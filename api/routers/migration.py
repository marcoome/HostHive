"""Migration router -- /api/v1/admin/migration (admin only).

Endpoints for importing server accounts from cPanel and HestiaCP backups.
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import require_role
from api.models.users import User
from api.schemas.migration import (
    MigrationAnalysis,
    MigrationExecuteRequest,
    MigrationStatus,
    MigrationStep,
    SourceType,
)
from api.services.migration_service import (
    CpanelMigrator,
    HestiaMigrator,
    detect_backup_type,
    extract_backup,
)

logger = logging.getLogger("hosthive.migration")

router = APIRouter()
_admin = require_role("admin")

_UPLOAD_DIR = Path("/opt/hosthive/tmp/migrations")
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB


# ---------------------------------------------------------------------------
# POST /upload -- upload a backup file
# ---------------------------------------------------------------------------

@router.post("/upload", status_code=status.HTTP_200_OK)
async def upload_backup(
    request: Request,
    file: UploadFile = File(...),
    admin: User = Depends(_admin),
):
    """Upload a cPanel or HestiaCP backup file (tar.gz).

    Returns a backup_id that is used in subsequent analyze/execute calls.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    if not file.filename.endswith((".tar.gz", ".tgz", ".tar")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a .tar.gz or .tar file.",
        )

    backup_id = secrets.token_urlsafe(16)
    backup_dir = _UPLOAD_DIR / backup_id
    backup_dir.mkdir(parents=True, exist_ok=True)

    dest_path = backup_dir / file.filename
    total_written = 0

    try:
        with open(dest_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # 1 MB chunks
                total_written += len(chunk)
                if total_written > _MAX_UPLOAD_SIZE:
                    # Clean up and reject
                    f.close()
                    shutil.rmtree(backup_dir, ignore_errors=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size is {_MAX_UPLOAD_SIZE // (1024**3)} GB.",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        shutil.rmtree(backup_dir, ignore_errors=True)
        logger.exception("Failed to save uploaded backup")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")

    logger.info(
        "Backup uploaded: id=%s file=%s size=%d by admin=%s",
        backup_id, file.filename, total_written, admin.username,
    )

    return {
        "backup_id": backup_id,
        "filename": file.filename,
        "size_bytes": total_written,
        "detail": "Backup uploaded successfully. Call /analyze to inspect contents.",
    }


# ---------------------------------------------------------------------------
# POST /analyze -- extract and analyze a backup
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=MigrationAnalysis, status_code=status.HTTP_200_OK)
async def analyze_backup(
    request: Request,
    body: dict,
    admin: User = Depends(_admin),
):
    """Extract and analyze an uploaded backup. Returns a summary of what will be imported."""
    backup_id = body.get("backup_id")
    if not backup_id:
        raise HTTPException(status_code=400, detail="backup_id is required.")

    backup_dir = _UPLOAD_DIR / backup_id
    if not backup_dir.is_dir():
        raise HTTPException(status_code=404, detail="Backup not found. Upload it first.")

    # Find the uploaded archive
    archives = list(backup_dir.glob("*.tar.gz")) + list(backup_dir.glob("*.tgz")) + list(backup_dir.glob("*.tar"))
    if not archives:
        raise HTTPException(status_code=404, detail="No archive file found in backup directory.")

    archive_path = archives[0]
    extract_dir = backup_dir / "extracted"
    if extract_dir.is_dir():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()

    # Extract
    try:
        extract_backup(str(archive_path), str(extract_dir))
    except Exception as exc:
        logger.exception("Failed to extract backup %s", backup_id)
        raise HTTPException(status_code=400, detail=f"Failed to extract archive: {exc}")

    # Detect type and analyze
    try:
        migrator = detect_backup_type(extract_dir)
        analysis = migrator.analyze()
        analysis.backup_id = backup_id
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to analyze backup %s", backup_id)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    # Cache analysis in Redis for the execute step
    redis = request.app.state.redis
    await redis.set(
        f"hosthive:migration:{backup_id}:analysis",
        analysis.model_dump_json(),
        ex=86400,
    )

    logger.info(
        "Backup analyzed: id=%s type=%s domains=%d dbs=%d emails=%d",
        backup_id, analysis.source_type.value,
        analysis.total_domains, analysis.total_databases, analysis.total_emails,
    )

    return analysis


# ---------------------------------------------------------------------------
# POST /execute -- start the migration
# ---------------------------------------------------------------------------

@router.post("/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_migration(
    request: Request,
    body: MigrationExecuteRequest,
    admin: User = Depends(_admin),
):
    """Start executing the migration asynchronously via Celery.

    Requires a prior /analyze call for the given backup_id.
    """
    redis = request.app.state.redis
    analysis_json = await redis.get(f"hosthive:migration:{body.backup_id}:analysis")
    if not analysis_json:
        raise HTTPException(
            status_code=400,
            detail="No analysis found for this backup_id. Call /analyze first.",
        )

    # Verify the backup directory still exists
    backup_dir = _UPLOAD_DIR / body.backup_id
    extract_dir = backup_dir / "extracted"
    if not extract_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Extracted backup files not found. Re-upload and analyze.",
        )

    # Initialize status in Redis
    initial_status = {
        "backup_id": body.backup_id,
        "progress": 0.0,
        "current_step": MigrationStep.PENDING.value,
        "steps_completed": [],
        "errors": [],
        "warnings": [],
        "created_user_ids": [],
        "created_domain_ids": [],
        "created_database_ids": [],
        "created_email_ids": [],
    }
    await redis.set(
        f"hosthive:migration:{body.backup_id}",
        json.dumps(initial_status),
        ex=86400,
    )

    # Dispatch Celery task
    from api.tasks.migration_tasks import execute_migration as migration_task

    task = migration_task.delay(
        backup_id=body.backup_id,
        analysis_json=analysis_json,
        options_json=body.options.model_dump_json(),
    )

    logger.info(
        "Migration started: backup_id=%s task_id=%s by admin=%s",
        body.backup_id, task.id, admin.username,
    )

    return {
        "backup_id": body.backup_id,
        "task_id": task.id,
        "detail": "Migration started. Poll /status for progress.",
    }


# ---------------------------------------------------------------------------
# GET /status -- poll migration progress
# ---------------------------------------------------------------------------

@router.get("/status", response_model=MigrationStatus, status_code=status.HTTP_200_OK)
async def get_migration_status(
    request: Request,
    backup_id: str,
    admin: User = Depends(_admin),
):
    """Get the current progress of a running or completed migration."""
    redis = request.app.state.redis
    raw = await redis.get(f"hosthive:migration:{backup_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="No migration found for this backup_id.")

    data = json.loads(raw)
    return MigrationStatus(**data)
