"""Backups router -- /api/v1/backups."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.backups import Backup, BackupStatus, BackupType
from api.models.integrations import Integration, IntegrationName
from api.models.packages import Package
from api.models.users import User
from api.schemas.backups import BackupCreate, BackupResponse, BackupSchedule, RestoreOptions
from api.services.s3_service import S3BackupService
from api.services.sftp_service import SFTPBackupService
from api.services.rclone_service import RcloneBackupService

router = APIRouter()
logger = logging.getLogger(__name__)

BACKUP_BASE_DIR = "/opt/hosthive/backups"


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_backup_or_404(
    backup_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Backup:
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalar_one_or_none()
    if backup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found.")
    if not _is_admin(current_user) and backup.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return backup


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# Direct backup operations (no agent)
# --------------------------------------------------------------------------

def _ensure_backup_dir(user_id: str) -> Path:
    """Ensure the backup directory for a user exists and return it."""
    backup_dir = Path(BACKUP_BASE_DIR) / user_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _direct_create_full_backup(user_id: str, username: str) -> tuple[str, int]:
    """Create a full backup of /home/{username}/ using tar.

    Returns (file_path, size_bytes).
    """
    backup_dir = _ensure_backup_dir(user_id)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{timestamp}_full.tar.gz"
    home_dir = f"/home/{username}"

    if not os.path.isdir(home_dir):
        raise RuntimeError(f"Home directory {home_dir} does not exist")

    result = subprocess.run(
        ["tar", "-czf", str(backup_file), "-C", "/home", username],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tar failed: {result.stderr.strip()}")

    size_bytes = os.path.getsize(backup_file)
    return str(backup_file), size_bytes


def _direct_create_files_only_backup(user_id: str, username: str) -> tuple[str, int]:
    """Create a files-only backup (same as full, excludes nothing extra)."""
    return _direct_create_full_backup(user_id, username)


def _direct_create_db_backup(user_id: str, username: str) -> tuple[str, int]:
    """Create a database-only backup (tries MySQL then PostgreSQL).

    Returns (file_path, size_bytes).
    """
    backup_dir = _ensure_backup_dir(user_id)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{timestamp}_db.sql.gz"

    # Convention: DB name matches username (common in hosting panels)
    db_name = username

    # Try mysqldump first
    mysql_result = subprocess.run(
        ["mysqldump", "-u", "root", "--databases", db_name],
        capture_output=True,
        text=False,
        timeout=300,
    )
    if mysql_result.returncode == 0:
        import gzip
        with gzip.open(backup_file, "wb") as f:
            f.write(mysql_result.stdout)
        size_bytes = os.path.getsize(backup_file)
        return str(backup_file), size_bytes

    # Fallback to pg_dump
    pg_result = subprocess.run(
        ["pg_dump", "-U", "postgres", db_name],
        capture_output=True,
        text=False,
        timeout=300,
    )
    if pg_result.returncode == 0:
        import gzip
        with gzip.open(backup_file, "wb") as f:
            f.write(pg_result.stdout)
        size_bytes = os.path.getsize(backup_file)
        return str(backup_file), size_bytes

    raise RuntimeError(
        f"Database backup failed. MySQL: {mysql_result.stderr[:200]}, "
        f"PostgreSQL: {pg_result.stderr[:200]}"
    )


def _direct_create_incremental_backup(
    user_id: str, username: str, parent_path: str | None,
) -> tuple[str, int, dict]:
    """Create an incremental backup using rsync --link-dest.

    Returns (snapshot_dir_path, size_bytes, metadata).
    """
    backup_dir = _ensure_backup_dir(user_id)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    snapshot_dir = backup_dir / f"{timestamp}_incremental"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    home_dir = f"/home/{username}"

    metadata: dict = {"parent_backup_path": parent_path, "type": "incremental"}

    if os.path.isdir(home_dir):
        rsync_cmd = ["rsync", "-a", "--stats", "--delete"]
        if parent_path:
            parent_files = os.path.join(parent_path, "files")
            if os.path.isdir(parent_files):
                rsync_cmd.append(f"--link-dest={parent_files}")
            elif os.path.isdir(parent_path):
                rsync_cmd.append(f"--link-dest={parent_path}")
        rsync_cmd += [home_dir + "/", str(files_dir) + "/"]

        result = subprocess.run(
            rsync_cmd, capture_output=True, text=True, timeout=600,
        )
        if result.returncode not in (0, 24):
            raise RuntimeError(f"rsync failed (rc={result.returncode}): {result.stderr.strip()}")

        for line in (result.stdout + result.stderr).splitlines():
            line = line.strip()
            if line.startswith("Number of regular files transferred:"):
                metadata["files_transferred"] = line.split(":", 1)[1].strip()
            elif line.startswith("Total transferred file size:"):
                metadata["transferred_size"] = line.split(":", 1)[1].strip()

    # DB dump inside the snapshot (always a fresh full dump)
    db_dir = snapshot_dir / "_dbdumps"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_name = username
    mysql_result = subprocess.run(
        ["mysqldump", "-u", "root", "--databases", db_name],
        capture_output=True, text=False, timeout=300,
    )
    if mysql_result.returncode == 0:
        (db_dir / "mysql_dump.sql").write_bytes(mysql_result.stdout)
        metadata.setdefault("db_engines_dumped", []).append("mysql")

    pg_result = subprocess.run(
        ["pg_dump", "-U", "postgres", db_name],
        capture_output=True, text=False, timeout=300,
    )
    if pg_result.returncode == 0:
        (db_dir / "pg_dumpall.sql").write_bytes(pg_result.stdout)
        metadata.setdefault("db_engines_dumped", []).append("postgres")

    du = subprocess.run(
        ["du", "-sb", str(snapshot_dir)], capture_output=True, text=True, timeout=60,
    )
    size_bytes = int(du.stdout.split()[0]) if du.returncode == 0 else 0

    return str(snapshot_dir), size_bytes, metadata


def _direct_create_backup(
    user_id: str, username: str, backup_type: str, parent_path: str | None = None,
) -> tuple[str, int] | tuple[str, int, dict]:
    """Route to the correct backup function based on type."""
    if backup_type == "full":
        return _direct_create_full_backup(user_id, username)
    elif backup_type == "files_only":
        return _direct_create_files_only_backup(user_id, username)
    elif backup_type == "db_only":
        return _direct_create_db_backup(user_id, username)
    elif backup_type == "incremental":
        return _direct_create_incremental_backup(user_id, username, parent_path)
    else:
        raise RuntimeError(f"Unknown backup type: {backup_type}")


def _direct_restore_backup(
    file_path: str,
    username: str,
    restore_options: dict | None = None,
) -> None:
    """Restore a backup by extracting tar to /home/{username}/.

    *restore_options* controls selective restore:
      - restore_files (bool)
      - restore_databases (bool)
      - restore_emails (bool)
      - restore_cron (bool)
      - target_path (str|None)
    """
    opts = restore_options or {}
    do_files = opts.get("restore_files", True)
    do_databases = opts.get("restore_databases", True)
    target_path = opts.get("target_path")

    home_dir = target_path or f"/home/{username}"

    if not os.path.isfile(file_path):
        raise RuntimeError(f"Backup file {file_path} does not exist")

    if file_path.endswith(".tar.gz"):
        if do_files:
            result = subprocess.run(
                ["tar", "-xzf", file_path, "-C", "/home"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"tar restore failed: {result.stderr.strip()}")
            # Fix ownership
            subprocess.run(
                ["chown", "-R", f"{username}:{username}", home_dir],
                capture_output=True,
                timeout=60,
            )
        elif do_databases:
            # Extract to temp dir and only restore DB dumps
            import tempfile
            with tempfile.TemporaryDirectory(prefix="hh_restore_") as tmp:
                result = subprocess.run(
                    ["tar", "-xzf", file_path, "-C", tmp],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"tar extract failed: {result.stderr.strip()}")
                # Look for SQL dumps in the extracted tree
                for root, _dirs, files in os.walk(tmp):
                    for fname in files:
                        if fname.endswith(".sql"):
                            sql_path = os.path.join(root, fname)
                            with open(sql_path, "rb") as f:
                                sql_data = f.read()
                            mysql_result = subprocess.run(
                                ["mysql", "-u", "root"],
                                input=sql_data,
                                capture_output=True,
                                timeout=300,
                            )
                            if mysql_result.returncode != 0:
                                subprocess.run(
                                    ["psql", "-U", "postgres", "-d", username],
                                    input=sql_data,
                                    capture_output=True,
                                    timeout=300,
                                )
    elif file_path.endswith(".sql.gz"):
        if not do_databases:
            return  # nothing to restore from a DB-only backup if databases not selected
        import gzip
        with gzip.open(file_path, "rb") as f:
            sql_data = f.read()
        # Try MySQL first
        mysql_result = subprocess.run(
            ["mysql", "-u", "root"],
            input=sql_data,
            capture_output=True,
            timeout=300,
        )
        if mysql_result.returncode != 0:
            # Fallback to PostgreSQL
            pg_result = subprocess.run(
                ["psql", "-U", "postgres", "-d", username],
                input=sql_data,
                capture_output=True,
                timeout=300,
            )
            if pg_result.returncode != 0:
                raise RuntimeError("DB restore failed for both MySQL and PostgreSQL")
    else:
        raise RuntimeError(f"Unknown backup format: {file_path}")


def _direct_delete_backup_file(file_path: str) -> None:
    """Delete a backup file from disk."""
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
    except OSError as exc:
        logger.warning("Failed to remove backup file %s: %s", file_path, exc)


# --------------------------------------------------------------------------
# GET / -- list backups for current user
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_backups(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Backup)
    count_query = select(func.count()).select_from(Backup)
    if not _is_admin(current_user):
        query = query.where(Backup.user_id == current_user.id)
        count_query = count_query.where(Backup.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(
        query.order_by(Backup.created_at.desc()).offset(skip).limit(limit)
    )).scalars().all()

    return {
        "items": [BackupResponse.model_validate(b) for b in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# PUT /schedule -- configure backup schedule (persists to DB + Redis cache)
# --------------------------------------------------------------------------
@router.put("/schedule", status_code=status.HTTP_200_OK)
async def update_backup_schedule(
    body: BackupSchedule,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist backup schedule to the User row in the database.

    Also caches in Redis for fast reads.
    """
    # Update the user record in the database (source of truth)
    current_user.backup_enabled = body.enabled
    current_user.backup_frequency = body.frequency
    current_user.backup_type = body.backup_type.value
    current_user.backup_retention_days = body.retention_days
    current_user.backup_retention_count = body.retention_count
    db.add(current_user)
    await db.flush()

    # Cache in Redis for quick reads
    import json as _json
    schedule_data = body.model_dump(mode="json")
    try:
        redis = request.app.state.redis
        await redis.set(
            f"hosthive:backup_schedule:{current_user.id}",
            _json.dumps(schedule_data),
        )
    except Exception:
        pass  # Redis is optional cache; DB is the source of truth

    _log(db, request, current_user.id, "backups.schedule", f"Updated backup schedule: {body.frequency}/{body.backup_type.value}")

    return {"detail": "Backup schedule updated.", **schedule_data}


@router.get("/schedule", status_code=status.HTTP_200_OK)
async def get_backup_schedule(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current backup schedule from the database."""
    return {
        "enabled": current_user.backup_enabled or False,
        "frequency": current_user.backup_frequency or "daily",
        "backup_type": current_user.backup_type or "full",
        "retention_days": current_user.backup_retention_days or 30,
        "retention_count": current_user.backup_retention_count or 5,
    }


# --------------------------------------------------------------------------
# POST /create -- trigger backup (agent -> direct fallback)
# --------------------------------------------------------------------------
@router.post("/create", status_code=status.HTTP_202_ACCEPTED)
async def create_backup(
    body: BackupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # -- Package limit check: max_backups --
    if not _is_admin(current_user) and current_user.package_id:
        pkg_result = await db.execute(select(Package).where(Package.id == current_user.package_id))
        pkg = pkg_result.scalar_one_or_none()
        if pkg and pkg.max_backups > 0:
            backup_count = (await db.execute(
                select(func.count()).select_from(Backup).where(
                    Backup.user_id == current_user.id,
                    Backup.status == BackupStatus.COMPLETED,
                )
            )).scalar() or 0
            if backup_count >= pkg.max_backups:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Backup limit reached ({pkg.max_backups}). Delete old backups or upgrade your package.",
                )

    # --- Resolve parent backup for incremental chain --------------------
    parent_backup: Backup | None = None
    parent_path: str | None = None

    if body.backup_type == BackupType.INCREMENTAL:
        if body.parent_backup_id:
            # Explicit parent specified by caller
            result = await db.execute(
                select(Backup).where(
                    Backup.id == body.parent_backup_id,
                    Backup.user_id == current_user.id,
                    Backup.status == BackupStatus.COMPLETED,
                )
            )
            parent_backup = result.scalar_one_or_none()
        else:
            # Auto-resolve: find latest completed backup for this user
            result = await db.execute(
                select(Backup).where(
                    Backup.user_id == current_user.id,
                    Backup.status == BackupStatus.COMPLETED,
                    Backup.file_path.isnot(None),
                ).order_by(Backup.created_at.desc()).limit(1)
            )
            parent_backup = result.scalar_one_or_none()

        if parent_backup and parent_backup.file_path:
            parent_path = parent_backup.file_path

    # Save pending backup to DB first
    backup = Backup(
        user_id=current_user.id,
        backup_type=body.backup_type,
        status=BackupStatus.IN_PROGRESS,
        parent_backup_id=parent_backup.id if parent_backup else None,
    )
    db.add(backup)
    await db.flush()

    # Try Celery/agent first
    dispatched_via_agent = False
    try:
        from api.tasks.backup_tasks import create_user_backup
        task = create_user_backup.delay(
            str(current_user.id),
            body.backup_type.value,
            parent_path=parent_path,
            backup_id=str(backup.id),
        )
        dispatched_via_agent = True
        _log(db, request, current_user.id, "backups.create", f"Triggered {body.backup_type.value} backup via agent")
        return {
            "detail": "Backup task queued.",
            "task_id": task.id,
            "backup": BackupResponse.model_validate(backup),
        }
    except Exception as exc:
        logger.warning("Celery/agent backup dispatch failed, falling back to direct: %s", exc)

    # Direct backup fallback
    if not dispatched_via_agent:
        try:
            import functools
            loop = asyncio.get_running_loop()
            result_data = await loop.run_in_executor(
                None,
                functools.partial(
                    _direct_create_backup,
                    str(current_user.id),
                    current_user.username,
                    body.backup_type.value,
                    parent_path=parent_path,
                ),
            )

            # Incremental returns a 3-tuple (path, size, metadata)
            if len(result_data) == 3:
                file_path, size_bytes, meta = result_data
                backup.backup_metadata = meta
            else:
                file_path, size_bytes = result_data

            backup.status = BackupStatus.COMPLETED
            backup.file_path = file_path
            backup.size_bytes = size_bytes
            db.add(backup)
            await db.flush()

            _log(db, request, current_user.id, "backups.create", f"Created {body.backup_type.value} backup directly")
            return {
                "detail": "Backup created successfully.",
                "backup": BackupResponse.model_validate(backup),
            }
        except Exception as exc:
            backup.status = BackupStatus.FAILED
            backup.error_message = str(exc)[:1024]
            db.add(backup)
            await db.flush()
            logger.error("Direct backup also failed for user %s: %s", current_user.id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Backup failed: {exc}",
            )


# --------------------------------------------------------------------------
# POST / -- alias for create (frontend compatibility)
# --------------------------------------------------------------------------
@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_backup_alias(
    body: BackupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await create_backup(body=body, request=request, db=db, current_user=current_user)


# --------------------------------------------------------------------------
# POST /{id}/restore -- restore backup via agent
# --------------------------------------------------------------------------
@router.post("/{backup_id}/restore", status_code=status.HTTP_200_OK)
async def restore_backup(
    backup_id: uuid.UUID,
    request: Request,
    body: RestoreOptions | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.status != BackupStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed backups can be restored.",
        )
    if not backup.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Backup has no associated file.",
        )

    options_dict = body.model_dump() if body else {}

    # Try agent first, fall back to direct
    restored = False
    agent = request.app.state.agent
    try:
        result = await agent.restore_backup(
            current_user.username, backup.file_path, restore_options=options_dict,
        )
        restored = True
    except Exception as exc:
        logger.warning("Agent error restoring backup, falling back to direct: %s", exc)

    if not restored:
        try:
            import functools
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                functools.partial(
                    _direct_restore_backup,
                    backup.file_path,
                    current_user.username,
                    restore_options=options_dict,
                ),
            )
        except Exception as exc:
            logger.error("Direct backup restore also failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restore backup: {exc}",
            )

    selected = [k.replace("restore_", "") for k, v in options_dict.items() if k.startswith("restore_") and v]
    _log(db, request, current_user.id, "backups.restore", f"Restored backup {backup_id} (components: {', '.join(selected) or 'all'})")
    return {"detail": "Backup restored successfully.", "restored_components": selected}


# --------------------------------------------------------------------------
# DELETE /{id} -- delete backup file via agent
# --------------------------------------------------------------------------
@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    backup_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.file_path:
        # Try agent first, fall back to direct file deletion
        deleted_via_agent = False
        agent = request.app.state.agent
        try:
            await agent._request(
                "DELETE",
                "/backup/file",
                json_body={"file_path": backup.file_path},
            )
            deleted_via_agent = True
        except Exception as exc:
            logger.warning("Agent error deleting backup file, falling back to direct: %s", exc)

        if not deleted_via_agent:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _direct_delete_backup_file, backup.file_path)
            except Exception as exc:
                logger.warning("Direct backup file deletion also failed: %s", exc)

    _log(db, request, current_user.id, "backups.delete", f"Deleted backup {backup_id}")
    await db.delete(backup)
    await db.flush()


# --------------------------------------------------------------------------
# GET /{id}/download -- generate signed download URL
# --------------------------------------------------------------------------
@router.get("/{backup_id}/download", status_code=status.HTTP_200_OK)
async def download_backup(
    backup_id: uuid.UUID,
    direct: bool = Query(False, description="Serve the file directly instead of a signed URL"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.status != BackupStatus.COMPLETED or not backup.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Backup is not available for download.",
        )

    # Direct file serving (no agent needed)
    if direct or not settings.AGENT_URL:
        if not os.path.isfile(backup.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Backup file not found on disk.",
            )
        filename = os.path.basename(backup.file_path)
        return FileResponse(
            path=backup.file_path,
            filename=filename,
            media_type="application/gzip",
        )

    # Generate a time-limited signed URL (agent-based download)
    expires = int(time.time()) + 3600  # 1 hour
    payload = f"{backup.file_path}:{expires}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    download_url = (
        f"{settings.AGENT_URL}/backup/download"
        f"?path={backup.file_path}&expires={expires}&sig={signature}"
    )

    return {
        "download_url": download_url,
        "expires_in": 3600,
        "file_path": backup.file_path,
        "size_bytes": backup.size_bytes,
    }


# --------------------------------------------------------------------------
# S3 remote backup helpers
# --------------------------------------------------------------------------

def _decrypt_integration_config(cipher_text: str) -> dict:
    """Decrypt an integration config_json using the integrations Fernet key."""
    import base64
    import hashlib as _hashlib
    import json as _json
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(_hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    fernet = Fernet(key)
    return _json.loads(fernet.decrypt(cipher_text.encode()).decode())


async def _get_s3_service(db: AsyncSession) -> S3BackupService:
    """Retrieve the S3 integration config and return an S3BackupService instance.

    Raises HTTPException 400 if S3 is not configured or not enabled.
    """
    result = await db.execute(
        select(Integration).where(Integration.name == IntegrationName.S3)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled or not integration.config_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3 integration is not configured or not enabled.",
        )
    config = _decrypt_integration_config(integration.config_json)
    return S3BackupService.from_config(config)


# --------------------------------------------------------------------------
# POST /{id}/upload-remote -- upload existing local backup to S3
# --------------------------------------------------------------------------
@router.post("/{backup_id}/upload-remote", status_code=status.HTTP_200_OK)
async def upload_backup_to_s3(
    backup_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a completed local backup to S3-compatible remote storage."""
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.status != BackupStatus.COMPLETED or not backup.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed backups with a file can be uploaded.",
        )
    if not os.path.isfile(backup.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup file not found on disk.",
        )

    s3 = await _get_s3_service(db)
    remote_key = f"backups/{current_user.id}/{os.path.basename(backup.file_path)}"

    try:
        result = await s3.upload_backup(backup.file_path, remote_key)
    except Exception as exc:
        logger.error("S3 upload failed for backup %s: %s", backup_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload to S3: {exc}",
        )

    # Track the remote key on the backup record
    backup.remote_key = result["key"]
    db.add(backup)

    _log(db, request, current_user.id, "backups.upload_remote", f"Uploaded backup {backup_id} to S3 key {remote_key}")
    await db.flush()

    return {
        "detail": "Backup uploaded to remote storage.",
        "backup": BackupResponse.model_validate(backup),
        "remote_key": result["key"],
        "size": result["size"],
    }


# --------------------------------------------------------------------------
# GET /remote -- list remote backups from S3
# --------------------------------------------------------------------------
@router.get("/remote", status_code=status.HTTP_200_OK)
async def list_remote_backups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List backups stored in S3-compatible remote storage."""
    s3 = await _get_s3_service(db)

    # Scope listing to the current user's prefix (admins see all)
    prefix = "" if _is_admin(current_user) else f"backups/{current_user.id}/"

    try:
        objects = await s3.list_backups(prefix=prefix)
    except Exception as exc:
        logger.error("S3 list failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list remote backups: {exc}",
        )

    return {"items": objects, "total": len(objects)}


# --------------------------------------------------------------------------
# POST /remote/{key}/restore -- download from S3 and restore
# --------------------------------------------------------------------------
@router.post("/remote/{key:path}/restore", status_code=status.HTTP_200_OK)
async def restore_remote_backup(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a backup from S3 and restore it locally."""
    # Non-admin users can only restore their own backups
    if not _is_admin(current_user) and not key.startswith(f"backups/{current_user.id}/"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    s3 = await _get_s3_service(db)

    # Download to a temporary local path
    local_dir = _ensure_backup_dir(str(current_user.id))
    local_path = str(local_dir / f"s3_restore_{os.path.basename(key)}")

    try:
        await s3.download_backup(key, local_path)
    except Exception as exc:
        logger.error("S3 download failed for key %s: %s", key, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to download from S3: {exc}",
        )

    # Restore the downloaded file
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _direct_restore_backup, local_path, current_user.username,
        )
    except Exception as exc:
        logger.error("Restore failed after S3 download for key %s: %s", key, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {exc}",
        )
    finally:
        # Clean up the downloaded file
        try:
            if os.path.isfile(local_path):
                os.remove(local_path)
        except OSError:
            pass

    _log(db, request, current_user.id, "backups.restore_remote", f"Restored remote backup {key}")
    await db.flush()

    return {"detail": "Remote backup restored successfully.", "key": key}


# --------------------------------------------------------------------------
# DELETE /remote/{key} -- delete remote backup from S3
# --------------------------------------------------------------------------
@router.delete("/remote/{key:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_remote_backup(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a backup from S3-compatible remote storage."""
    if not _is_admin(current_user) and not key.startswith(f"backups/{current_user.id}/"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    s3 = await _get_s3_service(db)

    try:
        await s3.delete_backup(key)
    except Exception as exc:
        logger.error("S3 delete failed for key %s: %s", key, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete remote backup: {exc}",
        )

    _log(db, request, current_user.id, "backups.delete_remote", f"Deleted remote backup {key}")
    await db.flush()


# --------------------------------------------------------------------------
# SFTP remote backup helpers
# --------------------------------------------------------------------------

async def _get_sftp_service(db: AsyncSession) -> SFTPBackupService:
    """Retrieve the SFTP integration config and return an SFTPBackupService."""
    result = await db.execute(
        select(Integration).where(Integration.name == IntegrationName.SFTP)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled or not integration.config_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SFTP integration is not configured or not enabled.",
        )
    config = _decrypt_integration_config(integration.config_json)
    return SFTPBackupService.from_config(config)


# --------------------------------------------------------------------------
# Rclone remote backup helpers
# --------------------------------------------------------------------------

async def _get_rclone_service(db: AsyncSession) -> RcloneBackupService:
    """Retrieve the Rclone integration config and return an RcloneBackupService."""
    result = await db.execute(
        select(Integration).where(Integration.name == IntegrationName.RCLONE)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled or not integration.config_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rclone integration is not configured or not enabled.",
        )
    config = _decrypt_integration_config(integration.config_json)
    return RcloneBackupService.from_config(config)


# --------------------------------------------------------------------------
# POST /{id}/upload-sftp -- upload existing local backup to SFTP
# --------------------------------------------------------------------------
@router.post("/{backup_id}/upload-sftp", status_code=status.HTTP_200_OK)
async def upload_backup_to_sftp(
    backup_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a completed local backup to an SFTP server."""
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.status != BackupStatus.COMPLETED or not backup.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed backups with a file can be uploaded.",
        )
    if not os.path.isfile(backup.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup file not found on disk.",
        )

    sftp_svc = await _get_sftp_service(db)
    remote_key = f"backups/{current_user.id}/{os.path.basename(backup.file_path)}"

    try:
        result = await sftp_svc.upload_backup(backup.file_path, remote_key)
    except Exception as exc:
        logger.error("SFTP upload failed for backup %s: %s", backup_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload to SFTP: {exc}",
        )

    backup.remote_key = result["key"]
    db.add(backup)

    _log(db, request, current_user.id, "backups.upload_sftp", f"Uploaded backup {backup_id} to SFTP key {remote_key}")
    await db.flush()

    return {
        "detail": "Backup uploaded to SFTP remote storage.",
        "backup": BackupResponse.model_validate(backup),
        "remote_key": result["key"],
        "size": result["size"],
    }


# --------------------------------------------------------------------------
# POST /{id}/upload-rclone -- upload existing local backup via Rclone
# --------------------------------------------------------------------------
@router.post("/{backup_id}/upload-rclone", status_code=status.HTTP_200_OK)
async def upload_backup_to_rclone(
    backup_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a completed local backup via Rclone (Google Drive, B2, Dropbox, etc.)."""
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.status != BackupStatus.COMPLETED or not backup.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed backups with a file can be uploaded.",
        )
    if not os.path.isfile(backup.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup file not found on disk.",
        )

    rclone_svc = await _get_rclone_service(db)
    remote_key = f"backups/{current_user.id}/{os.path.basename(backup.file_path)}"

    try:
        result = await rclone_svc.upload_backup(backup.file_path, remote_key)
    except Exception as exc:
        logger.error("Rclone upload failed for backup %s: %s", backup_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload via Rclone: {exc}",
        )

    backup.remote_key = result["key"]
    db.add(backup)

    _log(db, request, current_user.id, "backups.upload_rclone", f"Uploaded backup {backup_id} via Rclone key {remote_key}")
    await db.flush()

    return {
        "detail": "Backup uploaded via Rclone remote storage.",
        "backup": BackupResponse.model_validate(backup),
        "remote_key": result["key"],
        "size": result["size"],
    }
