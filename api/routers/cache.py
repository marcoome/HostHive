"""Cache management router -- /api/v1/cache.

Manages Redis, Memcached, Varnish, and PHP OPcache services directly on the
local host. This router does NOT proxy to the HostHive agent on port 7080 --
all operations use direct shell/subprocess calls (redis-cli, varnishadm,
varnishstat, php CLI, nc) and direct filesystem access. Any blocking
filesystem work is offloaded to the default executor via
``asyncio.get_running_loop().run_in_executor()`` to keep the event loop
responsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.core.security import get_current_user
from api.models.users import User

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _run(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "Command timed out"
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


async def _service_is_active(name: str) -> bool:
    """Check whether a systemd service is active."""
    rc, out, _ = await _run(f"systemctl is-active {name}")
    return out.strip() == "active"


async def _to_thread(func, *args, **kwargs):
    """Run a blocking callable in the default executor."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(None, func, *args)


def _write_temp_php(script: str, prefix: str) -> str:
    """Synchronously write a PHP script to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".php", prefix=prefix, delete=False
    ) as tmp:
        tmp.write(script)
        return tmp.name


def _unlink_quiet(path: str) -> None:
    """Synchronously delete a file, ignoring missing-file errors."""
    Path(path).unlink(missing_ok=True)


def _write_text_quiet(path: str, content: str) -> bool:
    """Synchronously write a text file. Returns True on success."""
    try:
        Path(path).write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def _parse_redis_info(raw: str) -> dict[str, Any]:
    """Parse `redis-cli INFO` output into a dictionary."""
    info: dict[str, Any] = {}
    current_section = ""
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            if line.startswith("# "):
                current_section = line[2:].lower()
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()
    return info


def _parse_memcached_stats(raw: str) -> dict[str, str]:
    """Parse ``echo 'stats' | nc localhost 11211`` output."""
    stats: dict[str, str] = {}
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("STAT "):
            parts = line.split(None, 2)
            if len(parts) == 3:
                stats[parts[1]] = parts[2]
    return stats


# ---------------------------------------------------------------------------
# GET /status -- overview of all cache services
# ---------------------------------------------------------------------------
@router.get("/status")
async def cache_status(
    current_user: User = Depends(get_current_user),
):
    """Return the running status of all cache services."""
    _require_admin(current_user)

    redis_active, memcached_active, varnish_active = await asyncio.gather(
        _service_is_active("redis-server"),
        _service_is_active("memcached"),
        _service_is_active("varnish"),
    )

    # Check OPcache by looking for the PHP module
    rc, opcache_out, _ = await _run("php -m 2>/dev/null | grep -i opcache")
    opcache_loaded = rc == 0 and "opcache" in opcache_out.lower()

    return {
        "redis": {"active": redis_active},
        "memcached": {"active": memcached_active},
        "varnish": {"active": varnish_active},
        "opcache": {"loaded": opcache_loaded},
    }


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
@router.get("/redis/info")
async def redis_info(
    current_user: User = Depends(get_current_user),
):
    """Return parsed output from ``redis-cli INFO``."""
    _require_admin(current_user)

    rc, out, err = await _run("redis-cli INFO")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"redis-cli INFO failed: {err or out}")

    parsed = _parse_redis_info(out)
    return {
        "connected_clients": parsed.get("connected_clients", "0"),
        "used_memory_human": parsed.get("used_memory_human", "0B"),
        "used_memory_peak_human": parsed.get("used_memory_peak_human", "0B"),
        "total_commands_processed": parsed.get("total_commands_processed", "0"),
        "keyspace_hits": parsed.get("keyspace_hits", "0"),
        "keyspace_misses": parsed.get("keyspace_misses", "0"),
        "uptime_in_seconds": parsed.get("uptime_in_seconds", "0"),
        "redis_version": parsed.get("redis_version", "unknown"),
        "db_count": sum(1 for k in parsed if k.startswith("db")),
        "raw": parsed,
    }


@router.post("/redis/flush")
async def redis_flush(
    current_user: User = Depends(get_current_user),
):
    """Flush the entire Redis cache (FLUSHALL)."""
    _require_admin(current_user)

    rc, out, err = await _run("redis-cli FLUSHALL")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"redis-cli FLUSHALL failed: {err or out}")

    logger.info("Redis FLUSHALL executed by %s", current_user.username)
    return {"detail": "Redis cache flushed.", "output": out}


@router.post("/redis/flush-db/{db_index}")
async def redis_flush_db(
    db_index: int,
    current_user: User = Depends(get_current_user),
):
    """Flush a specific Redis database."""
    _require_admin(current_user)

    if db_index < 0 or db_index > 15:
        raise HTTPException(status_code=400, detail="db_index must be 0-15.")

    rc, out, err = await _run(f"redis-cli -n {db_index} FLUSHDB")
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"FLUSHDB failed: {err or out}")

    logger.info("Redis FLUSHDB %d executed by %s", db_index, current_user.username)
    return {"detail": f"Redis database {db_index} flushed.", "output": out}


# ---------------------------------------------------------------------------
# OPcache
# ---------------------------------------------------------------------------
@router.get("/opcache/status")
async def opcache_status(
    current_user: User = Depends(get_current_user),
):
    """Return OPcache statistics by executing a temporary PHP script."""
    _require_admin(current_user)

    php_script = """<?php
header('Content-Type: application/json');
if (!function_exists('opcache_get_status')) {
    echo json_encode(["error" => "OPcache not available"]);
    exit(1);
}
$status = opcache_get_status(false);
$config = opcache_get_configuration();
echo json_encode([
    "enabled"             => $status["opcache_enabled"] ?? false,
    "used_memory_mb"      => round(($status["memory_usage"]["used_memory"] ?? 0) / 1048576, 2),
    "free_memory_mb"      => round(($status["memory_usage"]["free_memory"] ?? 0) / 1048576, 2),
    "wasted_memory_mb"    => round(($status["memory_usage"]["wasted_memory"] ?? 0) / 1048576, 2),
    "hit_rate"            => round($status["opcache_statistics"]["opcache_hit_rate"] ?? 0, 2),
    "cached_scripts"      => $status["opcache_statistics"]["num_cached_scripts"] ?? 0,
    "cached_keys"         => $status["opcache_statistics"]["num_cached_keys"] ?? 0,
    "max_cached_keys"     => $status["opcache_statistics"]["max_cached_keys"] ?? 0,
    "hits"                => $status["opcache_statistics"]["hits"] ?? 0,
    "misses"              => $status["opcache_statistics"]["misses"] ?? 0,
    "max_memory_mb"       => round(($config["directives"]["opcache.memory_consumption"] ?? 0) / 1048576, 2),
    "interned_strings_mb" => round(($config["directives"]["opcache.interned_strings_buffer"] ?? 0), 2),
]);
"""
    tmp_path = await _to_thread(_write_temp_php, php_script, "hosthive_opcache_")

    try:
        rc, out, err = await _run(f"php {tmp_path}")
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"OPcache status failed: {err or out}")

        try:
            data = await _to_thread(json.loads, out)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail=f"Invalid JSON from PHP: {out[:500]}")

        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])

        return data
    finally:
        await _to_thread(_unlink_quiet, tmp_path)


@router.post("/opcache/reset")
async def opcache_reset(
    current_user: User = Depends(get_current_user),
):
    """Reset the PHP OPcache by executing a temporary PHP script via CLI.

    For FPM pools, this also attempts a curl to localhost to trigger the reset
    in the FPM process context.
    """
    _require_admin(current_user)

    php_script = """<?php
if (function_exists('opcache_reset')) {
    opcache_reset();
    echo json_encode(["detail" => "OPcache reset successfully"]);
} else {
    echo json_encode(["error" => "OPcache not available"]);
    exit(1);
}
"""
    tmp_path = await _to_thread(
        _write_temp_php, php_script, "hosthive_opcache_reset_"
    )

    try:
        rc, out, err = await _run(f"php {tmp_path}")

        # Also attempt to reset via a web-accessible path so that the FPM
        # worker pool (which has its own opcache) is refreshed. This is a
        # best-effort operation against the local web server only -- it is
        # NOT a call to the HostHive agent on :7080.
        web_reset_path = "/var/www/html/_hosthive_opcache_reset.php"
        wrote_web = await _to_thread(
            _write_text_quiet,
            web_reset_path,
            '<?php opcache_reset(); echo "ok"; unlink(__FILE__);',
        )
        if wrote_web:
            try:
                await _run(
                    "curl -s -m 5 http://127.0.0.1/_hosthive_opcache_reset.php"
                )
            except Exception:
                pass  # Best effort for FPM context reset
            finally:
                await _to_thread(_unlink_quiet, web_reset_path)

        if rc != 0:
            raise HTTPException(status_code=500, detail=f"OPcache reset failed: {err or out}")

        logger.info("OPcache reset executed by %s", current_user.username)
        return {"detail": "OPcache reset successfully (CLI). FPM reset attempted."}
    finally:
        await _to_thread(_unlink_quiet, tmp_path)


# ---------------------------------------------------------------------------
# Varnish
# ---------------------------------------------------------------------------
@router.get("/varnish/status")
async def varnish_status(
    current_user: User = Depends(get_current_user),
):
    """Return Varnish cache statistics."""
    _require_admin(current_user)

    active = await _service_is_active("varnish")
    if not active:
        return {"active": False, "stats": {}}

    rc, out, err = await _run("varnishstat -1 -j 2>/dev/null")
    if rc != 0:
        # Fallback to text output
        rc2, out2, _ = await _run("varnishstat -1 2>/dev/null")
        stats: dict[str, str] = {}
        for line in out2.split("\n"):
            parts = line.split(None, 2)
            if len(parts) >= 2:
                stats[parts[0]] = parts[1]
        return {"active": True, "stats": stats}

    try:
        data = await _to_thread(json.loads, out)
    except json.JSONDecodeError:
        return {"active": True, "stats": {}, "raw": out[:2000]}

    return {"active": True, "stats": data}


@router.post("/varnish/purge")
async def varnish_purge(
    current_user: User = Depends(get_current_user),
):
    """Purge the entire Varnish cache."""
    _require_admin(current_user)

    rc, out, err = await _run('varnishadm "ban req.url ~ ."')
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Varnish purge failed: {err or out}",
        )

    logger.info("Varnish cache purged by %s", current_user.username)
    return {"detail": "Varnish cache purged.", "output": out}


@router.post("/varnish/purge-url")
async def varnish_purge_url(
    url_pattern: str,
    current_user: User = Depends(get_current_user),
):
    """Purge Varnish cache entries matching a URL pattern."""
    _require_admin(current_user)

    # Sanitise pattern to prevent injection
    safe_pattern = url_pattern.replace('"', '\\"').replace("'", "\\'")
    rc, out, err = await _run(f'varnishadm "ban req.url ~ {safe_pattern}"')
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Varnish purge failed: {err or out}",
        )

    logger.info("Varnish URL purge '%s' by %s", url_pattern, current_user.username)
    return {"detail": f"Varnish cache purged for pattern: {url_pattern}", "output": out}


# ---------------------------------------------------------------------------
# Memcached
# ---------------------------------------------------------------------------
@router.get("/memcached/stats")
async def memcached_stats(
    current_user: User = Depends(get_current_user),
):
    """Return Memcached statistics via the stats command."""
    _require_admin(current_user)

    active = await _service_is_active("memcached")
    if not active:
        return {"active": False, "stats": {}}

    rc, out, err = await _run('echo "stats" | nc -w 2 localhost 11211')
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Memcached stats failed: {err or out}",
        )

    stats = _parse_memcached_stats(out)
    return {
        "active": True,
        "pid": stats.get("pid", ""),
        "uptime": stats.get("uptime", "0"),
        "curr_connections": stats.get("curr_connections", "0"),
        "total_connections": stats.get("total_connections", "0"),
        "curr_items": stats.get("curr_items", "0"),
        "total_items": stats.get("total_items", "0"),
        "bytes": stats.get("bytes", "0"),
        "limit_maxbytes": stats.get("limit_maxbytes", "0"),
        "get_hits": stats.get("get_hits", "0"),
        "get_misses": stats.get("get_misses", "0"),
        "evictions": stats.get("evictions", "0"),
        "version": stats.get("version", "unknown"),
    }


@router.post("/memcached/flush")
async def memcached_flush(
    current_user: User = Depends(get_current_user),
):
    """Flush the entire Memcached cache."""
    _require_admin(current_user)

    rc, out, err = await _run('echo "flush_all" | nc -w 2 localhost 11211')
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Memcached flush failed: {err or out}",
        )

    logger.info("Memcached flush_all executed by %s", current_user.username)
    return {"detail": "Memcached cache flushed.", "output": out}
