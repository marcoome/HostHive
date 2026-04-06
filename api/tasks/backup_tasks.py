"""HostHive backup tasks."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.backup")


def _decrypt_integration_config(cipher_text: str) -> dict:
    """Decrypt an integration config_json using the integrations Fernet key."""
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    fernet = Fernet(key)
    return json.loads(fernet.decrypt(cipher_text.encode()).decode())


def _get_integration_config(session: Session, name) -> dict | None:
    """Return the decrypted integration config for *name*, or None if not configured."""
    from api.models.integrations import Integration

    result = session.execute(
        select(Integration).where(Integration.name == name)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled or not integration.config_json:
        return None

    try:
        return _decrypt_integration_config(integration.config_json)
    except Exception as exc:
        logger.warning("Failed to decrypt %s integration config: %s", name, exc)
        return None


def _get_s3_integration_config(session: Session) -> dict | None:
    """Return the decrypted S3 integration config, or None if not configured/enabled."""
    from api.models.integrations import IntegrationName
    return _get_integration_config(session, IntegrationName.S3)


def _get_sftp_integration_config(session: Session) -> dict | None:
    """Return the decrypted SFTP integration config, or None if not configured/enabled."""
    from api.models.integrations import IntegrationName
    return _get_integration_config(session, IntegrationName.SFTP)


def _get_rclone_integration_config(session: Session) -> dict | None:
    """Return the decrypted Rclone integration config, or None if not configured/enabled."""
    from api.models.integrations import IntegrationName
    return _get_integration_config(session, IntegrationName.RCLONE)


def _sync_upload_to_s3(s3_config: dict, file_path: str, remote_key: str) -> dict:
    """Synchronously upload a file to S3 by running the async method in a new event loop."""
    from api.services.s3_service import S3BackupService

    s3 = S3BackupService.from_config(s3_config)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(s3.upload_backup(file_path, remote_key))
    finally:
        loop.close()


def _sync_cleanup_s3(s3_config: dict, keep: int) -> int:
    """Synchronously clean up old S3 backups."""
    from api.services.s3_service import S3BackupService

    s3 = S3BackupService.from_config(s3_config)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(s3.cleanup_old_backups(keep=keep))
    finally:
        loop.close()


def _sync_upload_to_sftp(sftp_config: dict, file_path: str, remote_key: str) -> dict:
    """Synchronously upload a file to SFTP."""
    from api.services.sftp_service import SFTPBackupService

    sftp = SFTPBackupService.from_config(sftp_config)
    return sftp.upload_backup_sync(file_path, remote_key)


def _sync_cleanup_sftp(sftp_config: dict, keep: int) -> int:
    """Synchronously clean up old SFTP backups."""
    from api.services.sftp_service import SFTPBackupService

    sftp = SFTPBackupService.from_config(sftp_config)
    return sftp.cleanup_old_backups_sync(keep=keep)


def _sync_upload_to_rclone(rclone_config: dict, file_path: str, remote_key: str) -> dict:
    """Synchronously upload a file via Rclone."""
    from api.services.rclone_service import RcloneBackupService

    rclone = RcloneBackupService.from_config(rclone_config)
    return rclone.upload_backup_sync(file_path, remote_key)


def _sync_cleanup_rclone(rclone_config: dict, keep: int) -> int:
    """Synchronously clean up old Rclone backups."""
    from api.services.rclone_service import RcloneBackupService

    rclone = RcloneBackupService.from_config(rclone_config)
    return rclone.cleanup_old_backups_sync(keep=keep)


def _auto_upload_to_remote(session: Session, backup, user_id: str, backup_id: str) -> None:
    """Auto-upload a completed backup to whichever remote backend is configured.

    Checks S3 first, then SFTP, then Rclone. Uses the first one that is enabled.
    """
    remote_key = f"backups/{user_id}/{os.path.basename(backup.file_path)}"

    # Try S3
    s3_config = _get_s3_integration_config(session)
    if s3_config and backup.file_path:
        try:
            _sync_upload_to_s3(s3_config, backup.file_path, remote_key)
            backup.remote_key = remote_key
            session.commit()
            logger.info("Auto-uploaded backup %s to S3 key %s", backup_id, remote_key)
            return
        except Exception as exc:
            logger.warning("S3 auto-upload failed for backup %s (non-fatal): %s", backup_id, exc)

    # Try SFTP
    sftp_config = _get_sftp_integration_config(session)
    if sftp_config and backup.file_path:
        try:
            _sync_upload_to_sftp(sftp_config, backup.file_path, remote_key)
            backup.remote_key = remote_key
            session.commit()
            logger.info("Auto-uploaded backup %s to SFTP key %s", backup_id, remote_key)
            return
        except Exception as exc:
            logger.warning("SFTP auto-upload failed for backup %s (non-fatal): %s", backup_id, exc)

    # Try Rclone
    rclone_config = _get_rclone_integration_config(session)
    if rclone_config and backup.file_path:
        try:
            _sync_upload_to_rclone(rclone_config, backup.file_path, remote_key)
            backup.remote_key = remote_key
            session.commit()
            logger.info("Auto-uploaded backup %s via Rclone key %s", backup_id, remote_key)
            return
        except Exception as exc:
            logger.warning("Rclone auto-upload failed for backup %s (non-fatal): %s", backup_id, exc)


@app.task(
    name="api.tasks.backup_tasks.create_user_backup",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
)
def create_user_backup(
    self,
    user_id: str,
    backup_type: str = "full",
    parent_path: str | None = None,
    backup_id: str | None = None,
) -> dict:
    """Create a backup for a single user via the HostHive agent.

    Args:
        user_id: UUID of the user whose data to back up.
        backup_type: One of full, incremental, files_only, db_only.
        parent_path: For incremental backups, the file_path of the parent
            backup to use as the --link-dest reference.
        backup_id: If the caller already created a Backup row, pass its ID
            so we update that row instead of creating a new one.

    Returns:
        Dict with backup_id, status, and file_path.
    """
    from api.models.backups import Backup, BackupStatus, BackupType

    logger.info("Starting %s backup for user %s", backup_type, user_id)

    with get_sync_session() as session:
        # Reuse existing row or create a new one
        if backup_id:
            import uuid as _uuid
            backup = session.get(Backup, _uuid.UUID(backup_id))
            if backup is None:
                backup = Backup(
                    user_id=user_id,
                    backup_type=BackupType(backup_type),
                    status=BackupStatus.IN_PROGRESS,
                )
                session.add(backup)
                session.commit()
                backup_id = str(backup.id)
        else:
            # Resolve parent for incremental if not provided
            parent_backup_ref = None
            if backup_type == "incremental" and parent_path is None:
                parent_backup_ref = session.execute(
                    select(Backup).where(
                        Backup.user_id == user_id,
                        Backup.status == BackupStatus.COMPLETED,
                        Backup.file_path.isnot(None),
                    ).order_by(Backup.created_at.desc()).limit(1)
                ).scalar_one_or_none()
                if parent_backup_ref:
                    parent_path = parent_backup_ref.file_path

            backup = Backup(
                user_id=user_id,
                backup_type=BackupType(backup_type),
                status=BackupStatus.IN_PROGRESS,
                parent_backup_id=(
                    parent_backup_ref.id if parent_backup_ref else None
                ),
            )
            session.add(backup)
            session.commit()
            backup_id = str(backup.id)

        try:
            # Build the request payload
            agent_payload: dict = {
                "user_id": user_id,
                "backup_type": backup_type,
                "backup_id": backup_id,
            }
            if backup_type == "incremental" and parent_path:
                agent_payload["parent_path"] = parent_path

            # Call the HostHive agent to perform the actual backup
            response = httpx.post(
                f"{settings.AGENT_URL}/api/v1/backups/create",
                json=agent_payload,
                headers={"X-Agent-Secret": settings.AGENT_SECRET},
                timeout=600.0,
            )
            response.raise_for_status()
            result = response.json()

            # Update backup record with result
            backup.status = BackupStatus.COMPLETED
            backup.file_path = result.get("file_path")
            backup.size_bytes = result.get("size_bytes")
            if result.get("metadata"):
                backup.backup_metadata = result["metadata"]
            session.commit()

            logger.info(
                "Backup %s completed for user %s (%s bytes)",
                backup_id, user_id, backup.size_bytes,
            )

            # Auto-upload to remote storage if any backend is configured
            if backup.file_path:
                _auto_upload_to_remote(session, backup, user_id, backup_id)

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
    """Delete backup records and files based on per-user retention settings.

    For each user enforces both ``backup_retention_days`` (age-based) and
    ``backup_retention_count`` (count-based).  Falls back to 30 days / 5
    count when the user has no preference stored.
    """
    from api.models.backups import Backup
    from api.models.users import User

    logger.info("Starting cleanup of old backups (per-user retention)")

    with get_sync_session() as session:
        users = session.execute(
            select(User).where(User.is_active.is_(True))
        ).scalars().all()

        deleted_count = 0

        for user in users:
            retention_days = user.backup_retention_days or 30
            retention_count = user.backup_retention_count or 5
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            # --- Age-based retention ---
            old_backups = session.execute(
                select(Backup).where(
                    Backup.user_id == user.id,
                    Backup.created_at < cutoff,
                )
            ).scalars().all()

            for backup in old_backups:
                try:
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

            # --- Count-based retention: keep only the N most recent ---
            remaining = session.execute(
                select(Backup)
                .where(Backup.user_id == user.id)
                .order_by(Backup.created_at.desc())
            ).scalars().all()

            if len(remaining) > retention_count:
                for backup in remaining[retention_count:]:
                    try:
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
                            "Failed to delete excess backup %s: %s",
                            backup.file_path, exc,
                        )

        session.commit()

    logger.info("Cleaned up %d old backups (per-user retention)", deleted_count)
    return {"deleted_count": deleted_count}


def _is_backup_due(user) -> bool:
    """Check whether the user is due for a backup based on their frequency setting.

    Returns True when enough time has elapsed since ``last_backup_at``
    according to the user's ``backup_frequency`` (daily / weekly / monthly).
    If the user has never been backed up, they are always due.
    """
    if user.last_backup_at is None:
        return True

    now = datetime.now(timezone.utc)
    elapsed = now - user.last_backup_at.replace(tzinfo=timezone.utc)
    freq = (user.backup_frequency or "daily").lower()

    if freq == "daily":
        return elapsed >= timedelta(days=1)
    elif freq == "weekly":
        return elapsed >= timedelta(weeks=1)
    elif freq == "monthly":
        return elapsed >= timedelta(days=30)

    # Unknown frequency -- fall back to daily
    return elapsed >= timedelta(days=1)


@app.task(
    name="api.tasks.backup_tasks.create_scheduled_backups",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    retry_backoff=True,
    retry_backoff_max=600,
)
def create_scheduled_backups(self) -> dict:
    """Create backups for users that have auto-backup enabled and are due.

    Honors each user's ``backup_enabled``, ``backup_frequency``, and
    ``backup_type`` settings.  Only dispatches a task when enough time
    has elapsed since ``last_backup_at``.
    """
    from api.models.users import User

    logger.info("Scheduling automatic backups for eligible users")

    s3_cleaned = 0

    with get_sync_session() as session:
        # Only fetch users that opted in to automatic backups
        users = session.execute(
            select(User).where(
                User.is_active.is_(True),
                User.is_suspended.is_(False),
                User.backup_enabled.is_(True),
            )
        ).scalars().all()

        dispatched = 0
        skipped = 0
        for user in users:
            if not _is_backup_due(user):
                skipped += 1
                continue

            backup_type = (user.backup_type or "full").lower()

            # For incremental, resolve the parent backup path
            parent_path = None
            if backup_type == "incremental":
                from api.models.backups import Backup, BackupStatus
                latest = session.execute(
                    select(Backup).where(
                        Backup.user_id == user.id,
                        Backup.status == BackupStatus.COMPLETED,
                        Backup.file_path.isnot(None),
                    ).order_by(Backup.created_at.desc()).limit(1)
                ).scalar_one_or_none()
                if latest:
                    parent_path = latest.file_path

            create_user_backup.delay(
                str(user.id), backup_type, parent_path=parent_path,
            )

            # Stamp the user so the next run knows when they were last backed up
            user.last_backup_at = datetime.now(timezone.utc)
            dispatched += 1

        session.commit()

        # Clean up old remote backups for each configured backend
        s3_config = _get_s3_integration_config(session)
        if s3_config:
            retention = s3_config.get("retention", 30)
            try:
                s3_cleaned = _sync_cleanup_s3(s3_config, keep=retention)
                logger.info("S3 cleanup removed %d old backups (retention=%d)", s3_cleaned, retention)
            except Exception as exc:
                logger.warning("S3 cleanup failed (non-fatal): %s", exc)

        sftp_cleaned = 0
        sftp_config = _get_sftp_integration_config(session)
        if sftp_config:
            retention = sftp_config.get("retention", 30)
            try:
                sftp_cleaned = _sync_cleanup_sftp(sftp_config, keep=retention)
                logger.info("SFTP cleanup removed %d old backups (retention=%d)", sftp_cleaned, retention)
            except Exception as exc:
                logger.warning("SFTP cleanup failed (non-fatal): %s", exc)

        rclone_cleaned = 0
        rclone_config = _get_rclone_integration_config(session)
        if rclone_config:
            retention = rclone_config.get("retention", 30)
            try:
                rclone_cleaned = _sync_cleanup_rclone(rclone_config, keep=retention)
                logger.info("Rclone cleanup removed %d old backups (retention=%d)", rclone_cleaned, retention)
            except Exception as exc:
                logger.warning("Rclone cleanup failed (non-fatal): %s", exc)

    logger.info(
        "Dispatched %d scheduled backup tasks (%d skipped, not yet due)",
        dispatched, skipped,
    )
    return {
        "dispatched": dispatched,
        "skipped": skipped,
        "s3_cleaned": s3_cleaned,
        "sftp_cleaned": sftp_cleaned,
        "rclone_cleaned": rclone_cleaned,
    }
