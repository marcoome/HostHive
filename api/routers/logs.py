"""Log management router -- /api/v1/logs (admin only).

Provides log browsing, searching, rotation, and access log statistics.
Extends the basic log reading already in server.py with advanced features.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def _run_async(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run(cmd, timeout))


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


# ---------------------------------------------------------------------------
# GET /available -- List available log files
# ---------------------------------------------------------------------------

@router.get("/available", status_code=status.HTTP_200_OK)
async def list_available_logs(
    request: Request,
    admin: User = Depends(_admin),
):
    """List all known log files and their availability on the system."""
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
                entry["modified"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            except Exception:
                pass

        available.append(entry)

    # Also discover any rotated log files
    rotated_count = 0
    for name, pattern in _LOG_PATHS.items():
        import glob as _glob
        base = pattern.replace("*", "")
        for rotated in _glob.glob(f"{base}*.gz") + _glob.glob(f"{base}*.1"):
            rotated_count += 1

    return {
        "logs": available,
        "total": len(available),
        "available_count": sum(1 for l in available if l["exists"]),
        "rotated_files": rotated_count,
    }


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


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
    """Read a log file with pagination support."""
    name = _sanitize_log_name(name)
    log_path = _resolve_log_path(name)

    if not log_path or not os.path.exists(log_path):
        # Try journalctl as fallback
        return await _read_from_journalctl(name, lines, offset, order)

    try:
        if offset > 0:
            # Use tail + head for offset: get (offset+lines) from end, then take first 'lines'
            total_lines = offset + lines
            result = await _run_async(
                ["sudo", "tail", "-n", str(total_lines), log_path],
                timeout=10,
            )
            if result.returncode != 0:
                result = await _run_async(["tail", "-n", str(total_lines), log_path], timeout=10)
        else:
            result = await _run_async(
                ["sudo", "tail", "-n", str(lines), log_path],
                timeout=10,
            )
            if result.returncode != 0:
                result = await _run_async(["tail", "-n", str(lines), log_path], timeout=10)

        if result.returncode != 0:
            return await _read_from_journalctl(name, lines, offset, order)

        all_lines = result.stdout.splitlines()

        # Apply offset
        if offset > 0 and len(all_lines) > lines:
            all_lines = all_lines[:len(all_lines) - offset]
            all_lines = all_lines[-lines:]

        # Apply ordering
        if order == "desc":
            all_lines.reverse()

        # Get total line count for the file
        try:
            wc_result = await _run_async(["wc", "-l", log_path], timeout=5)
            total = int(wc_result.stdout.split()[0]) if wc_result.returncode == 0 else len(all_lines)
        except Exception:
            total = len(all_lines)

        return {
            "name": name,
            "file": log_path,
            "lines": all_lines,
            "count": len(all_lines),
            "total_lines": total,
            "offset": offset,
            "order": order,
        }

    except Exception as e:
        return await _read_from_journalctl(name, lines, offset, order)


async def _read_from_journalctl(
    name: str, lines: int, offset: int, order: str,
) -> dict[str, Any]:
    """Fallback: read logs from journalctl."""
    # Map log names to systemd units
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

        # Apply offset
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
    """Search through a log file using grep."""
    name = _sanitize_log_name(name)
    log_path = _resolve_log_path(name)

    # Sanitize the search query (escape shell-dangerous chars but allow regex)
    # We pass the pattern directly to grep, so we need to be careful
    if any(c in q for c in [";", "|", "&", "`", "$", "(", ")", "{", "}", "<", ">"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query contains disallowed characters.",
        )

    if not log_path or not os.path.exists(log_path):
        # Fallback: search journalctl
        return await _search_journalctl(name, q, lines, case_sensitive)

    grep_cmd = ["sudo", "grep"]
    if not case_sensitive:
        grep_cmd.append("-i")
    grep_cmd.extend(["-n", "--color=never", "-E", q])

    # Use tail to limit the search scope, then pipe to grep
    try:
        # First get the last N lines, then search
        tail_result = await _run_async(["sudo", "tail", "-n", str(lines), log_path], timeout=10)
        if tail_result.returncode != 0:
            tail_result = await _run_async(["tail", "-n", str(lines), log_path], timeout=10)

        if tail_result.returncode != 0:
            return await _search_journalctl(name, q, lines, case_sensitive)

        # Search through the output
        loop = asyncio.get_running_loop()
        grep_result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["grep"] + (["-i"] if not case_sensitive else []) + ["-n", "--color=never", "-E", q],
                input=tail_result.stdout,
                capture_output=True,
                text=True,
                timeout=15,
            ),
        )

        matches = grep_result.stdout.strip().splitlines() if grep_result.stdout else []

        return {
            "name": name,
            "file": log_path,
            "query": q,
            "case_sensitive": case_sensitive,
            "matches": matches[:500],  # Limit returned matches
            "match_count": len(matches),
            "searched_lines": lines,
        }

    except Exception as e:
        return await _search_journalctl(name, q, lines, case_sensitive)


async def _search_journalctl(
    name: str, query: str, lines: int, case_sensitive: bool,
) -> dict[str, Any]:
    """Search journalctl output."""
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
        if not case_sensitive:
            cmd += ["--grep", query.lower()]
        else:
            cmd += ["--grep", query]

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
    """Parse nginx access log and return statistics."""
    log_path = _resolve_log_path("nginx-access")
    if not log_path or not os.path.exists(log_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nginx access log not found.",
        )

    try:
        result = await _run_async(["sudo", "tail", "-n", str(lines), log_path], timeout=15)
        if result.returncode != 0:
            result = await _run_async(["tail", "-n", str(lines), log_path], timeout=15)
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cannot read nginx access log.",
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Timeout reading access log.",
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

    for line in result.stdout.strip().splitlines():
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
