"""Server router -- /api/v1/server (admin only).

Every endpoint tries the agent first; if the agent is unreachable or errors,
it falls back to direct system commands (systemctl, psutil, ufw, fail2ban-client,
reading log files, etc.).

NOTE: The API process typically runs as user 'hosthive'.  Direct service control
(start/stop/restart) and firewall/fail2ban mutations require sudo privileges.
Ensure /etc/sudoers.d/hosthive contains lines like:
    hosthive ALL=(ALL) NOPASSWD: /usr/bin/systemctl start *
    hosthive ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop *
    hosthive ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
    hosthive ALL=(ALL) NOPASSWD: /usr/sbin/ufw *
    hosthive ALL=(ALL) NOPASSWD: /usr/bin/fail2ban-client *
"""

from __future__ import annotations

import asyncio
import glob as _glob
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role, verify_token
from api.models.activity_log import ActivityLog
from api.models.server_stats import ServerStat
from api.models.users import User
from api.schemas.server import FirewallRule
from config.security import ALLOWED_SERVICES

router = APIRouter()
log = logging.getLogger("novapanel.server")

_admin = require_role("admin")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All services to monitor (superset of ALLOWED_SERVICES — includes panel's own
# daemons and extras that should be visible but not necessarily controllable).
_MONITORED_SERVICES: list[str] = [
    "nginx",
    "postgresql",
    "redis-server",
    "hosthive-api",
    "hosthive-agent",
    "hosthive-worker",
    "exim4",
    "dovecot",
    "proftpd",
    "fail2ban",
    "docker",
    "mariadb",
    "php8.2-fpm",
    "php8.3-fpm",
    "named",
    "clamav-daemon",
]

_DISPLAY_NAMES: dict[str, str] = {
    "nginx": "Nginx",
    "postgresql": "PostgreSQL",
    "redis-server": "Redis",
    "hosthive-api": "NovaPanel API",
    "hosthive-agent": "NovaPanel Agent",
    "hosthive-worker": "NovaPanel Worker",
    "exim4": "Exim4 (Mail)",
    "dovecot": "Dovecot (IMAP)",
    "proftpd": "ProFTPD",
    "fail2ban": "Fail2ban",
    "docker": "Docker",
    "mariadb": "MariaDB",
    "php8.2-fpm": "PHP 8.2 FPM",
    "php8.3-fpm": "PHP 8.3 FPM",
    "named": "BIND DNS",
    "clamav-daemon": "ClamAV",
}

_LOG_PATHS: dict[str, str] = {
    "nginx": "/var/log/nginx/access.log",
    "nginx-error": "/var/log/nginx/error.log",
    "hosthive": "/opt/hosthive/logs/api.log",
    "postgresql": "/var/log/postgresql/postgresql-*-main.log",
    "mail": "/var/log/mail.log",
    "auth": "/var/log/auth.log",
    "syslog": "/var/log/syslog",
    "fail2ban": "/var/log/fail2ban.log",
    "exim4": "/var/log/exim4/mainlog",
    "dovecot": "/var/log/dovecot.log",
    "proftpd": "/var/log/proftpd/proftpd.log",
}

# Services allowed for start/stop/restart (security whitelist).
# We extend ALLOWED_SERVICES with our panel daemons.
_CONTROLLABLE_SERVICES: set[str] = set(ALLOWED_SERVICES) | {
    "hosthive-api",
    "hosthive-agent",
    "hosthive-worker",
    "docker",
    "mariadb",
    "php8.3-fpm",
    "clamav-daemon",
    "named",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a command via subprocess. Raises on timeout."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def _run_async(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a blocking subprocess call in the default executor so we don't block the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run(cmd, timeout))


def _validate_service_name(name: str) -> str:
    """Sanitise service name to prevent injection. Returns cleaned name or raises."""
    cleaned = re.sub(r"[^a-zA-Z0-9._@:-]", "", name)
    if not cleaned or cleaned != name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service name: {name}",
        )
    return cleaned


# ---------------------------------------------------------------------------
# Direct-command implementations (fallbacks)
# ---------------------------------------------------------------------------

async def _direct_get_service_status(name: str) -> dict:
    """Get status of a single service using systemctl directly."""
    try:
        result_active = await _run_async(["systemctl", "is-active", name], timeout=5)
        active = result_active.stdout.strip() == "active"

        result_enabled = await _run_async(["systemctl", "is-enabled", name], timeout=5)
        enabled = result_enabled.stdout.strip() == "enabled"

        return {
            "name": name,
            "display_name": _DISPLAY_NAMES.get(name, name.replace("-", " ").title()),
            "status": "running" if active else "stopped",
            "enabled": enabled,
        }
    except Exception:
        return {
            "name": name,
            "display_name": _DISPLAY_NAMES.get(name, name.replace("-", " ").title()),
            "status": "unknown",
            "enabled": False,
        }


async def _direct_list_services() -> list[dict]:
    """List all monitored services using systemctl directly."""
    tasks = [_direct_get_service_status(svc) for svc in _MONITORED_SERVICES]
    return await asyncio.gather(*tasks)


async def _direct_service_action(service_name: str, action: str) -> dict:
    """Start/stop/restart a service using sudo systemctl."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action: {action}",
        )
    if service_name not in _CONTROLLABLE_SERVICES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Service '{service_name}' is not in the allowed list.",
        )

    result = await _run_async(["sudo", "systemctl", action, service_name], timeout=30)
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"systemctl {action} {service_name} failed: {result.stderr.strip()}",
        )
    return {"ok": True, "service": service_name, "action": action}


async def _direct_server_stats() -> dict:
    """Gather server stats via psutil / os."""
    try:
        import psutil  # noqa: local import — only needed in fallback path
    except ImportError:
        return {"error": "psutil not installed", "_agent_down": True}

    loop = asyncio.get_running_loop()

    def _gather():
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        load = os.getloadavg()
        uptime = time.time() - psutil.boot_time()
        conns = len(psutil.net_connections(kind="inet"))

        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / (1024 * 1024)),
            "memory_total_mb": round(mem.total / (1024 * 1024)),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "load_avg_1": load[0],
            "load_avg_5": load[1],
            "load_avg_15": load[2],
            "network_rx_bytes": net.bytes_recv,
            "network_tx_bytes": net.bytes_sent,
            "active_connections": conns,
            "uptime_seconds": int(uptime),
        }

    return await loop.run_in_executor(None, _gather)


async def _direct_firewall_rules() -> dict:
    """Get firewall rules via ufw."""
    result = await _run_async(["sudo", "ufw", "status", "numbered"], timeout=10)
    if result.returncode != 0:
        return {"rules": [], "status": "unknown", "error": result.stderr.strip()}

    lines = result.stdout.strip().splitlines()
    rules: list[dict] = []
    fw_status = "inactive"

    for line in lines:
        if line.startswith("Status:"):
            fw_status = line.split(":", 1)[1].strip()
            continue

        # Lines look like: [ 1] 22/tcp    ALLOW IN    Anywhere
        match = re.match(
            r"\[\s*(\d+)\]\s+(.+?)\s+(ALLOW|DENY|REJECT)\s+(IN|OUT|FWD)?\s*(.*)",
            line,
        )
        if match:
            rule_num = match.group(1)
            port_proto = match.group(2).strip()
            action = match.group(3).lower()
            direction = (match.group(4) or "in").lower()
            source = match.group(5).strip() or "any"
            rules.append({
                "id": rule_num,
                "port": port_proto,
                "action": action,
                "direction": direction,
                "source": source,
            })

    return {"status": fw_status, "rules": rules}


async def _direct_firewall_add_rule(rule: dict) -> dict:
    """Add a firewall rule via ufw."""
    action = rule.get("action", "allow")
    protocol = rule.get("protocol", "tcp")
    port = rule.get("port")
    source = rule.get("source", "any")
    comment = rule.get("comment")

    cmd = ["sudo", "ufw"]

    if source and source != "any":
        cmd += [action, "from", source]
        if port:
            cmd += ["to", "any", "port", port, "proto", protocol]
    else:
        if port:
            cmd += [action, f"{port}/{protocol}"]
        else:
            cmd += [action, protocol]

    if comment:
        cmd += ["comment", comment]

    result = await _run_async(cmd, timeout=15)
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ufw error: {result.stderr.strip()}",
        )
    return {"ok": True, "message": result.stdout.strip()}


async def _direct_firewall_delete_rule(rule_id: str) -> None:
    """Delete a firewall rule via ufw by rule number."""
    # ufw delete requires --force to skip confirmation prompt
    result = await _run_async(
        ["sudo", "ufw", "--force", "delete", rule_id], timeout=15
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ufw delete error: {result.stderr.strip()}",
        )


async def _direct_fail2ban_status() -> dict:
    """Get fail2ban status via fail2ban-client."""
    result = await _run_async(["sudo", "fail2ban-client", "status"], timeout=10)
    if result.returncode != 0:
        return {"jails": [], "error": result.stderr.strip()}

    # Parse the jail list from output like:
    # `- Jail list:   sshd, nginx-http-auth`
    jails_line = ""
    for line in result.stdout.splitlines():
        if "Jail list:" in line:
            jails_line = line.split("Jail list:", 1)[1].strip().rstrip(",")
            break

    jail_names = [j.strip() for j in jails_line.split(",") if j.strip()] if jails_line else []

    jails: list[dict] = []
    for jail_name in jail_names:
        jail_info = await _direct_fail2ban_jail_detail(jail_name)
        jails.append(jail_info)

    return {"jails": jails}


async def _direct_fail2ban_jail_detail(jail_name: str) -> dict:
    """Get detail for a single fail2ban jail."""
    result = await _run_async(["sudo", "fail2ban-client", "status", jail_name], timeout=10)
    if result.returncode != 0:
        return {"name": jail_name, "enabled": True, "currently_failed": 0, "total_failed": 0, "currently_banned": 0, "total_banned": 0, "banned_ips": []}

    text = result.stdout
    currently_failed = 0
    total_failed = 0
    currently_banned = 0
    total_banned = 0
    banned_ips: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if "Currently failed:" in line:
            currently_failed = int(line.split(":", 1)[1].strip())
        elif "Total failed:" in line:
            total_failed = int(line.split(":", 1)[1].strip())
        elif "Currently banned:" in line:
            currently_banned = int(line.split(":", 1)[1].strip())
        elif "Total banned:" in line:
            total_banned = int(line.split(":", 1)[1].strip())
        elif "Banned IP list:" in line:
            ip_part = line.split(":", 1)[1].strip()
            if ip_part:
                banned_ips = [ip.strip() for ip in ip_part.split() if ip.strip()]

    return {
        "name": jail_name,
        "enabled": True,
        "currently_failed": currently_failed,
        "total_failed": total_failed,
        "currently_banned": currently_banned,
        "total_banned": total_banned,
        "banned_ips": banned_ips,
    }


async def _direct_fail2ban_unban(ip: str) -> dict:
    """Unban an IP from all jails via fail2ban-client."""
    result = await _run_async(["sudo", "fail2ban-client", "unban", ip], timeout=10)
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"fail2ban-client unban error: {result.stderr.strip()}",
        )
    return {"ok": True, "ip": ip, "message": result.stdout.strip()}


async def _direct_fail2ban_enable_jail(jail_name: str) -> dict:
    """Enable (start) a fail2ban jail."""
    result = await _run_async(
        ["sudo", "fail2ban-client", "start", jail_name], timeout=15
    )
    if result.returncode != 0:
        # It might already be running; try reload instead
        result2 = await _run_async(
            ["sudo", "fail2ban-client", "reload", jail_name], timeout=15
        )
        if result2.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"fail2ban enable error: {result.stderr.strip()} / {result2.stderr.strip()}",
            )
    return {"ok": True, "jail": jail_name, "action": "enabled"}


async def _direct_fail2ban_disable_jail(jail_name: str) -> dict:
    """Disable (stop) a fail2ban jail."""
    result = await _run_async(
        ["sudo", "fail2ban-client", "stop", jail_name], timeout=15
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"fail2ban disable error: {result.stderr.strip()}",
        )
    return {"ok": True, "jail": jail_name, "action": "disabled"}


async def _direct_read_logs(service: str, lines: int = 200) -> dict:
    """Read last N lines of a service log file directly."""
    pattern = _LOG_PATHS.get(service)
    if not pattern:
        # Try journalctl for unknown services
        return await _direct_read_journal(service, lines)

    # Resolve glob patterns (e.g. postgresql-*-main.log)
    matched_files = sorted(_glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not matched_files:
        # Fallback to journalctl if log file doesn't exist
        return await _direct_read_journal(service, lines)

    log_path = matched_files[0]

    try:
        result = await _run_async(["sudo", "tail", "-n", str(lines), log_path], timeout=10)
        if result.returncode != 0:
            # Try without sudo
            result = await _run_async(["tail", "-n", str(lines), log_path], timeout=10)

        if result.returncode != 0:
            return await _direct_read_journal(service, lines)

        log_lines = result.stdout.splitlines()
        return {"lines": log_lines, "service": service, "file": log_path}
    except Exception:
        return await _direct_read_journal(service, lines)


async def _direct_read_journal(service: str, lines: int = 200) -> dict:
    """Read last N log lines from journalctl for a given service unit."""
    result = await _run_async(
        ["journalctl", "-u", service, "-n", str(lines), "--no-pager", "-o", "short-iso"],
        timeout=10,
    )
    if result.returncode != 0:
        return {"lines": [], "service": service, "error": f"No logs found for {service}"}

    log_lines = result.stdout.splitlines()
    return {"lines": log_lines, "service": service, "source": "journalctl"}


# ---------------------------------------------------------------------------
# GET /stats -- current CPU/RAM/disk/net; agent first, then psutil
# ---------------------------------------------------------------------------
@router.get("/stats", status_code=status.HTTP_200_OK)
async def server_stats(
    request: Request,
    admin: User = Depends(_admin),
):
    _DEFAULTS = {
        "cpu_percent": 0.0,
        "memory_percent": 0.0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "disk_percent": 0.0,
        "disk_used_gb": 0.0,
        "disk_total_gb": 0.0,
        "load_avg_1": 0.0,
        "load_avg_5": 0.0,
        "load_avg_15": 0.0,
        "network_rx_bytes": 0,
        "network_tx_bytes": 0,
        "active_connections": 0,
    }

    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent.get_server_stats()
        if isinstance(result, dict):
            for key, default in _DEFAULTS.items():
                if result.get(key) is None:
                    result[key] = default
        return result
    except Exception:
        pass

    # --- Fallback: direct system commands via psutil ---
    try:
        result = await _direct_server_stats()
        if isinstance(result, dict) and "error" not in result:
            for key, default in _DEFAULTS.items():
                if result.get(key) is None:
                    result[key] = default
            return result
    except Exception:
        pass

    return {**_DEFAULTS, "_agent_down": True}


# --------------------------------------------------------------------------
# GET /stats/history -- last 24h from ServerStat table (no agent needed)
# --------------------------------------------------------------------------
@router.get("/stats/history", status_code=status.HTTP_200_OK)
async def stats_history(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = (await db.execute(
        select(ServerStat)
        .where(ServerStat.created_at >= since)
        .order_by(ServerStat.created_at.asc())
    )).scalars().all()

    return {
        "items": [
            {
                "id": str(s.id),
                "cpu_percent": s.cpu_percent,
                "memory_percent": s.memory_percent,
                "memory_used_mb": s.memory_used_mb,
                "disk_percent": s.disk_percent,
                "disk_used_gb": s.disk_used_gb,
                "load_avg_1": s.load_avg_1,
                "load_avg_5": s.load_avg_5,
                "load_avg_15": s.load_avg_15,
                "network_rx_bytes": s.network_rx_bytes,
                "network_tx_bytes": s.network_tx_bytes,
                "active_connections": s.active_connections,
                "created_at": s.created_at.isoformat(),
            }
            for s in results
        ],
        "total": len(results),
    }


# --------------------------------------------------------------------------
# GET /services -- all service statuses; agent first, then systemctl
# --------------------------------------------------------------------------
@router.get("/services", status_code=status.HTTP_200_OK)
async def list_services(
    request: Request,
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/system/services")
        if isinstance(result, dict) and "services" in result:
            services = result["services"]
        elif isinstance(result, list):
            services = result
        else:
            services = []
        for svc in services:
            if isinstance(svc, dict) and "display_name" not in svc:
                svc["display_name"] = _DISPLAY_NAMES.get(svc.get("name", ""), svc.get("name", ""))
        return services
    except Exception:
        pass

    # --- Fallback: direct systemctl ---
    try:
        services = await _direct_list_services()
        return list(services)
    except Exception:
        return [
            {"name": s, "display_name": _DISPLAY_NAMES.get(s, s), "status": "unknown", "enabled": False}
            for s in _MONITORED_SERVICES
        ]


# --------------------------------------------------------------------------
# POST /services/{name}/restart
# --------------------------------------------------------------------------
@router.post("/services/{service_name}/restart", status_code=status.HTTP_200_OK)
async def restart_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    service_name = _validate_service_name(service_name)

    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent.service_action(service_name, "restart")
        _log_activity(db, request, admin.id, "server.restart_service", f"Restarted service {service_name}")
        return result
    except Exception:
        pass

    # --- Fallback: direct systemctl ---
    result = await _direct_service_action(service_name, "restart")
    _log_activity(db, request, admin.id, "server.restart_service", f"Restarted service {service_name} (direct)")
    return result


# --------------------------------------------------------------------------
# POST /services/{name}/start
# --------------------------------------------------------------------------
@router.post("/services/{service_name}/start", status_code=status.HTTP_200_OK)
async def start_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    service_name = _validate_service_name(service_name)

    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/service/restart",
            json_body={"name": service_name, "action": "start"},
        )
        _log_activity(db, request, admin.id, "server.start_service", f"Started service {service_name}")
        return result
    except Exception:
        pass

    # --- Fallback: direct systemctl ---
    result = await _direct_service_action(service_name, "start")
    _log_activity(db, request, admin.id, "server.start_service", f"Started service {service_name} (direct)")
    return result


# --------------------------------------------------------------------------
# POST /services/{name}/stop
# --------------------------------------------------------------------------
@router.post("/services/{service_name}/stop", status_code=status.HTTP_200_OK)
async def stop_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    service_name = _validate_service_name(service_name)

    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/service/restart",
            json_body={"name": service_name, "action": "stop"},
        )
        _log_activity(db, request, admin.id, "server.stop_service", f"Stopped service {service_name}")
        return result
    except Exception:
        pass

    # --- Fallback: direct systemctl ---
    result = await _direct_service_action(service_name, "stop")
    _log_activity(db, request, admin.id, "server.stop_service", f"Stopped service {service_name} (direct)")
    return result


# --------------------------------------------------------------------------
# Firewall
# --------------------------------------------------------------------------

@router.get("/firewall", status_code=status.HTTP_200_OK)
async def firewall_rules(
    request: Request,
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/system/firewall")
        return result
    except Exception:
        pass

    # --- Fallback: direct ufw ---
    try:
        return await _direct_firewall_rules()
    except Exception:
        return {"rules": [], "_agent_down": True}


@router.post("/firewall", status_code=status.HTTP_201_CREATED)
async def add_firewall_rule(
    body: FirewallRule,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    rule_data = body.model_dump()

    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent.firewall_add_rule(rule_data)
        _log_activity(db, request, admin.id, "server.firewall_add", f"Added firewall rule: {rule_data}")
        return result
    except Exception:
        pass

    # --- Fallback: direct ufw ---
    result = await _direct_firewall_add_rule(rule_data)
    _log_activity(db, request, admin.id, "server.firewall_add", f"Added firewall rule (direct): {rule_data}")
    return result


@router.delete("/firewall/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_firewall_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        await agent.firewall_delete_rule(rule_id)
        _log_activity(db, request, admin.id, "server.firewall_delete", f"Deleted firewall rule {rule_id}")
        return
    except Exception:
        pass

    # --- Fallback: direct ufw ---
    await _direct_firewall_delete_rule(rule_id)
    _log_activity(db, request, admin.id, "server.firewall_delete", f"Deleted firewall rule {rule_id} (direct)")


# --------------------------------------------------------------------------
# Fail2ban
# --------------------------------------------------------------------------

@router.get("/fail2ban", status_code=status.HTTP_200_OK)
async def fail2ban_jails(
    request: Request,
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/system/fail2ban")
        return result
    except Exception:
        pass

    # --- Fallback: direct fail2ban-client ---
    try:
        return await _direct_fail2ban_status()
    except Exception:
        return {"jails": [], "_agent_down": True}


@router.post("/fail2ban/unban", status_code=status.HTTP_200_OK)
async def fail2ban_unban(
    ip: str = Query(..., max_length=45),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST",
            "/system/fail2ban/unban",
            json_body={"ip": ip},
        )
        _log_activity(db, request, admin.id, "server.fail2ban_unban", f"Unbanned IP {ip}")
        return result
    except Exception:
        pass

    # --- Fallback: direct fail2ban-client ---
    result = await _direct_fail2ban_unban(ip)
    _log_activity(db, request, admin.id, "server.fail2ban_unban", f"Unbanned IP {ip} (direct)")
    return result


# --------------------------------------------------------------------------
# POST /fail2ban/{jail}/enable
# --------------------------------------------------------------------------
@router.post("/fail2ban/{jail_name}/enable", status_code=status.HTTP_200_OK)
async def fail2ban_enable_jail(
    jail_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/fail2ban/enable",
            json_body={"jail": jail_name},
        )
        _log_activity(db, request, admin.id, "server.fail2ban_enable", f"Enabled jail {jail_name}")
        return result
    except Exception:
        pass

    # --- Fallback: direct fail2ban-client ---
    result = await _direct_fail2ban_enable_jail(jail_name)
    _log_activity(db, request, admin.id, "server.fail2ban_enable", f"Enabled jail {jail_name} (direct)")
    return result


# --------------------------------------------------------------------------
# POST /fail2ban/{jail}/disable
# --------------------------------------------------------------------------
@router.post("/fail2ban/{jail_name}/disable", status_code=status.HTTP_200_OK)
async def fail2ban_disable_jail(
    jail_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/fail2ban/disable",
            json_body={"jail": jail_name},
        )
        _log_activity(db, request, admin.id, "server.fail2ban_disable", f"Disabled jail {jail_name}")
        return result
    except Exception:
        pass

    # --- Fallback: direct fail2ban-client ---
    result = await _direct_fail2ban_disable_jail(jail_name)
    _log_activity(db, request, admin.id, "server.fail2ban_disable", f"Disabled jail {jail_name} (direct)")
    return result


# --------------------------------------------------------------------------
# GET /logs/{service} -- last N lines; agent first, then direct file read
# --------------------------------------------------------------------------
@router.get("/logs/{service}", status_code=status.HTTP_200_OK)
async def service_logs(
    service: str,
    lines: int = Query(200, ge=1, le=1000),
    request: Request = None,
    admin: User = Depends(_admin),
):
    # --- Try agent first ---
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "GET",
            f"/system/logs/{service}",
            params={"lines": lines},
        )
        return result
    except Exception:
        pass

    # --- Fallback: direct log reading ---
    try:
        return await _direct_read_logs(service, lines)
    except Exception:
        return {"lines": [], "service": service, "_agent_down": True}


# --------------------------------------------------------------------------
# GET /logs -- query param variant for frontend compatibility
# --------------------------------------------------------------------------
@router.get("/logs", status_code=status.HTTP_200_OK)
async def get_service_logs_query(
    service: str = Query(...),
    lines: int = Query(200, ge=1, le=1000),
    request: Request = None,
    admin: User = Depends(_admin),
):
    return await service_logs(service=service, lines=lines, request=request, admin=admin)


# --------------------------------------------------------------------------
# WebSocket /ws/terminal -- admin terminal (bidirectional)
# --------------------------------------------------------------------------
@router.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    # Authenticate via query param token
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = verify_token(token, expected_type="access")
        if payload.get("role") != "admin":
            await websocket.close(code=4003, reason="Admin required")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    agent = websocket.app.state.agent

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                command = msg.get("command", "")
                if not command:
                    await websocket.send_json({"error": "Empty command"})
                    continue

                # --- Try agent first ---
                try:
                    result = await agent._request(
                        "POST",
                        "/terminal/exec",
                        json_body={"command": command},
                    )
                    await websocket.send_json(result)
                    continue
                except Exception:
                    pass

                # --- Fallback: direct subprocess ---
                try:
                    proc_result = await _run_async(
                        ["bash", "-c", command], timeout=30
                    )
                    await websocket.send_json({
                        "stdout": proc_result.stdout,
                        "stderr": proc_result.stderr,
                        "exit_code": proc_result.returncode,
                    })
                except subprocess.TimeoutExpired:
                    await websocket.send_json({"error": "Command timed out (30s)"})
                except Exception as exc:
                    await websocket.send_json({"error": str(exc)})

            except Exception as exc:
                await websocket.send_json({"error": str(exc)})
    except WebSocketDisconnect:
        pass


# --------------------------------------------------------------------------
# WebSocket /ws/logs/{service} -- live log streaming
# --------------------------------------------------------------------------
@router.websocket("/ws/logs/{service}")
async def ws_log_stream(websocket: WebSocket, service: str):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = verify_token(token, expected_type="access")
        if payload.get("role") != "admin":
            await websocket.close(code=4003, reason="Admin required")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    agent = websocket.app.state.agent

    try:
        while True:
            # --- Try agent first ---
            try:
                result = await agent._request(
                    "GET",
                    f"/system/logs/{service}/tail",
                    params={"lines": 20},
                )
                await websocket.send_json(result)
                await asyncio.sleep(2)
                continue
            except Exception:
                pass

            # --- Fallback: direct tail ---
            try:
                result = await _direct_read_logs(service, 20)
                await websocket.send_json(result)
            except Exception as exc:
                await websocket.send_json({"error": str(exc)})

            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
