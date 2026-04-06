"""Antivirus router -- /api/v1/antivirus (admin only).

Provides ClamAV antivirus management: on-demand scanning, quarantine
management, ClamAV status monitoring, and freshclam database updates.

Scans are dispatched asynchronously via Celery so that large directory
scans do not block the API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, require_role
from api.models.activity_log import ActivityLog
from api.models.antivirus import QuarantineEntry, ScanResult, ScanStatus
from api.models.users import User
from api.schemas.antivirus import (
    AntivirusStatusResponse,
    QuarantineEntryResponse,
    ScanPathRequest,
    ScanResultResponse,
)

router = APIRouter()
log = logging.getLogger("hosthive.antivirus")

_admin = require_role("admin")

QUARANTINE_DIR = Path("/opt/hosthive/quarantine")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _run_async(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a shell command asynchronously via asyncio."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout),
    )


def _sanitize_path(path: str) -> str:
    """Basic path sanitisation -- block obvious traversal attacks."""
    path = os.path.normpath(path)
    if ".." in path.split(os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal is not allowed.",
        )
    return path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ===========================================================================
# POST /scan -- trigger full manual scan (async via Celery)
# ===========================================================================

@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def trigger_full_scan(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Trigger a full antivirus scan of all user home directories.

    The scan is dispatched to a Celery worker and returns immediately
    with the scan record ID and Celery task ID.
    """
    from api.tasks.server_tasks import run_antivirus_scan

    scan = ScanResult(
        user_id=admin.id,
        scan_path="/home",
        status=ScanStatus.PENDING,
    )
    db.add(scan)
    await db.flush()
    await db.refresh(scan)

    task = run_antivirus_scan.delay(str(scan.id), "/home")
    scan.celery_task_id = task.id
    db.add(scan)

    _log_activity(db, request, admin.id, "antivirus.scan", "Triggered full antivirus scan on /home")

    return {
        "scan_id": str(scan.id),
        "celery_task_id": task.id,
        "status": "pending",
        "message": "Scan dispatched to worker. Poll GET /antivirus/scans/{id} for progress.",
    }


# ===========================================================================
# POST /scan/path -- scan a specific path (async via Celery)
# ===========================================================================

@router.post("/scan/path", status_code=status.HTTP_202_ACCEPTED)
async def trigger_path_scan(
    body: ScanPathRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Trigger an antivirus scan on a specific path."""
    from api.tasks.server_tasks import run_antivirus_scan

    path = _sanitize_path(body.path)

    scan = ScanResult(
        user_id=admin.id,
        scan_path=path,
        status=ScanStatus.PENDING,
    )
    db.add(scan)
    await db.flush()
    await db.refresh(scan)

    task = run_antivirus_scan.delay(str(scan.id), path)
    scan.celery_task_id = task.id
    db.add(scan)

    _log_activity(db, request, admin.id, "antivirus.scan_path", f"Triggered antivirus scan on: {path}")

    return {
        "scan_id": str(scan.id),
        "celery_task_id": task.id,
        "status": "pending",
        "path": path,
    }


# ===========================================================================
# GET /scans -- list recent scan results
# ===========================================================================

@router.get("/scans", status_code=status.HTTP_200_OK)
async def list_scans(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Return paginated list of recent antivirus scan results."""
    count_q = select(func.count()).select_from(ScanResult)
    total = (await db.execute(count_q)).scalar() or 0

    query = (
        select(ScanResult)
        .order_by(ScanResult.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    results = (await db.execute(query)).scalars().all()

    return {
        "items": [ScanResultResponse.model_validate(r) for r in results],
        "total": total,
    }


# ===========================================================================
# GET /scans/{id} -- get scan details
# ===========================================================================

@router.get("/scans/{scan_id}", status_code=status.HTTP_200_OK)
async def get_scan(
    scan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Return detailed scan result including quarantine entries."""
    result = await db.execute(select(ScanResult).where(ScanResult.id == scan_id))
    scan = result.scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found.")

    # Fetch quarantine entries for this scan
    qe_result = await db.execute(
        select(QuarantineEntry).where(QuarantineEntry.scan_id == scan_id)
    )
    entries = qe_result.scalars().all()

    return {
        "scan": ScanResultResponse.model_validate(scan),
        "quarantine_entries": [QuarantineEntryResponse.model_validate(e) for e in entries],
    }


# ===========================================================================
# POST /quarantine/{file_id}/restore -- restore quarantined file
# ===========================================================================

@router.post("/quarantine/{file_id}/restore", status_code=status.HTTP_200_OK)
async def restore_quarantined_file(
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Restore a quarantined file back to its original location."""
    result = await db.execute(select(QuarantineEntry).where(QuarantineEntry.id == file_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quarantine entry not found.")

    if entry.restored:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File already restored.")
    if entry.deleted:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="File has been permanently deleted.")

    # Perform the restore on disk
    quarantine_file = Path(entry.quarantine_path)
    original_path = Path(entry.original_path)

    if not quarantine_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quarantined file no longer exists on disk.",
        )

    try:
        original_path.parent.mkdir(parents=True, exist_ok=True)
        quarantine_file.rename(original_path)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore file: {exc}",
        )

    entry.restored = True
    db.add(entry)

    _log_activity(
        db, request, admin.id, "antivirus.restore",
        f"Restored quarantined file: {entry.original_path}",
    )

    return {
        "file_id": str(file_id),
        "original_path": entry.original_path,
        "status": "restored",
    }


# ===========================================================================
# POST /quarantine/{file_id}/delete -- permanently delete quarantined file
# ===========================================================================

@router.post("/quarantine/{file_id}/delete", status_code=status.HTTP_200_OK)
async def delete_quarantined_file(
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Permanently delete a quarantined file from disk."""
    result = await db.execute(select(QuarantineEntry).where(QuarantineEntry.id == file_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quarantine entry not found.")

    if entry.deleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File already deleted.")

    quarantine_file = Path(entry.quarantine_path)
    if quarantine_file.exists():
        try:
            quarantine_file.unlink()
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete file: {exc}",
            )

    entry.deleted = True
    db.add(entry)

    _log_activity(
        db, request, admin.id, "antivirus.delete",
        f"Permanently deleted quarantined file: {entry.original_path} (threat: {entry.threat_name})",
    )

    return {
        "file_id": str(file_id),
        "original_path": entry.original_path,
        "status": "deleted",
    }


# ===========================================================================
# GET /status -- ClamAV service status and DB update time
# ===========================================================================

@router.get("/status", status_code=status.HTTP_200_OK)
async def antivirus_status(
    admin: User = Depends(_admin),
):
    """Return ClamAV installation status, daemon state, and database info."""
    result: dict[str, Any] = {
        "installed": False,
        "daemon_running": False,
        "freshclam_running": False,
        "database_version": None,
        "database_last_update": None,
        "quarantine_dir": str(QUARANTINE_DIR),
        "quarantine_count": 0,
    }

    # Check clamscan installed
    try:
        which = await _run_async(["which", "clamscan"], timeout=5)
        result["installed"] = which.returncode == 0
    except Exception:
        pass

    # Check clamav-daemon running
    try:
        svc = await _run_async(["systemctl", "is-active", "clamav-daemon"], timeout=5)
        result["daemon_running"] = svc.stdout.strip() == "active"
    except Exception:
        pass

    # Check clamav-freshclam running
    try:
        fc_svc = await _run_async(["systemctl", "is-active", "clamav-freshclam"], timeout=5)
        result["freshclam_running"] = fc_svc.stdout.strip() == "active"
    except Exception:
        pass

    # Database version via freshclam --version
    try:
        fc = await _run_async(["freshclam", "--version"], timeout=10)
        if fc.returncode == 0:
            result["database_version"] = fc.stdout.strip()
    except Exception:
        pass

    # Database last update (check main.cvd modification time)
    db_file = Path("/var/lib/clamav/main.cvd")
    if not db_file.exists():
        db_file = Path("/var/lib/clamav/main.cld")
    if db_file.exists():
        mtime = datetime.fromtimestamp(db_file.stat().st_mtime, tz=timezone.utc)
        result["database_last_update"] = mtime.isoformat()

    # Count quarantined files
    if QUARANTINE_DIR.exists():
        try:
            result["quarantine_count"] = sum(1 for _ in QUARANTINE_DIR.iterdir() if _.is_file())
        except OSError:
            pass

    return result


# ===========================================================================
# POST /update -- trigger freshclam DB update
# ===========================================================================

@router.post("/update", status_code=status.HTTP_200_OK)
async def trigger_db_update(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Trigger a ClamAV virus definition database update via freshclam."""
    # Stop freshclam service temporarily so we can run manually
    try:
        await _run_async(["sudo", "systemctl", "stop", "clamav-freshclam"], timeout=10)
    except Exception:
        pass  # May not be running

    try:
        result = await _run_async(["sudo", "freshclam"], timeout=120)
    except subprocess.TimeoutExpired:
        # Restart freshclam service regardless
        await _run_async(["sudo", "systemctl", "start", "clamav-freshclam"], timeout=10)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="freshclam update timed out after 120 seconds.",
        )

    # Restart freshclam service
    try:
        await _run_async(["sudo", "systemctl", "start", "clamav-freshclam"], timeout=10)
    except Exception:
        pass

    _log_activity(db, request, admin.id, "antivirus.update", "Triggered ClamAV database update")

    success = result.returncode == 0
    return {
        "status": "updated" if success else "failed",
        "returncode": result.returncode,
        "stdout": result.stdout.strip() if result.stdout else "",
        "stderr": result.stderr.strip() if result.stderr else "",
    }
