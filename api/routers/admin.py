"""Admin router -- /api/v1/admin (admin only)."""

from __future__ import annotations

import logging
import os
import platform
import secrets
import sys
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

logger = logging.getLogger("hosthive.admin")

router = APIRouter()

_admin = require_role("admin")

_BOOT_TIME = time.time()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=client_ip,
    ))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RotateSecretsResponse(BaseModel):
    detail: str
    new_jwt_secret_preview: str  # first 8 chars only


class SystemInfoResponse(BaseModel):
    os_version: str
    python_version: str
    hosthive_version: str
    uptime_seconds: float
    installed_services: list[str]


class MaintenanceModeRequest(BaseModel):
    enabled: bool


class MaintenanceModeResponse(BaseModel):
    maintenance_mode: bool
    detail: str


# ---------------------------------------------------------------------------
# POST /rotate-secrets -- generate new JWT + agent secrets
# ---------------------------------------------------------------------------
@router.post("/rotate-secrets", response_model=RotateSecretsResponse, status_code=status.HTTP_200_OK)
async def rotate_secrets(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    new_jwt_secret = secrets.token_urlsafe(48)
    new_agent_secret = secrets.token_urlsafe(48)

    # Write new secrets to the secrets file
    secrets_path = "/opt/hosthive/config/secrets.env"
    try:
        # Read existing file content
        existing_lines: list[str] = []
        if os.path.exists(secrets_path):
            with open(secrets_path, "r") as f:
                existing_lines = f.readlines()

        # Replace SECRET_KEY and AGENT_SECRET lines
        new_lines: list[str] = []
        found_secret = False
        found_agent = False
        for line in existing_lines:
            stripped = line.strip()
            if stripped.startswith("SECRET_KEY="):
                new_lines.append(f"SECRET_KEY={new_jwt_secret}\n")
                found_secret = True
            elif stripped.startswith("AGENT_SECRET="):
                new_lines.append(f"AGENT_SECRET={new_agent_secret}\n")
                found_agent = True
            else:
                new_lines.append(line)

        if not found_secret:
            new_lines.append(f"SECRET_KEY={new_jwt_secret}\n")
        if not found_agent:
            new_lines.append(f"AGENT_SECRET={new_agent_secret}\n")

        with open(secrets_path, "w") as f:
            f.writelines(new_lines)

    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Insufficient permissions to write secrets file.",
        )
    except Exception as exc:
        logger.error("Failed to rotate secrets: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write new secrets.",
        )

    # Invalidate all sessions by flushing refresh tokens from Redis
    try:
        redis = request.app.state.redis
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match="hosthive:refresh:*", count=500)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Failed to flush Redis sessions: %s", exc)

    # Request service restart via agent
    try:
        agent = request.app.state.agent
        await agent.service_action("hosthive-api", "restart")
    except Exception as exc:
        logger.warning("Failed to restart API service: %s", exc)

    _log(db, request, admin.id, "admin.rotate_secrets", "Rotated JWT and agent secrets, invalidated all sessions")

    return RotateSecretsResponse(
        detail="Secrets rotated. All sessions invalidated. Service restart requested.",
        new_jwt_secret_preview=new_jwt_secret[:8] + "...",
    )


# ---------------------------------------------------------------------------
# GET /system-info
# ---------------------------------------------------------------------------
@router.get("/system-info", response_model=SystemInfoResponse, status_code=status.HTTP_200_OK)
async def system_info(
    request: Request,
    admin: User = Depends(_admin),
):
    uptime = time.time() - _BOOT_TIME

    # Detect installed services by probing the agent
    installed: list[str] = []
    service_names = [
        "nginx", "mariadb", "postgresql", "postfix", "dovecot",
        "proftpd", "named", "pdns", "redis", "fail2ban",
        "wireguard", "certbot",
    ]
    try:
        agent = request.app.state.agent
        for svc in service_names:
            try:
                result = await agent.service_action(svc, "status")
                if result.get("active"):
                    installed.append(svc)
            except Exception:
                pass
    except Exception:
        pass

    return SystemInfoResponse(
        os_version=platform.platform(),
        python_version=sys.version,
        hosthive_version="0.1.0",
        uptime_seconds=round(uptime, 1),
        installed_services=installed,
    )


# ---------------------------------------------------------------------------
# POST /maintenance-mode -- toggle maintenance mode
# ---------------------------------------------------------------------------
@router.post("/maintenance-mode", response_model=MaintenanceModeResponse, status_code=status.HTTP_200_OK)
async def toggle_maintenance_mode(
    body: MaintenanceModeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    redis = request.app.state.redis

    if body.enabled:
        await redis.set("hosthive:maintenance_mode", "1")
        detail = "Maintenance mode enabled. Non-admin requests will be blocked."
    else:
        await redis.delete("hosthive:maintenance_mode")
        detail = "Maintenance mode disabled."

    _log(
        db, request, admin.id,
        "admin.maintenance_mode",
        f"Maintenance mode {'enabled' if body.enabled else 'disabled'}",
    )

    return MaintenanceModeResponse(
        maintenance_mode=body.enabled,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# GET /dashboard -- real-time dashboard stats
# ---------------------------------------------------------------------------
@router.get("/dashboard", status_code=status.HTTP_200_OK)
async def dashboard_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Real dashboard stats from database + agent (if available)."""
    from api.models.domains import Domain
    from api.models.databases import Database
    from api.models.email_accounts import EmailAccount
    from api.models.ftp_accounts import FtpAccount

    # Counts from database
    domain_count = (await db.execute(select(func.count()).select_from(Domain))).scalar() or 0
    db_count = (await db.execute(select(func.count()).select_from(Database))).scalar() or 0
    email_count = (await db.execute(select(func.count()).select_from(EmailAccount))).scalar() or 0
    ftp_count = (await db.execute(select(func.count()).select_from(FtpAccount))).scalar() or 0
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0

    # Server stats from agent (graceful fallback)
    server = {}
    try:
        agent = request.app.state.agent
        server = await agent.get_server_stats()
    except Exception:
        pass

    # Parse agent stats into frontend-friendly format
    cpu_percent = server.get("cpu_percent", 0) or 0
    mem = server.get("memory", {}) or {}
    disk = server.get("disk", {}) or {}
    load = server.get("load_average", {}) or {}
    net = server.get("network", {}) or {}

    # Sum network across interfaces
    total_rx = sum(iface.get("rx_bytes", 0) for iface in net.values()) if isinstance(net, dict) else 0
    total_tx = sum(iface.get("tx_bytes", 0) for iface in net.values()) if isinstance(net, dict) else 0

    mem_total = mem.get("total_kb", 0) * 1024
    mem_used = mem.get("used_kb", 0) * 1024
    mem_percent = mem.get("percent", 0)

    disk_total = disk.get("total_bytes", 0)
    disk_used = disk.get("used_bytes", 0)
    disk_percent_str = disk.get("percent", "0%")
    disk_percent = int(disk_percent_str.replace("%", "")) if isinstance(disk_percent_str, str) else 0

    return {
        "cpu_usage": cpu_percent,
        "cpu_cores": os.cpu_count() or 1,
        "ram_used": mem_used,
        "ram_total": mem_total,
        "ram_usage": mem_percent,
        "disk_used": disk_used,
        "disk_total": disk_total,
        "disk_usage": disk_percent,
        "net_in": total_rx,
        "net_out": total_tx,
        "load_average": load,
        "uptime_seconds": server.get("uptime_seconds", 0),
        "domains_count": domain_count,
        "databases_count": db_count,
        "email_count": email_count,
        "ftp_count": ftp_count,
        "user_count": user_count,
    }
