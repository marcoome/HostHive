"""Log management router -- /api/v1/logs (admin only).

Provides log browsing, searching, rotation, and access log statistics.

This router reads system log files DIRECTLY from disk using Python's built-in
file APIs (no agent proxy, no shell calls for reads). Blocking I/O is offloaded
to a thread pool via ``asyncio.get_running_loop().run_in_executor()`` so the
event loop stays responsive.

Falls back to ``journalctl`` (subprocess) only when a log file does not exist
on disk. Log rotation still uses ``logrotate``/``nginx -s reopen`` because
those are inherently external operations.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import logging
import os
import re
import subprocess
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

router = APIRouter()
log = logging.getLogger("novapanel.logs")

_admin = require_role("admin")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATHS: dict[str, str] = {
    "nginx-access": "/var/log/nginx/access.log",
    "nginx-error": "/var/log/nginx/error.log",
    "hosthive-api": "/opt/hosthive/logs/api.log",
    "hosthive-worker": "/opt/hosthive/logs/worker.log",
    "postgresql": "/var/log/postgresql/postgresql-*-main.log",
    "mail": "/var/log/mail.log",
    "auth": "/var/log/auth.log",
    "syslog": "/var/log/syslog",
    "fail2ban": "/var/log/fail2ban.log",
    "exim4": "/var/log/exim4/mainlog",
    "dovecot": "/var/log/dovecot.log",
    "proftpd": "/var/log/proftpd/proftpd.log",
    "php-fpm": "/var/log/php*-fpm.log",
    "ufw": "/var/log/ufw.log",
    "kern": "/var/log/kern.log",
    "dpkg": "/var/log/dpkg.log",
    "apt-history": "/var/log/apt/history.log",
    "clamav": "/var/log/clamav/clamav.log",
    "mysql": "/var/log/mysql/error.log",
    "daemon": "/var/log/daemon.log",
}

_LOG_DESCRIPTIONS: dict[str, str] = {
    "nginx-access": "Nginx access logs",
    "nginx-error": "Nginx error logs",
    "hosthive-api": "NovaPanel API logs",
    "hosthive-worker": "NovaPanel Celery worker logs",
    "postgresql": "PostgreSQL database logs",
    "mail": "Mail system logs",
    "auth": "Authentication and SSH logs",
    "syslog": "System log (general)",
    "fail2ban": "Fail2ban intrusion prevention logs",
    "exim4": "Exim4 mail transfer agent logs",
    "dovecot": "Dovecot IMAP server logs",
    "proftpd": "ProFTPD server logs",
    "php-fpm": "PHP-FPM logs",
    "ufw": "UFW firewall logs",
    "kern": "Kernel messages",
    "dpkg": "Package manager (dpkg) logs",
    "apt-history": "APT package installation history",
    "clamav": "ClamAV antivirus logs",
    "mysql": "MySQL/MariaDB error logs",
    "daemon": "Daemon logs",
}

# Cap how many bytes we'll scan from the tail of a file for a single request,
# to keep memory usage bounded even on huge access logs.
_MAX_TAIL_BYTES = 32 * 1024 * 1024  # 32 MiB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _run_in_executor(func, *args):
    """Run a blocking callable in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def _run_async(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return await _run_in_executor(lambda: _run(cmd, timeout))


def _resolve_log_path(name: str) -> Optional[str]:
    """Resolve a log name to an actual file path, supporting glob patterns."""
    import glob as _glob
    pattern = _LOG_PATHS.get(name)
    if not pattern:
        return None

    matched = sorted(_glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return matched[0] if matched else None


def _sanitize_log_name(name: str) -> str:
    """Sanitize log name to prevent path traversal."""
    cleaned = re.sub(r"[^a-zA-Z0-9._\-]", "", name)
    if not cleaned or cleaned != name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid log name: {name}",
        )
    return cleaned


def _open_log(path: str):
    """Open a log file, transparently handling .gz rotation."""
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _tail_lines_blocking(path: str, num_lines: int) -> tuple[list[str], int]:
    """Read the last ``num_lines`` lines of ``path`` efficiently.

    Returns ``(lines, total_lines_in_file)``.

    Strategy: seek to end, read backwards in 64 KiB chunks until we have
    enough newlines or hit the cap. For .gz files we fall back to a
    streaming deque since random access isn't supported.
    """
    if path.endswith(".gz"):
        with _open_log(path) as fh:
            buf: deque[str] = deque(maxlen=num_lines)
            total = 0
            for line in fh:
                buf.append(line.rstrip("\n"))
                total += 1
            return list(buf), total

    file_size = os.path.getsize(path)
    if file_size == 0:
        return [], 0

    block_size = 64 * 1024
    data = bytearray()
    bytes_read = 0
    newlines = 0

    with open(path, "rb") as fh:
        pos = file_size
        while pos > 0 and newlines <= num_lines and bytes_read < _MAX_TAIL_BYTES:
            read_size = min(block_size, pos)
            pos -= read_size
            fh.seek(pos)
            chunk = fh.read(read_size)
            data[0:0] = chunk
            bytes_read += read_size
            newlines = data.count(b"\n")

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > num_lines:
        lines = lines[-num_lines:]

    # Total line count: only counted if we read the entire file. Otherwise
    # estimate using a separate streaming pass-but cap that too.
    if bytes_read >= file_size:
        total = len(lines)
    else:
        total = _count_lines_blocking(path)

    return lines, total


def _count_lines_blocking(path: str) -> int:
    """Count newlines in a file in a streaming fashion."""
    if not os.path.exists(path):
        return 0
    total = 0
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                total += chunk.count(b"\n")
    except OSError:
        return 0
    return total


def _read_tail_text_blocking(path: str, max_lines: int) -> str:
    """Return the last ``max_lines`` of ``path`` as a single text blob."""
    lines, _ = _tail_lines_blocking(path, max_lines)
    return "\n".join(lines)


def _search_file_blocking(
    path: str, pattern: re.Pattern, max_lines: int, max_matches: int = 500,
) -> tuple[list[str], int]:
    """Search the last ``max_lines`` of a file for a regex pattern.

    Returns ``(matches, total_match_count)``. Each match line is prefixed
    with ``"<lineno>:"`` to mimic ``grep -n`` output.
    """
    lines, _ = _tail_lines_blocking(path, max_lines)
    matches: list[str] = []
    total = 0
    for idx, line in enumerate(lines, start=1):
        if pattern.search(line):
            total += 1
            if len(matches) < max_matches:
                matches.append(f"{idx}:{line}")
    return matches, total


# ---------------------------------------------------------------------------
# GET /available -- List available log files
# ---------------------------------------------------------------------------

@router.get("/available", status_code=status.HTTP_200_OK)
async def list_available_logs(
    request: Request,
    admin: User = Depends(_admin),
):
    """List all known log files and their availability on the system."""

    def _gather() -> dict[str, Any]:
        available: list[dict] = []
        for name, pattern in _LOG_PATHS.items():
            log_path = _resolve_log_path(name)
            exists = log_path is not None and os.path.exists(log_path)

            entry: dict[str, Any] = {
                "name": name,
                "description": _LOG_DESCRIPTIONS.get(name, name),
                "pattern": pattern,
                "exists": exists,
            }

            if exists and log_path:
                try:
                    stat = os.stat(log_path)
                    entry["path"] = log_path
                    entry["size_bytes"] = stat.st_size
                    entry["size_human"] = _human_size(stat.st_size)
                    entry["modified"] = datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc,
                    ).isoformat()
                except Exception:
                    pass

            available.append(entry)

        # Discover any rotated log files
        rotated_count = 0
        import glob as _glob
        for name, pattern in _LOG_PATHS.items():
            base = pattern.replace("*", "")
            for _ in _glob.glob(f"{base}*.gz") + _glob.glob(f"{base}*.1"):
                rotated_count += 1

        return {
            "logs": available,
            "total": len(available),
            "available_count": sum(1 for l in available if l["exists"]),
            "rotated_files": rotated_count,
        }

    return await _run_in_executor(_gather)


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    size: float = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# ---------------------------------------------------------------------------
# GET /{name} -- Read log with pagination
# ---------------------------------------------------------------------------

@router.get("/{name}", status_code=status.HTTP_200_OK)
async def read_log(
    name: str,
    lines: int = Query(200, ge=1, le=5000, description="Number of lines to return"),
    offset: int = Query(0, ge=0, description="Line offset (skip N lines from end)"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Line order: asc (oldest first) or desc (newest first)"),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Read a log file with pagination support.

    Reads the file directly from disk via a thread-pool executor. Falls back
    to ``journalctl`` only if the log file is missing.
    """
    name = _sanitize_log_name(name)
    log_path = _resolve_log_path(name)

    if not log_path or not os.path.exists(log_path):
        return await _read_from_journalctl(name, lines, offset, order)

    try:
        # Pull (offset + lines) from the tail, then slice. Cap to a sane limit.
        fetch = min(offset + lines, 50000)
        all_lines, total = await _run_in_executor(_tail_lines_blocking, log_path, fetch)

        # Apply offset (skip N lines from the newest end)
        if offset > 0:
            if offset >= len(all_lines):
                all_lines = []
            else:
                all_lines = all_lines[: len(all_lines) - offset]

        # Keep only the last ``lines`` after offset trimming
        if len(all_lines) > lines:
            all_lines = all_lines[-lines:]

        # Apply ordering: file order is asc (oldest first); flip for desc
        if order == "desc":
            all_lines = list(reversed(all_lines))

        return {
            "name": name,
            "file": log_path,
            "lines": all_lines,
            "count": len(all_lines),
            "total_lines": total,
            "offset": offset,
            "order": order,
        }

    except PermissionError:
        log.warning("Permission denied reading %s", log_path)
        return await _read_from_journalctl(name, lines, offset, order)
    except Exception as exc:
        log.exception("Failed to read log %s: %s", log_path, exc)
        return await _read_from_journalctl(name, lines, offset, order)


async def _read_from_journalctl(
    name: str, lines: int, offset: int, order: str,
) -> dict[str, Any]:
    """Fallback: read logs from journalctl when the file doesn't exist."""
    unit_map: dict[str, str] = {
        "nginx-access": "nginx",
        "nginx-error": "nginx",
        "hosthive-api": "hosthive-api",
        "hosthive-worker": "hosthive-worker",
        "postgresql": "postgresql",
        "mail": "postfix",
        "auth": "ssh",
        "fail2ban": "fail2ban",
        "exim4": "exim4",
        "dovecot": "dovecot",
        "proftpd": "proftpd",
        "clamav": "clamav-daemon",
    }

    unit = unit_map.get(name, name)
    cmd = ["journalctl", "-u", unit, "-n", str(lines + offset), "--no-pager", "-o", "short-iso"]

    if order == "desc":
        cmd.append("-r")

    try:
        result = await _run_async(cmd, timeout=10)
        if result.returncode != 0:
            return {
                "name": name,
                "lines": [],
                "count": 0,
                "error": f"No logs found for {name}",
                "source": "journalctl",
            }

        all_lines = result.stdout.splitlines()

        if offset > 0:
            all_lines = all_lines[offset:]
        all_lines = all_lines[:lines]

        return {
            "name": name,
            "lines": all_lines,
            "count": len(all_lines),
            "source": "journalctl",
            "unit": unit,
            "offset": offset,
            "order": order,
        }
    except Exception:
        return {
            "name": name,
            "lines": [],
            "count": 0,
            "error": f"Failed to read logs for {name}",
        }


# ---------------------------------------------------------------------------
# GET /{name}/search -- Search logs
# ---------------------------------------------------------------------------

@router.get("/{name}/search", status_code=status.HTTP_200_OK)
async def search_log(
    name: str,
    q: str = Query(..., min_length=1, max_length=256, description="Search query (regex supported)"),
    lines: int = Query(500, ge=1, le=10000, description="Max lines to search through"),
    case_sensitive: bool = Query(False, description="Case-sensitive search"),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Search through a log file using Python's ``re`` module.

    No shell, no grep, no agent. Reads the tail of the file directly and
    matches against a compiled regex in a thread-pool worker.
    """
    name = _sanitize_log_name(name)
    log_path = _resolve_log_path(name)

    # Compile the user-supplied regex safely. Reject invalid patterns up front.
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(q, flags)
    except re.error as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regex: {exc}",
        )

    if not log_path or not os.path.exists(log_path):
        return await _search_journalctl(name, q, lines, case_sensitive)

    try:
        matches, total = await _run_in_executor(
            _search_file_blocking, log_path, pattern, lines, 500,
        )
        return {
            "name": name,
            "file": log_path,
            "query": q,
            "case_sensitive": case_sensitive,
            "matches": matches,
            "match_count": total,
            "searched_lines": lines,
        }
    except PermissionError:
        log.warning("Permission denied searching %s", log_path)
        return await _search_journalctl(name, q, lines, case_sensitive)
    except Exception as exc:
        log.exception("Failed to search log %s: %s", log_path, exc)
        return await _search_journalctl(name, q, lines, case_sensitive)


async def _search_journalctl(
    name: str, query: str, lines: int, case_sensitive: bool,
) -> dict[str, Any]:
    """Fallback: search journalctl output when the file doesn't exist."""
    unit_map: dict[str, str] = {
        "nginx-access": "nginx",
        "nginx-error": "nginx",
        "hosthive-api": "hosthive-api",
        "postgresql": "postgresql",
        "auth": "ssh",
        "fail2ban": "fail2ban",
    }
    unit = unit_map.get(name, name)

    try:
        cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"]
        cmd += ["--grep", query]
        if not case_sensitive:
            cmd += ["--case-sensitive=false"]

        result = await _run_async(cmd, timeout=15)
        matches = result.stdout.strip().splitlines() if result.returncode == 0 else []

        return {
            "name": name,
            "query": query,
            "case_sensitive": case_sensitive,
            "matches": matches[:500],
            "match_count": len(matches),
            "source": "journalctl",
        }
    except Exception:
        return {
            "name": name,
            "query": query,
            "matches": [],
            "match_count": 0,
            "error": f"Search failed for {name}",
        }


# ---------------------------------------------------------------------------
# POST /rotate -- Force log rotation
# ---------------------------------------------------------------------------

@router.post("/rotate", status_code=status.HTTP_200_OK)
async def force_log_rotation(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Force log rotation using logrotate."""
    _log_activity(db, request, admin.id, "logs.rotate", "Forced log rotation")

    results: list[dict] = []

    # Run logrotate force
    try:
        result = await _run_async(
            ["sudo", "logrotate", "--force", "/etc/logrotate.conf"],
            timeout=60,
        )
        results.append({
            "action": "logrotate",
            "success": result.returncode == 0,
            "output": result.stdout.strip()[-500:] if result.stdout else "",
            "errors": result.stderr.strip()[-500:] if result.stderr else "",
        })
    except subprocess.TimeoutExpired:
        results.append({
            "action": "logrotate",
            "success": False,
            "errors": "Logrotate timed out after 60 seconds",
        })
    except Exception as e:
        results.append({
            "action": "logrotate",
            "success": False,
            "errors": str(e),
        })

    # Also rotate nginx logs specifically
    try:
        result = await _run_async(
            ["sudo", "nginx", "-s", "reopen"],
            timeout=10,
        )
        results.append({
            "action": "nginx_reopen",
            "success": result.returncode == 0,
            "output": result.stdout.strip() if result.stdout else "",
        })
    except Exception:
        pass

    return {
        "status": "completed",
        "results": results,
        "detail": "Log rotation completed.",
    }


# ---------------------------------------------------------------------------
# GET /access-stats -- Parsed access log statistics
# ---------------------------------------------------------------------------

@router.get("/access-stats", status_code=status.HTTP_200_OK)
async def access_log_stats(
    lines: int = Query(10000, ge=100, le=100000, description="Number of recent log lines to analyze"),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Parse nginx access log and return statistics.

    Reads the access log directly from disk in a thread-pool worker, then
    parses it in pure Python.
    """
    log_path = _resolve_log_path("nginx-access")
    if not log_path or not os.path.exists(log_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nginx access log not found.",
        )

    try:
        tail_text = await _run_in_executor(_read_tail_text_blocking, log_path, lines)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied reading {log_path}.",
        )
    except Exception as exc:
        log.exception("Failed to read nginx access log: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot read nginx access log.",
        )

    # Parse nginx combined log format:
    # IP - - [timestamp] "METHOD URI PROTO" status bytes "referer" "user-agent"
    log_pattern = re.compile(
        r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"(\S+)\s+(\S+)\s+\S+"\s+(\d+)\s+(\d+)\s+"([^"]*)"\s+"([^"]*)"'
    )

    ip_counter: Counter = Counter()
    uri_counter: Counter = Counter()
    status_counter: Counter = Counter()
    method_counter: Counter = Counter()
    ua_counter: Counter = Counter()
    referer_counter: Counter = Counter()
    total_bytes = 0
    total_requests = 0
    error_count = 0
    parse_errors = 0

    for line in tail_text.splitlines():
        match = log_pattern.match(line)
        if not match:
            parse_errors += 1
            continue

        total_requests += 1
        ip = match.group(1)
        method = match.group(3)
        uri = match.group(4)
        status_code_str = match.group(5)
        bytes_sent = int(match.group(6)) if match.group(6).isdigit() else 0
        referer = match.group(7)
        user_agent = match.group(8)

        ip_counter[ip] += 1
        uri_counter[uri] += 1
        status_counter[status_code_str] += 1
        method_counter[method] += 1
        total_bytes += bytes_sent

        if int(status_code_str) >= 400:
            error_count += 1

        # Track referers (exclude "-" and self-referrals)
        if referer and referer != "-":
            referer_counter[referer] += 1

        # Simplify user agents
        ua_short = _simplify_user_agent(user_agent)
        if ua_short:
            ua_counter[ua_short] += 1

    # Build top lists
    top_ips = [{"ip": ip, "requests": count} for ip, count in ip_counter.most_common(20)]
    top_uris = [{"uri": uri, "requests": count} for uri, count in uri_counter.most_common(20)]
    status_dist = [{"status": s, "count": count} for s, count in sorted(status_counter.items())]
    method_dist = [{"method": m, "count": count} for m, count in method_counter.most_common()]
    top_referers = [{"referer": r, "count": count} for r, count in referer_counter.most_common(10)]
    top_agents = [{"agent": ua, "count": count} for ua, count in ua_counter.most_common(10)]

    return {
        "total_requests": total_requests,
        "total_bytes": total_bytes,
        "total_bytes_human": _human_size(total_bytes),
        "error_count": error_count,
        "error_rate": round(error_count / total_requests * 100, 2) if total_requests > 0 else 0,
        "parse_errors": parse_errors,
        "analyzed_lines": lines,
        "top_ips": top_ips,
        "top_uris": top_uris,
        "status_distribution": status_dist,
        "method_distribution": method_dist,
        "top_referers": top_referers,
        "top_user_agents": top_agents,
        "unique_ips": len(ip_counter),
        "unique_uris": len(uri_counter),
    }


def _simplify_user_agent(ua: str) -> str:
    """Simplify user agent string to browser/bot name."""
    if not ua or ua == "-":
        return ""
    ua_lower = ua.lower()
    if "googlebot" in ua_lower:
        return "Googlebot"
    if "bingbot" in ua_lower:
        return "Bingbot"
    if "yandexbot" in ua_lower:
        return "YandexBot"
    if "baiduspider" in ua_lower:
        return "Baidu"
    if "curl" in ua_lower:
        return "curl"
    if "wget" in ua_lower:
        return "wget"
    if "python" in ua_lower:
        return "Python"
    if "chrome" in ua_lower and "edge" not in ua_lower:
        return "Chrome"
    if "firefox" in ua_lower:
        return "Firefox"
    if "safari" in ua_lower and "chrome" not in ua_lower:
        return "Safari"
    if "edge" in ua_lower:
        return "Edge"
    if "msie" in ua_lower or "trident" in ua_lower:
        return "Internet Explorer"
    if "bot" in ua_lower or "spider" in ua_lower or "crawl" in ua_lower:
        return "Other Bot"
    return "Other"
