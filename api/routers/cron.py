"""Cron jobs router -- /api/v1/cron."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.cron_jobs import CronJob
from api.models.users import User
from api.schemas.cron import CronJobCreate, CronJobResponse, CronJobUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_cron_or_404(
    cron_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> CronJob:
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cron job not found.")
    if not _is_admin(current_user) and job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return job


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# Direct crontab management (no agent)
# --------------------------------------------------------------------------

def _direct_list_crontab(username: str) -> list[str]:
    """List the current crontab entries for a system user."""
    result = subprocess.run(
        ["crontab", "-l", "-u", username],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        # crontab returns non-zero when no crontab exists
        return []
    return [line for line in result.stdout.splitlines() if line.strip() and not line.startswith("#")]


def _direct_write_crontab(username: str, entries: list[dict[str, str]]) -> None:
    """Write a full crontab for a system user from a list of {schedule, command} dicts."""
    header = "# Managed by HostHive -- do not edit manually\n"
    lines = [header]
    for entry in entries:
        lines.append(f"{entry['schedule']} {entry['command']}\n")

    crontab_content = "".join(lines)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".crontab", delete=False) as tmp:
        tmp.write(crontab_content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["crontab", "-u", username, tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"crontab install failed: {result.stderr.strip()}")
    finally:
        import os
        os.unlink(tmp_path)


def _direct_clear_crontab(username: str) -> None:
    """Remove all cron jobs for a system user."""
    subprocess.run(
        ["crontab", "-r", "-u", username],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _direct_run_command(username: str, command: str) -> str:
    """Execute a command immediately as the given user."""
    result = subprocess.run(
        ["sudo", "-u", username, "bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout
    if result.returncode != 0:
        output += f"\nSTDERR: {result.stderr}" if result.stderr else ""
        output += f"\nExit code: {result.returncode}"
    return output


async def _sync_crontab(
    db: AsyncSession,
    user: User,
    agent,
):
    """Push the full crontab for a user. Tries agent first, falls back to direct."""
    jobs = (await db.execute(
        select(CronJob).where(CronJob.user_id == user.id, CronJob.is_active.is_(True))
    )).scalars().all()

    entries = [
        {"schedule": j.schedule, "command": j.command}
        for j in jobs
    ]

    # Try agent first
    try:
        await agent.set_crontab(user.username, entries)
        return
    except Exception as exc:
        logger.warning("Agent error syncing crontab, falling back to direct: %s", exc)

    # Direct fallback
    loop = asyncio.get_running_loop()
    if entries:
        await loop.run_in_executor(None, _direct_write_crontab, user.username, entries)
    else:
        await loop.run_in_executor(None, _direct_clear_crontab, user.username)


# --------------------------------------------------------------------------
# GET / -- list cron jobs
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_cron_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(CronJob)
    count_query = select(func.count()).select_from(CronJob)
    if not _is_admin(current_user):
        query = query.where(CronJob.user_id == current_user.id)
        count_query = count_query.where(CronJob.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    return {
        "items": [CronJobResponse.model_validate(j) for j in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create cron job
# --------------------------------------------------------------------------
@router.post("", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_cron_job(
    body: CronJobCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = CronJob(
        user_id=current_user.id,
        schedule=body.schedule,
        command=body.command,
    )
    db.add(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception as exc:
        # Non-fatal: job is saved in DB; agent sync will be retried on next change.
        logger.warning("Agent error syncing crontab after create: %s", exc)

    _log(db, request, current_user.id, "cron.create", f"Created cron job: {body.schedule} {body.command[:80]}")
    return CronJobResponse.model_validate(job)


# --------------------------------------------------------------------------
# GET /{id} -- cron job detail
# --------------------------------------------------------------------------
@router.get("/{cron_id}", response_model=CronJobResponse, status_code=status.HTTP_200_OK)
async def get_cron_job(
    cron_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CronJobResponse.model_validate(await _get_cron_or_404(cron_id, db, current_user))


# --------------------------------------------------------------------------
# PUT /{id} -- update cron job
# --------------------------------------------------------------------------
@router.put("/{cron_id}", response_model=CronJobResponse, status_code=status.HTTP_200_OK)
async def update_cron_job(
    cron_id: uuid.UUID,
    body: CronJobUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await _get_cron_or_404(cron_id, db, current_user)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)
    db.add(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception:
        pass  # non-fatal; DB is source of truth

    _log(db, request, current_user.id, "cron.update", f"Updated cron job {cron_id}")
    return CronJobResponse.model_validate(job)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete cron job
# --------------------------------------------------------------------------
@router.delete("/{cron_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(
    cron_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await _get_cron_or_404(cron_id, db, current_user)

    _log(db, request, current_user.id, "cron.delete", f"Deleted cron job {cron_id}")
    await db.delete(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception:
        pass


# --------------------------------------------------------------------------
# POST /{id}/run-now -- immediate execution
# --------------------------------------------------------------------------
@router.post("/{cron_id}/run-now", status_code=status.HTTP_200_OK)
async def run_cron_now(
    cron_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await _get_cron_or_404(cron_id, db, current_user)

    # Try agent first, fall back to direct execution
    result = None
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST",
            "/cron/run",
            json_body={"username": current_user.username, "command": job.command},
        )
    except Exception as exc:
        logger.warning("Agent error running cron job, falling back to direct: %s", exc)

    if result is None:
        try:
            loop = asyncio.get_running_loop()
            output = await loop.run_in_executor(
                None, _direct_run_command, current_user.username, job.command,
            )
            result = {"output": output}
        except Exception as exc:
            logger.error("Direct cron execution also failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to run cron job: {exc}",
            )

    # Update last_run timestamp
    job.last_run = datetime.now(timezone.utc)
    db.add(job)
    await db.flush()

    _log(db, request, current_user.id, "cron.run_now", f"Manually ran cron job {cron_id}")
    return {"detail": "Job execution triggered.", "result": result}
