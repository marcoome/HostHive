"""Dashboard router -- /api/v1/dashboard (all authenticated users).

Server stats are gathered directly from psutil / os in the API process.
This module never proxies to the HostHive agent on port 7080 and must not
import or reference ``request.app.state.agent``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.users import User, UserRole

logger = logging.getLogger("hosthive.dashboard")

router = APIRouter()

_BOOT_TIME = time.time()


async def _direct_server_stats() -> dict:
    """Collect server stats via psutil/os in a worker thread.

    Returns a dict shaped like the historical agent ``get_server_stats``
    payload so the rest of the dashboard handler can stay unchanged.
    """
    try:
        import psutil  # local import — psutil is the canonical source
    except ImportError:
        return {}

    loop = asyncio.get_running_loop()

    def _gather() -> dict:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        try:
            la1, la5, la15 = os.getloadavg()
        except (OSError, AttributeError):
            la1 = la5 = la15 = 0.0
        uptime = time.time() - psutil.boot_time()

        # Build the same shape the old AgentClient.get_server_stats() returned.
        net_counters = {}
        try:
            for iface, counters in psutil.net_io_counters(pernic=True).items():
                net_counters[iface] = {
                    "rx_bytes": counters.bytes_recv,
                    "tx_bytes": counters.bytes_sent,
                }
        except Exception:
            pass

        return {
            "cpu_percent": cpu,
            "memory": {
                "total_kb": mem.total // 1024,
                "used_kb": mem.used // 1024,
                "percent": mem.percent,
            },
            "disk": {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "percent": f"{int(disk.percent)}%",
            },
            "load_average": {"1m": la1, "5m": la5, "15m": la15},
            "network": net_counters,
            "uptime_seconds": int(uptime),
        }

    try:
        return await loop.run_in_executor(None, _gather)
    except Exception as exc:
        logger.warning("psutil server stats collection failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# GET / -- dashboard stats for any authenticated user
# ---------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dashboard stats. Admins see full server stats; regular users see their own resources."""
    from api.models.domains import Domain
    from api.models.databases import Database
    from api.models.email_accounts import EmailAccount
    from api.models.ftp_accounts import FtpAccount
    from api.models.server_stats import ServerStat

    is_admin = current_user.role == UserRole.ADMIN

    # --- Resource counts (scoped by user for non-admins) ---
    if is_admin:
        domain_count = (await db.execute(select(func.count()).select_from(Domain))).scalar() or 0
        db_count = (await db.execute(select(func.count()).select_from(Database))).scalar() or 0
        email_count = (await db.execute(select(func.count()).select_from(EmailAccount))).scalar() or 0
        ftp_count = (await db.execute(select(func.count()).select_from(FtpAccount))).scalar() or 0
        user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    else:
        uid = current_user.id
        domain_count = (await db.execute(
            select(func.count()).select_from(Domain).where(Domain.user_id == uid)
        )).scalar() or 0
        db_count = (await db.execute(
            select(func.count()).select_from(Database).where(Database.user_id == uid)
        )).scalar() or 0
        email_count = (await db.execute(
            select(func.count()).select_from(EmailAccount).where(EmailAccount.user_id == uid)
        )).scalar() or 0
        ftp_count = (await db.execute(
            select(func.count()).select_from(FtpAccount).where(FtpAccount.user_id == uid)
        )).scalar() or 0
        user_count = 0  # non-admins don't need this

    # --- Server stats via direct psutil (admins get real data, users get zeros) ---
    server = {}
    if is_admin:
        try:
            server = await _direct_server_stats()
        except Exception as exc:
            logger.warning("Direct server stats collection failed: %s", exc)
            server = {}

    cpu_percent = server.get("cpu_percent", 0) or 0
    mem = server.get("memory", {}) or {}
    disk = server.get("disk", {}) or {}
    load = server.get("load_average", {}) or {}
    net = server.get("network", {}) or {}

    total_rx = sum(iface.get("rx_bytes", 0) for iface in net.values()) if isinstance(net, dict) else 0
    total_tx = sum(iface.get("tx_bytes", 0) for iface in net.values()) if isinstance(net, dict) else 0

    mem_total = mem.get("total_kb", 0) * 1024
    mem_used = mem.get("used_kb", 0) * 1024
    mem_percent = mem.get("percent", 0)

    disk_total = disk.get("total_bytes", 0)
    disk_used = disk.get("used_bytes", 0)
    disk_percent_str = disk.get("percent", "0%")
    disk_percent = int(disk_percent_str.replace("%", "")) if isinstance(disk_percent_str, str) else 0

    # --- Historical stats (admins only) ---
    cpu_history = []
    ram_history = []
    timestamps = []
    if is_admin:
        since = datetime.now() - timedelta(hours=24)
        historical = (await db.execute(
            select(ServerStat)
            .where(ServerStat.created_at >= since)
            .order_by(ServerStat.created_at.asc())
        )).scalars().all()

        cpu_history = [s.cpu_percent for s in historical]
        ram_history = [s.memory_percent for s in historical]
        timestamps = [s.created_at.isoformat() for s in historical]

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
        "cpu_history": cpu_history,
        "ram_history": ram_history,
        "history_timestamps": timestamps,
    }
