"""Users router -- /api/v1/users (admin only)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.databases import Database
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.ftp_accounts import FtpAccount
from api.models.users import User, UserRole
from api.schemas.users import UserCreate, UserListResponse, UserResponse, UserUpdate

router = APIRouter()

_admin = require_role("admin")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _get_user_or_404(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=client_ip,
    ))


# --------------------------------------------------------------------------
# GET / -- list users (paginated, filterable)
# --------------------------------------------------------------------------
@router.get("/", response_model=UserListResponse, status_code=status.HTTP_200_OK)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    is_suspended: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    query = select(User)
    count_query = select(func.count()).select_from(User)

    if role is not None:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)
    if is_suspended is not None:
        query = query.where(User.is_suspended == is_suspended)
        count_query = count_query.where(User.is_suspended == is_suspended)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(query.order_by(User.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in results],
        total=total,
        page=(skip // limit) + 1,
        per_page=limit,
    )


# --------------------------------------------------------------------------
# POST / -- create user
# --------------------------------------------------------------------------
@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # Check uniqueness
    exists = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        package_id=body.package_id,
    )
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.create", f"Created user {body.username}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# GET /{id} -- user detail
# --------------------------------------------------------------------------
@router.get("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    return UserResponse.model_validate(await _get_user_or_404(user_id, db))


# --------------------------------------------------------------------------
# PUT /{id} -- update user
# --------------------------------------------------------------------------
@router.put("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.update", f"Updated user {user.username}: {list(update_data.keys())}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete user + all resources
# --------------------------------------------------------------------------
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    agent = request.app.state.agent

    # Clean up remote resources via agent
    domains = (await db.execute(
        select(Domain).where(Domain.user_id == user_id)
    )).scalars().all()
    for domain in domains:
        try:
            await agent.delete_vhost(domain.domain_name)
        except Exception:
            pass  # best-effort cleanup

    databases = (await db.execute(
        select(Database).where(Database.user_id == user_id)
    )).scalars().all()
    for database in databases:
        try:
            await agent.delete_database(database.db_name, database.db_user, database.db_type.value)
        except Exception:
            pass

    emails = (await db.execute(
        select(EmailAccount).where(EmailAccount.user_id == user_id)
    )).scalars().all()
    for email_acct in emails:
        try:
            await agent.delete_mailbox(email_acct.address)
        except Exception:
            pass

    ftp_accounts = (await db.execute(
        select(FtpAccount).where(FtpAccount.user_id == user_id)
    )).scalars().all()
    for ftp in ftp_accounts:
        try:
            await agent.delete_ftp_account(ftp.username)
        except Exception:
            pass

    _log(db, request, admin.id, "users.delete", f"Deleted user {user.username} and all resources")

    await db.delete(user)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/suspend
# --------------------------------------------------------------------------
@router.post("/{user_id}/suspend", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def suspend_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    user.is_suspended = True
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.suspend", f"Suspended user {user.username}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# POST /{id}/unsuspend
# --------------------------------------------------------------------------
@router.post("/{user_id}/unsuspend", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def unsuspend_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    user.is_suspended = False
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.unsuspend", f"Unsuspended user {user.username}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# GET /{id}/stats -- disk, bandwidth, resource usage
# --------------------------------------------------------------------------
@router.get("/{user_id}/stats", status_code=status.HTTP_200_OK)
async def user_stats(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)

    domain_count = (await db.execute(
        select(func.count()).select_from(Domain).where(Domain.user_id == user_id)
    )).scalar() or 0
    db_count = (await db.execute(
        select(func.count()).select_from(Database).where(Database.user_id == user_id)
    )).scalar() or 0
    email_count = (await db.execute(
        select(func.count()).select_from(EmailAccount).where(EmailAccount.user_id == user_id)
    )).scalar() or 0
    ftp_count = (await db.execute(
        select(func.count()).select_from(FtpAccount).where(FtpAccount.user_id == user_id)
    )).scalar() or 0

    return {
        "user_id": str(user_id),
        "username": user.username,
        "domains": domain_count,
        "databases": db_count,
        "email_accounts": email_count,
        "ftp_accounts": ftp_count,
        "package": {
            "name": user.package.name if user.package else None,
            "disk_quota_mb": user.package.disk_quota_mb if user.package else None,
            "bandwidth_gb": user.package.bandwidth_gb if user.package else None,
        },
    }
