"""Databases router -- /api/v1/databases."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password
from api.models.activity_log import ActivityLog
from api.models.databases import Database
from api.models.users import User
from api.schemas.databases import DatabaseCreate, DatabaseResponse

router = APIRouter()


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_db_or_404(
    db_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Database:
    result = await db.execute(select(Database).where(Database.id == db_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database not found.")
    if not _is_admin(current_user) and record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return record


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# GET / -- list databases
# --------------------------------------------------------------------------
@router.get("/", status_code=status.HTTP_200_OK)
async def list_databases(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Database)
    count_query = select(func.count()).select_from(Database)
    if not _is_admin(current_user):
        query = query.where(Database.user_id == current_user.id)
        count_query = count_query.where(Database.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(query.order_by(Database.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [DatabaseResponse.model_validate(d) for d in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create database via agent
# --------------------------------------------------------------------------
@router.post("/", response_model=DatabaseResponse, status_code=status.HTTP_201_CREATED)
async def create_database(
    body: DatabaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Uniqueness check
    exists = await db.execute(select(Database).where(Database.db_name == body.db_name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database name already exists.")

    agent = request.app.state.agent
    try:
        await agent.create_database(
            db_name=body.db_name,
            db_user=body.db_user,
            db_password=body.db_password,
            db_type=body.db_type.value,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error creating database: {exc}",
        )

    record = Database(
        user_id=current_user.id,
        db_name=body.db_name,
        db_user=body.db_user,
        db_password_encrypted=hash_password(body.db_password),
        db_type=body.db_type,
    )
    db.add(record)
    await db.flush()

    _log(db, request, current_user.id, "databases.create", f"Created {body.db_type.value} database {body.db_name}")
    return DatabaseResponse.model_validate(record)


# --------------------------------------------------------------------------
# GET /{id} -- database detail
# --------------------------------------------------------------------------
@router.get("/{db_id}", response_model=DatabaseResponse, status_code=status.HTTP_200_OK)
async def get_database(
    db_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return DatabaseResponse.model_validate(await _get_db_or_404(db_id, db, current_user))


# --------------------------------------------------------------------------
# DELETE /{id} -- delete database via agent
# --------------------------------------------------------------------------
@router.delete("/{db_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_database(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _get_db_or_404(db_id, db, current_user)
    agent = request.app.state.agent

    try:
        await agent.delete_database(record.db_name, record.db_user, record.db_type.value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting database: {exc}",
        )

    _log(db, request, current_user.id, "databases.delete", f"Deleted database {record.db_name}")
    await db.delete(record)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/reset-password -- generate new password, update via agent
# --------------------------------------------------------------------------
@router.post("/{db_id}/reset-password", status_code=status.HTTP_200_OK)
async def reset_database_password(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _get_db_or_404(db_id, db, current_user)
    new_password = secrets.token_urlsafe(24)

    agent = request.app.state.agent
    try:
        await agent._request(
            "POST",
            "/database/reset-password",
            json_body={
                "db_name": record.db_name,
                "db_user": record.db_user,
                "db_password": new_password,
                "db_type": record.db_type.value,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error resetting password: {exc}",
        )

    record.db_password_encrypted = hash_password(new_password)
    db.add(record)
    await db.flush()

    _log(db, request, current_user.id, "databases.reset_password", f"Reset password for {record.db_name}")
    return {"db_name": record.db_name, "new_password": new_password}
