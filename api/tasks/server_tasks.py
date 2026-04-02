"""HostHive server monitoring tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.server")


@app.task(
    name="api.tasks.server_tasks.collect_server_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=300,
)
def collect_server_stats(self) -> dict:
    """Poll the HostHive agent for current server metrics and persist them."""
    from api.models.server_stats import ServerStat

    logger.info("Collecting server statistics from agent")

    try:
        response = httpx.get(
            f"{settings.AGENT_URL}/api/v1/server/stats",
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.error("Failed to collect server stats: %s", exc)
        raise self.retry(exc=exc)

    with get_sync_session() as session:
        stat = ServerStat(
            cpu_percent=data.get("cpu_percent", 0.0),
            memory_percent=data.get("memory_percent", 0.0),
            memory_used_mb=data.get("memory_used_mb", 0),
            memory_total_mb=data.get("memory_total_mb", 0),
            disk_percent=data.get("disk_percent", 0.0),
            disk_used_gb=data.get("disk_used_gb", 0.0),
            disk_total_gb=data.get("disk_total_gb", 0.0),
            load_avg_1=data.get("load_avg_1", 0.0),
            load_avg_5=data.get("load_avg_5", 0.0),
            load_avg_15=data.get("load_avg_15", 0.0),
            network_rx_bytes=data.get("network_rx_bytes", 0),
            network_tx_bytes=data.get("network_tx_bytes", 0),
            active_connections=data.get("active_connections", 0),
        )
        session.add(stat)
        session.commit()

    logger.info(
        "Server stats recorded: CPU=%.1f%%, MEM=%.1f%%, DISK=%.1f%%",
        stat.cpu_percent, stat.memory_percent, stat.disk_percent,
    )
    return {
        "cpu_percent": stat.cpu_percent,
        "memory_percent": stat.memory_percent,
        "disk_percent": stat.disk_percent,
    }


@app.task(
    name="api.tasks.server_tasks.cleanup_old_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
)
def cleanup_old_stats(self) -> dict:
    """Delete server statistics older than 30 days to keep the database lean."""
    from api.models.server_stats import ServerStat

    logger.info("Cleaning up server stats older than 30 days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    with get_sync_session() as session:
        result = session.execute(
            delete(ServerStat).where(ServerStat.created_at < cutoff)
        )
        deleted = result.rowcount
        session.commit()

    logger.info("Deleted %d old server stat records (cutoff: %s)", deleted, cutoff)
    return {"deleted_count": deleted, "cutoff": cutoff.isoformat()}
