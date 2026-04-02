"""Prometheus metrics router -- /metrics (Bearer token auth)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.models.backups import Backup
from api.models.domains import Domain
from api.models.users import User

logger = logging.getLogger("novapanel.metrics")

router = APIRouter()

_bearer_scheme = HTTPBearer(auto_error=False)

# The metrics token can be set via METRICS_TOKEN env var or defaults to the
# first 32 chars of SECRET_KEY (so it works out-of-the-box).
_METRICS_TOKEN: str | None = getattr(settings, "METRICS_TOKEN", None) or settings.SECRET_KEY[:32]

_BOOT_TIME = time.monotonic()


# ---------------------------------------------------------------------------
# Auth dependency -- Bearer token (configurable, not JWT)
# ---------------------------------------------------------------------------

async def _verify_metrics_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    if credentials is None or credentials.credentials != _METRICS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing metrics token.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prom_line(name: str, value: float | int, help_text: str = "", ptype: str = "gauge") -> str:
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {ptype}")
    lines.append(f"{name} {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GET / -- Prometheus text format metrics
# ---------------------------------------------------------------------------
@router.get("/", response_class=PlainTextResponse, status_code=status.HTTP_200_OK)
async def prometheus_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: None = Depends(_verify_metrics_token),
):
    sections: list[str] = []

    # System metrics from agent (best effort)
    cpu_pct = 0.0
    ram_pct = 0.0
    disk_pct = 0.0
    net_in = 0
    net_out = 0
    try:
        agent = request.app.state.agent
        stats = await agent.get_server_stats()
        cpu_pct = stats.get("cpu_percent", 0.0)
        ram_pct = stats.get("ram_percent", 0.0)
        disk_pct = stats.get("disk_percent", 0.0)
        net_in = stats.get("network_in_bytes", 0)
        net_out = stats.get("network_out_bytes", 0)
    except Exception:
        logger.debug("Could not fetch server stats from agent for metrics")

    sections.append(_prom_line("hosthive_cpu_percent", cpu_pct, "CPU usage percentage"))
    sections.append(_prom_line("hosthive_ram_percent", ram_pct, "RAM usage percentage"))
    sections.append(_prom_line("hosthive_disk_percent", disk_pct, "Disk usage percentage"))
    sections.append(_prom_line("hosthive_network_in_bytes", net_in, "Network bytes received", "counter"))
    sections.append(_prom_line("hosthive_network_out_bytes", net_out, "Network bytes sent", "counter"))

    # Domain count
    domain_count = (await db.execute(
        select(func.count()).select_from(Domain)
    )).scalar() or 0
    sections.append(_prom_line("hosthive_domains_total", domain_count, "Total number of domains"))

    # Active users
    active_users = (await db.execute(
        select(func.count()).select_from(User).where(User.is_active.is_(True), User.is_suspended.is_(False))
    )).scalar() or 0
    sections.append(_prom_line("hosthive_users_active", active_users, "Number of active users"))

    # Last successful backup timestamp
    last_backup = (await db.execute(
        select(Backup.created_at)
        .where(Backup.status == "completed")
        .order_by(Backup.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    backup_ts = int(last_backup.timestamp()) if last_backup else 0
    sections.append(_prom_line(
        "hosthive_backup_last_success_timestamp",
        backup_ts,
        "Unix timestamp of last successful backup",
    ))

    # Uptime
    uptime_seconds = time.monotonic() - _BOOT_TIME
    sections.append(_prom_line("hosthive_uptime_seconds", round(uptime_seconds, 1), "API uptime in seconds", "counter"))

    return "\n\n".join(sections) + "\n"
