"""HostHive backup tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.backup")


@app.task(
    name="api.tasks.backup_tasks.create_user_backup",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
)
def create_user_backup(self, user_id: str, backup_type: str = "full") -> dict:
    """Create a backup for a single user via the HostHive agent.

    Args:
        user_id: UUID of the user whose data to back up.
        backup_type: One of full, incremental, files_only, db_only.

    Returns:
        Dict with backup_id, status, and file_path.
    """
    from api.models.backups import Backup, BackupStatus, BackupType

    logger.info("Starting %s backup for user %s", backup_type, user_id)

    with get_sync_session() as session:
        # Create a pending backup record
        backup = Backup(
            user_id=user_id,
            backup_type=BackupType(backup_type),
            status=BackupStatus.IN_PROGRESS,
        )
        session.add(backup)
        session.commit()
        backup_id = str(backup.id)

        try:
            # Call the HostHive agent to perform the actual backup
            response = httpx.post(
                f"{settings.AGENT_URL}/api/v1/backups/create",
                json={
                    "user_id": user_id,
                    "backup_type": backup_type,
                    "backup_id": backup_id,
                },
                headers={"X-Agent-Secret": settings.AGENT_SECRET},
                timeout=600.0,
            )
            response.raise_for_status()
            result = response.json()

            # Update backup record with result
            backup.status = BackupStatus.COMPLETED
            backup.file_path = result.get("file_path")
            backup.size_bytes = result.get("size_bytes")
            session.commit()

            logger.info(
                "Backup %s completed for user %s (%s bytes)",
                backup_id, user_id, backup.size_bytes,
            )
            return {
                "backup_id": backup_id,
                "status": "completed",
                "file_path": backup.file_path,
            }

        except Exception as exc:
            backup.status = BackupStatus.FAILED
            backup.error_message = str(exc)[:1024]
            session.commit()
            logger.error(
                "Backup %s failed for user %s: %s",
                backup_id, user_id, exc,
            )
            raise self.retry(exc=exc)


@app.task(
    name="api.tasks.backup_tasks.cleanup_old_backups",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
)
def cleanup_old_backups(self) -> dict:
    """Delete backup records and files older than 7 days."""
    from api.models.backups import Backup

    logger.info("Starting cleanup of old backups")
    cutoff = datetime.utcnow() - timedelta(days=7)

    with get_sync_session() as session:
        # Fetch old completed backups to delete their files via agent
        old_backups = session.execute(
            select(Backup).where(Backup.created_at < cutoff)
        ).scalars().all()

        deleted_count = 0
        for backup in old_backups:
            try:
                # Ask the agent to remove the backup file from disk
                if backup.file_path:
                    httpx.post(
                        f"{settings.AGENT_URL}/api/v1/backups/delete",
                        json={"file_path": backup.file_path},
                        headers={"X-Agent-Secret": settings.AGENT_SECRET},
                        timeout=30.0,
                    )
                session.delete(backup)
                deleted_count += 1
            except httpx.HTTPError as exc:
                logger.warning(
                    "Failed to delete backup file %s: %s",
                    backup.file_path, exc,
                )

        session.commit()

    logger.info("Cleaned up %d old backups (cutoff: %s)", deleted_count, cutoff)
    return {"deleted_count": deleted_count, "cutoff": cutoff.isoformat()}


@app.task(
    name="api.tasks.backup_tasks.create_scheduled_backups",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    retry_backoff=True,
    retry_backoff_max=600,
)
def create_scheduled_backups(self) -> dict:
    """Create backups for all users that have auto-backup enabled.

    Dispatches individual ``create_user_backup`` tasks for each user.
    """
    from api.models.users import User

    logger.info("Scheduling automatic backups for eligible users")

    with get_sync_session() as session:
        # Users with active accounts get automatic backups
        users = session.execute(
            select(User).where(
                User.is_active.is_(True),
                User.is_suspended.is_(False),
            )
        ).scalars().all()

        dispatched = 0
        for user in users:
            create_user_backup.delay(str(user.id), "full")
            dispatched += 1

    logger.info("Dispatched %d scheduled backup tasks", dispatched)
    return {"dispatched": dispatched}
