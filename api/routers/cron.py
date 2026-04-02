"""Cron jobs router -- /api/v1/cron."""

from __future__ import annotations

import uuid

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


async def _sync_crontab(
    db: AsyncSession,
    user: User,
    agent,
):
    """Push the full crontab for a user to the agent."""
    jobs = (await db.execute(
        select(CronJob).where(CronJob.user_id == user.id, CronJob.is_active.is_(True))
    )).scalars().all()

    entries = [
        {"schedule": j.schedule, "command": j.command}
        for j in jobs
    ]
    await agent.set_crontab(user.username, entries)


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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error syncing crontab: {exc}",
        )

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
    agent = request.app.state.agent

    try:
        result = await agent._request(
            "POST",
            "/cron/run",
            json_body={"username": current_user.username, "command": job.command},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error running cron job: {exc}",
        )

    _log(db, request, current_user.id, "cron.run_now", f"Manually ran cron job {cron_id}")
    return {"detail": "Job execution triggered.", "result": result}
