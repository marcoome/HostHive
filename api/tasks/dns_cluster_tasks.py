"""Celery tasks for DNS cluster synchronisation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.dns_cluster")


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.task(
    name="api.tasks.dns_cluster_tasks.verify_cluster_sync",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def verify_cluster_sync(self) -> dict:
    """Periodic task: push all active zones to every active slave node.

    This ensures that any missed NOTIFY / AXFR transfers are caught up.
    Runs every 15 minutes by default (configured in celeryconfig.py).
    """
    from api.core.config import settings
    from api.core.encryption import decrypt_value
    from api.models.dns_cluster import DnsClusterNode
    from api.models.dns_records import DnsRecord
    from api.models.dns_zones import DnsZone
    from api.services.bind_service import generate_zone_file, push_zone_to_node

    logger.info("Starting DNS cluster sync verification")

    with get_sync_session() as session:
        # Fetch active slave nodes
        nodes = session.execute(
            select(DnsClusterNode).where(
                DnsClusterNode.is_active.is_(True),
                DnsClusterNode.role == "slave",
            )
        ).scalars().all()

        if not nodes:
            logger.info("No active slave nodes -- nothing to sync")
            return {"status": "skipped", "reason": "no_slaves"}

        # Fetch all active zones
        zones = session.execute(
            select(DnsZone).where(DnsZone.is_active.is_(True))
        ).scalars().all()

        if not zones:
            logger.info("No active zones -- nothing to sync")
            return {"status": "skipped", "reason": "no_zones"}

        succeeded = 0
        failed = 0

        for zone in zones:
            records = session.execute(
                select(DnsRecord).where(DnsRecord.zone_id == zone.id)
            ).scalars().all()

            content = generate_zone_file(zone.zone_name, records)

            for node in nodes:
                try:
                    plain_key = decrypt_value(node.api_key, settings.SECRET_KEY)
                except Exception:
                    plain_key = node.api_key

                ok, msg = _run_async(
                    push_zone_to_node(node.api_url, plain_key, zone.zone_name, content)
                )

                if ok:
                    node.last_sync_at = datetime.now(timezone.utc)
                    succeeded += 1
                else:
                    logger.warning(
                        "Cluster sync failed: zone=%s node=%s msg=%s",
                        zone.zone_name, node.hostname, msg,
                    )
                    failed += 1

        session.commit()

    logger.info("DNS cluster sync complete: %d succeeded, %d failed", succeeded, failed)
    return {"status": "synced", "succeeded": succeeded, "failed": failed}
