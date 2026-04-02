"""
Resource executor -- per-user cgroups v2 resource limits.

Manages CPU, memory, and I/O limits for hosting users via Linux cgroups v2
(Debian 12 default).  Also manages per-domain PHP-FPM pool limits.

All subprocess calls use list arguments.  shell=True is NEVER used.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agent.executors._helpers import atomic_write, safe_domain, safe_username

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CGROUP_BASE = Path("/sys/fs/cgroup")
HOSTHIVE_CGROUP = CGROUP_BASE / "hosthive"
PHP_FPM_POOL_DIR = Path("/etc/php")  # /etc/php/<version>/fpm/pool.d/
RESOURCE_META_DIR = Path("/opt/novapanel/data/resource_limits")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_cgroup(username: str) -> Path:
    """Create a cgroup v2 slice for the given user under hosthive."""
    cgroup_path = HOSTHIVE_CGROUP / username
    cgroup_path.mkdir(parents=True, exist_ok=True)

    # Enable controllers
    controllers_file = HOSTHIVE_CGROUP / "cgroup.subtree_control"
    if controllers_file.exists():
        current = controllers_file.read_text().strip()
        needed = {"+cpu", "+memory", "+io"}
        already = set(current.split())
        missing = needed - already
        if missing:
            for ctrl in missing:
                try:
                    controllers_file.write_text(ctrl)
                except OSError:
                    pass  # Controller may not be available

    return cgroup_path


def _read_cgroup_stat(cgroup_path: Path, filename: str) -> str:
    """Read a cgroup v2 stat file, return empty string on error."""
    path = cgroup_path / filename
    if path.exists():
        try:
            return path.read_text().strip()
        except OSError:
            pass
    return ""


def _write_cgroup_value(cgroup_path: Path, filename: str, value: str) -> None:
    """Write a value to a cgroup v2 control file."""
    path = cgroup_path / filename
    path.write_text(value)


def _save_limit_meta(username: str, limits: dict[str, Any]) -> None:
    """Persist limit settings to metadata file."""
    RESOURCE_META_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = RESOURCE_META_DIR / f"{username}.json"
    atomic_write(meta_path, json.dumps(limits, indent=2))


def _load_limit_meta(username: str) -> dict[str, Any]:
    """Load persisted limit settings."""
    meta_path = RESOURCE_META_DIR / f"{username}.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {}


def _find_php_versions() -> list[str]:
    """Detect installed PHP versions."""
    versions = []
    if PHP_FPM_POOL_DIR.exists():
        for entry in sorted(PHP_FPM_POOL_DIR.iterdir()):
            if entry.is_dir() and re.match(r"\d+\.\d+", entry.name):
                fpm_dir = entry / "fpm" / "pool.d"
                if fpm_dir.exists():
                    versions.append(entry.name)
    return versions


def _php_pool_path(domain: str, php_version: str) -> Path:
    """Return the PHP-FPM pool config path for a domain."""
    return PHP_FPM_POOL_DIR / php_version / "fpm" / "pool.d" / f"{domain}.conf"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def set_user_limits(
    username: str,
    cpu_percent: int = 100,
    memory_mb: int = 1024,
    io_weight: int = 100,
) -> dict[str, Any]:
    """Create or update cgroup v2 limits for a hosting user.

    Args:
        username: System username.
        cpu_percent: CPU limit as percentage of one core (100 = 1 core).
        memory_mb: Memory limit in megabytes.
        io_weight: I/O weight (1-10000, default 100).
    """
    username = safe_username(username)

    if cpu_percent < 1 or cpu_percent > 10000:
        raise ValueError("cpu_percent must be between 1 and 10000")
    if memory_mb < 32:
        raise ValueError("memory_mb must be at least 32")
    if io_weight < 1 or io_weight > 10000:
        raise ValueError("io_weight must be between 1 and 10000")

    cgroup_path = _ensure_cgroup(username)

    # CPU limit: cpu.max is "quota period" in microseconds
    # 100% of one core = "100000 100000"
    quota = cpu_percent * 1000  # Convert percentage to microseconds
    _write_cgroup_value(cgroup_path, "cpu.max", f"{quota} 100000")

    # Memory limit
    memory_bytes = memory_mb * 1024 * 1024
    _write_cgroup_value(cgroup_path, "memory.max", str(memory_bytes))

    # I/O weight
    _write_cgroup_value(cgroup_path, "io.weight", f"default {io_weight}")

    # Persist metadata
    limits = {
        "username": username,
        "cpu_percent": cpu_percent,
        "memory_mb": memory_mb,
        "io_weight": io_weight,
    }
    _save_limit_meta(username, limits)

    return limits


def get_user_usage(username: str) -> dict[str, Any]:
    """Return current CPU, RAM, and I/O usage for a user from cgroup stats."""
    username = safe_username(username)
    cgroup_path = HOSTHIVE_CGROUP / username

    if not cgroup_path.exists():
        raise FileNotFoundError(f"No cgroup found for user {username}")

    usage: dict[str, Any] = {"username": username}

    # CPU usage (from cpu.stat)
    cpu_stat = _read_cgroup_stat(cgroup_path, "cpu.stat")
    if cpu_stat:
        cpu_data: dict[str, int] = {}
        for line in cpu_stat.splitlines():
            parts = line.split()
            if len(parts) == 2:
                cpu_data[parts[0]] = int(parts[1])
        usage["cpu"] = {
            "usage_usec": cpu_data.get("usage_usec", 0),
            "user_usec": cpu_data.get("user_usec", 0),
            "system_usec": cpu_data.get("system_usec", 0),
        }

    # Memory usage
    mem_current = _read_cgroup_stat(cgroup_path, "memory.current")
    mem_max = _read_cgroup_stat(cgroup_path, "memory.max")
    if mem_current:
        current_bytes = int(mem_current)
        usage["memory"] = {
            "current_bytes": current_bytes,
            "current_mb": round(current_bytes / (1024 * 1024), 1),
        }
        if mem_max and mem_max != "max":
            max_bytes = int(mem_max)
            usage["memory"]["max_bytes"] = max_bytes
            usage["memory"]["max_mb"] = round(max_bytes / (1024 * 1024), 1)
            usage["memory"]["percent"] = round(current_bytes / max_bytes * 100, 1) if max_bytes > 0 else 0

    # I/O usage (from io.stat)
    io_stat = _read_cgroup_stat(cgroup_path, "io.stat")
    if io_stat:
        io_data: list[dict[str, Any]] = []
        for line in io_stat.splitlines():
            parts = line.split()
            if parts:
                entry: dict[str, Any] = {"device": parts[0]}
                for kv in parts[1:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        entry[k] = int(v)
                io_data.append(entry)
        usage["io"] = io_data

    # Configured limits
    usage["limits"] = _load_limit_meta(username)

    return usage


def remove_user_limits(username: str) -> dict[str, Any]:
    """Remove cgroup and persisted limits for a user."""
    username = safe_username(username)
    cgroup_path = HOSTHIVE_CGROUP / username

    # Remove cgroup (must be empty of processes first)
    if cgroup_path.exists():
        try:
            cgroup_path.rmdir()
        except OSError:
            # Move processes to parent cgroup first
            procs_file = cgroup_path / "cgroup.procs"
            parent_procs = HOSTHIVE_CGROUP / "cgroup.procs"
            if procs_file.exists():
                for pid in procs_file.read_text().strip().splitlines():
                    try:
                        parent_procs.write_text(pid.strip())
                    except OSError:
                        pass
            try:
                cgroup_path.rmdir()
            except OSError as exc:
                raise ValueError(f"Could not remove cgroup for {username}: {exc}")

    # Remove metadata
    meta_path = RESOURCE_META_DIR / f"{username}.json"
    if meta_path.exists():
        meta_path.unlink()

    return {"username": username, "removed": True}


def list_user_limits() -> list[dict[str, Any]]:
    """Return all users with their configured resource limits."""
    RESOURCE_META_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for meta_file in sorted(RESOURCE_META_DIR.glob("*.json")):
        try:
            data = json.loads(meta_file.read_text())
            results.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return results


def set_php_fpm_limits(
    domain: str,
    max_children: int = 5,
    memory_limit: str = "256M",
    php_version: str = "8.2",
) -> dict[str, Any]:
    """Create or update a per-domain PHP-FPM pool with resource limits.

    Args:
        domain: Domain name (used as pool name).
        max_children: Maximum number of PHP-FPM child processes.
        memory_limit: PHP memory_limit (e.g. "256M").
        php_version: PHP version (e.g. "8.2").
    """
    domain = safe_domain(domain)

    if max_children < 1 or max_children > 1000:
        raise ValueError("max_children must be between 1 and 1000")

    pool_path = _php_pool_path(domain, php_version)

    # Pool name must be safe (alphanumeric + dots + hyphens)
    pool_name = domain.replace(".", "_")

    pool_config = f"""[{pool_name}]
; HostHive managed PHP-FPM pool for {domain}

user = www-data
group = www-data

listen = /run/php/php{php_version}-fpm-{pool_name}.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660

pm = dynamic
pm.max_children = {max_children}
pm.start_servers = {min(2, max_children)}
pm.min_spare_servers = 1
pm.max_spare_servers = {min(3, max_children)}
pm.max_requests = 500

; Per-process memory limit
php_admin_value[memory_limit] = {memory_limit}

; Logging
php_admin_flag[log_errors] = on
php_admin_value[error_log] = /var/log/php-fpm/{pool_name}.error.log

; Security
php_admin_value[open_basedir] = /home/{domain}/:/tmp/:/var/tmp/
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen
php_admin_value[upload_max_filesize] = 50M
php_admin_value[post_max_size] = 55M
"""

    pool_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(pool_path, pool_config)

    # Ensure log directory exists
    Path("/var/log/php-fpm").mkdir(parents=True, exist_ok=True)

    return {
        "domain": domain,
        "php_version": php_version,
        "pool_name": pool_name,
        "max_children": max_children,
        "memory_limit": memory_limit,
        "config_path": str(pool_path),
    }


def get_domain_resource_usage(domain: str) -> dict[str, Any]:
    """Return current resource usage for a domain (via its PHP-FPM pool)."""
    domain = safe_domain(domain)
    pool_name = domain.replace(".", "_")

    usage: dict[str, Any] = {"domain": domain}

    # Try to find running PHP-FPM processes for this pool
    result = subprocess.run(
        ["pgrep", "-a", "-f", f"php-fpm.*{pool_name}"],
        capture_output=True,
        text=True,
        timeout=15,
    )

    pids = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if parts:
            pids.append(parts[0])

    usage["process_count"] = len(pids)
    usage["pids"] = pids

    # Get memory usage of these processes
    if pids:
        total_rss = 0
        for pid in pids:
            stat_path = Path(f"/proc/{pid}/status")
            if stat_path.exists():
                try:
                    for line in stat_path.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                total_rss += int(parts[1])  # in kB
                except (OSError, ValueError):
                    pass
        usage["memory_kb"] = total_rss
        usage["memory_mb"] = round(total_rss / 1024, 1)

    return usage
