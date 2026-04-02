"""Backups router -- /api/v1/backups."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.backups import Backup, BackupStatus
from api.models.users import User
from api.schemas.backups import BackupCreate, BackupResponse

router = APIRouter()


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
# POST /create -- trigger backup via Celery task
# --------------------------------------------------------------------------
@router.post("/create", status_code=status.HTTP_202_ACCEPTED)
async def create_backup(
    body: BackupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from api.tasks.backup_tasks import create_user_backup

    task = create_user_backup.delay(str(current_user.id), body.backup_type.value)

    _log(db, request, current_user.id, "backups.create", f"Triggered {body.backup_type.value} backup")
    return {"detail": "Backup task queued.", "task_id": task.id}


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

    agent = request.app.state.agent
    try:
        result = await agent.restore_backup(backup.file_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error restoring backup: {exc}",
        )

    _log(db, request, current_user.id, "backups.restore", f"Restored backup {backup_id}")
    return {"detail": "Backup restored successfully.", "result": result}


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
        agent = request.app.state.agent
        try:
            await agent._request(
                "DELETE",
                "/backup/file",
                json_body={"file_path": backup.file_path},
            )
        except Exception:
            pass  # best-effort cleanup

    _log(db, request, current_user.id, "backups.delete", f"Deleted backup {backup_id}")
    await db.delete(backup)
    await db.flush()


# --------------------------------------------------------------------------
# GET /{id}/download -- generate signed download URL
# --------------------------------------------------------------------------
@router.get("/{backup_id}/download", status_code=status.HTTP_200_OK)
async def download_backup(
    backup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    backup = await _get_backup_or_404(backup_id, db, current_user)

    if backup.status != BackupStatus.COMPLETED or not backup.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Backup is not available for download.",
        )

    # Generate a time-limited signed URL
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
