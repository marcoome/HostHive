"""Celery tasks for integration-related background work."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List

import httpx
from sqlalchemy import select

from api.core.config import settings
from api.core.encryption import decrypt_value
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.integrations")


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _load_integration(session, name: str):
    """Load an enabled integration by name, returning (model, decrypted_config) or (None, None)."""
    from api.models.integrations import Integration, IntegrationName

    row = session.execute(
        select(Integration).where(
            Integration.name == IntegrationName(name),
            Integration.is_enabled.is_(True),
        )
    ).scalar_one_or_none()

    if row is None or not row.config_json:
        return None, None

    config = json.loads(decrypt_value(row.config_json, settings.SECRET_KEY))
    return row, config


# ---------------------------------------------------------------------------
# S3 backup upload
# ---------------------------------------------------------------------------


@app.task(
    name="api.tasks.integration_tasks.upload_backup_to_s3",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    autoretry_for=(httpx.HTTPError, ConnectionError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
)
def upload_backup_to_s3(self, backup_id: str, delete_local: bool = False) -> dict:
    """After a local backup completes, upload it to S3-compatible storage.

    Args:
        backup_id: UUID of the Backup record.
        delete_local: If True, remove the local file after successful upload.
    """
    from api.models.backups import Backup
    from api.services.s3_service import S3BackupService

    logger.info("Uploading backup %s to S3", backup_id)

    with get_sync_session() as session:
        integration, s3_config = _load_integration(session, "s3")
        if integration is None:
            logger.info("S3 integration is disabled — skipping upload")
            return {"status": "skipped", "reason": "s3_disabled"}

        backup = session.execute(
            select(Backup).where(Backup.id == backup_id)
        ).scalar_one_or_none()

        if backup is None or not backup.file_path:
            logger.warning("Backup %s not found or has no file_path", backup_id)
            return {"status": "skipped", "reason": "no_file"}

        svc = S3BackupService(integration.config_json)
        remote_key = f"backups/{backup_id}/{backup.file_path.rsplit('/', 1)[-1]}"

        try:
            result = _run_async(svc.upload_backup(backup.file_path, remote_key))
        except Exception as exc:
            logger.error("S3 upload failed for backup %s: %s", backup_id, exc)
            raise self.retry(exc=exc)

        if delete_local:
            import os
            try:
                os.unlink(backup.file_path)
                logger.info("Deleted local backup file %s", backup.file_path)
            except OSError as exc:
                logger.warning("Failed to delete local file %s: %s", backup.file_path, exc)

    logger.info("Backup %s uploaded to S3 key %s", backup_id, remote_key)
    return {"status": "uploaded", "remote_key": remote_key, **result}


# ---------------------------------------------------------------------------
# Cloudflare DNS sync
# ---------------------------------------------------------------------------


@app.task(
    name="api.tasks.integration_tasks.sync_cloudflare_dns",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
)
def sync_cloudflare_dns(self, domain_id: str) -> dict:
    """Synchronise local DNS records for a domain to Cloudflare."""
    from api.models.dns_records import DnsRecord
    from api.models.dns_zones import DnsZone
    from api.services.cloudflare_service import CloudflareService

    logger.info("Syncing DNS for domain %s to Cloudflare", domain_id)

    with get_sync_session() as session:
        integration, _ = _load_integration(session, "cloudflare")
        if integration is None:
            logger.info("Cloudflare integration is disabled — skipping sync")
            return {"status": "skipped", "reason": "cloudflare_disabled"}

        zone = session.execute(
            select(DnsZone).where(DnsZone.id == domain_id)
        ).scalar_one_or_none()

        if zone is None:
            logger.warning("DNS zone %s not found", domain_id)
            return {"status": "skipped", "reason": "zone_not_found"}

        records = session.execute(
            select(DnsRecord).where(DnsRecord.zone_id == zone.id)
        ).scalars().all()

        record_dicts = [
            {
                "type": r.record_type,
                "name": r.name,
                "content": r.content,
                "ttl": getattr(r, "ttl", 1),
            }
            for r in records
        ]

        svc = CloudflareService(integration.config_json)
        try:
            result = _run_async(svc.sync_dns_zone(zone.name, record_dicts))
        except Exception as exc:
            logger.error("Cloudflare sync failed for zone %s: %s", zone.name, exc)
            raise self.retry(exc=exc)

    logger.info("Cloudflare sync complete for zone %s", domain_id)
    return {"status": "synced", **result}


# ---------------------------------------------------------------------------
# Service health check + alert
# ---------------------------------------------------------------------------


@app.task(
    name="api.tasks.integration_tasks.check_services_and_alert",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def check_services_and_alert(self) -> dict:
    """Check critical services and dispatch alerts if any are down.

    Intended to be called every 1 minute via Celery Beat.
    """
    from api.models.integrations import Integration
    from api.services.notification_service import ALERT_SERVICE_DOWN, NotificationDispatcher

    services_to_check = [
        ("nginx", ["systemctl", "is-active", "nginx"]),
        ("mysql", ["systemctl", "is-active", "mysql"]),
        ("redis", ["systemctl", "is-active", "redis"]),
        ("postfix", ["systemctl", "is-active", "postfix"]),
    ]

    import subprocess

    down_services: List[str] = []
    for name, cmd in services_to_check:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.stdout.strip() != "active":
                down_services.append(name)
        except Exception:
            down_services.append(name)

    if not down_services:
        return {"status": "all_ok"}

    message = f"Services DOWN: {', '.join(down_services)}"
    logger.warning(message)

    # Load notification integrations
    with get_sync_session() as session:
        rows = session.execute(select(Integration)).scalars().all()
        integrations = [
            {
                "name": row.name.value if hasattr(row.name, "value") else row.name,
                "is_enabled": row.is_enabled,
                "config_json": row.config_json,
            }
            for row in rows
        ]

    _run_async(
        NotificationDispatcher.dispatch_alert(
            alert_type=ALERT_SERVICE_DOWN,
            message=message,
            severity="critical",
            integrations=integrations,
        )
    )

    return {"status": "alerted", "down": down_services}


# ---------------------------------------------------------------------------
# S3 backup cleanup
# ---------------------------------------------------------------------------


@app.task(
    name="api.tasks.integration_tasks.cleanup_s3_backups",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
)
def cleanup_s3_backups(self, keep: int = 30) -> dict:
    """Remove old backups from S3, keeping the most recent *keep* objects.

    Intended to run weekly via Celery Beat.
    """
    from api.services.s3_service import S3BackupService

    logger.info("Starting S3 backup cleanup (keep=%d)", keep)

    with get_sync_session() as session:
        integration, _ = _load_integration(session, "s3")
        if integration is None:
            logger.info("S3 integration is disabled — skipping cleanup")
            return {"status": "skipped", "reason": "s3_disabled"}

        svc = S3BackupService(integration.config_json)
        deleted = _run_async(svc.cleanup_old_backups(keep=keep))

    logger.info("S3 cleanup complete: deleted %d old backups", deleted)
    return {"status": "cleaned", "deleted": deleted}
