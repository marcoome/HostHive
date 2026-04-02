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
from api.models.users import User
from api.schemas.backups import BackupCreate, BackupResponse

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


def _direct_create_backup(user_id: str, username: str, backup_type: str) -> tuple[str, int]:
    """Route to the correct backup function based on type."""
    if backup_type == "full":
        return _direct_create_full_backup(user_id, username)
    elif backup_type == "files_only":
        return _direct_create_files_only_backup(user_id, username)
    elif backup_type == "db_only":
        return _direct_create_db_backup(user_id, username)
    elif backup_type == "incremental":
        # Incremental treated the same as full for direct mode
        return _direct_create_full_backup(user_id, username)
    else:
        raise RuntimeError(f"Unknown backup type: {backup_type}")


def _direct_restore_backup(file_path: str, username: str) -> None:
    """Restore a backup by extracting tar to /home/{username}/."""
    home_dir = f"/home/{username}"
    if not os.path.isfile(file_path):
        raise RuntimeError(f"Backup file {file_path} does not exist")

    if file_path.endswith(".tar.gz"):
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
    elif file_path.endswith(".sql.gz"):
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
# PUT /schedule -- configure backup schedule
# --------------------------------------------------------------------------
@router.put("/schedule", status_code=status.HTTP_200_OK)
async def update_backup_schedule(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Save backup schedule to Redis."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    redis = request.app.state.redis
    import json as _json
    await redis.set(
        f"hosthive:backup_schedule:{current_user.id}",
        _json.dumps(body),
    )
    return {"detail": "Backup schedule updated.", **body}


@router.get("/schedule", status_code=status.HTTP_200_OK)
async def get_backup_schedule(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Get backup schedule from Redis."""
    redis = request.app.state.redis
    import json as _json
    data = await redis.get(f"hosthive:backup_schedule:{current_user.id}")
    if data:
        return _json.loads(data)
    return {"enabled": False, "frequency": "daily", "retention": 7, "backup_type": "full"}


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
    # Save pending backup to DB first
    backup = Backup(
        user_id=current_user.id,
        backup_type=body.backup_type,
        status=BackupStatus.IN_PROGRESS,
    )
    db.add(backup)
    await db.flush()

    # Try Celery/agent first
    dispatched_via_agent = False
    try:
        from api.tasks.backup_tasks import create_user_backup
        task = create_user_backup.delay(str(current_user.id), body.backup_type.value)
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
            loop = asyncio.get_running_loop()
            file_path, size_bytes = await loop.run_in_executor(
                None,
                _direct_create_backup,
                str(current_user.id),
                current_user.username,
                body.backup_type.value,
            )
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

    # Try agent first, fall back to direct
    restored = False
    agent = request.app.state.agent
    try:
        result = await agent.restore_backup(current_user.username, backup.file_path)
        restored = True
    except Exception as exc:
        logger.warning("Agent error restoring backup, falling back to direct: %s", exc)

    if not restored:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _direct_restore_backup, backup.file_path, current_user.username,
            )
        except Exception as exc:
            logger.error("Direct backup restore also failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restore backup: {exc}",
            )

    _log(db, request, current_user.id, "backups.restore", f"Restored backup {backup_id}")
    return {"detail": "Backup restored successfully."}


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
