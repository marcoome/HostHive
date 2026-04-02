"""Reseller router -- /api/v1/reseller (reseller role only).

Strict isolation: resellers can only see/manage users they created
(user.created_by == reseller.id).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.packages import Package
from api.models.reseller import ResellerBranding, ResellerLimit
from api.models.users import User, UserRole
from api.schemas.reseller import (
    ResellerBrandingCreate,
    ResellerBrandingResponse,
    ResellerBrandingUpdate,
    ResellerLimitResponse,
    ResellerStatsResponse,
    ResellerUserCreate,
    ResellerUserListResponse,
    ResellerUserResponse,
    ResellerUserUpdate,
)
from api.services.reseller_service import ResellerService

router = APIRouter()

_reseller = require_role("reseller", "admin")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _get_reseller_user_or_404(
    user_id: uuid.UUID,
    reseller_id: uuid.UUID,
    db: AsyncSession,
) -> User:
    """Fetch a user that belongs to this reseller, or raise 404."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.created_by == reseller_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


# --------------------------------------------------------------------------
# GET /dashboard -- reseller overview
# --------------------------------------------------------------------------
@router.get("/dashboard", response_model=ResellerStatsResponse, status_code=status.HTTP_200_OK)
async def reseller_dashboard(
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    svc = ResellerService(db)
    stats = await svc.get_reseller_stats(reseller.id)
    return ResellerStatsResponse(**stats)


# --------------------------------------------------------------------------
# GET /users -- list reseller's own users
# --------------------------------------------------------------------------
@router.get("/users", response_model=ResellerUserListResponse, status_code=status.HTTP_200_OK)
async def list_reseller_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    base = select(User).where(User.created_by == reseller.id)
    count_q = select(func.count()).select_from(User).where(User.created_by == reseller.id)

    total = (await db.execute(count_q)).scalar() or 0
    results = (
        await db.execute(base.order_by(User.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return ResellerUserListResponse(
        items=[ResellerUserResponse.model_validate(u) for u in results],
        total=total,
        page=(skip // limit) + 1,
        per_page=limit,
    )


# --------------------------------------------------------------------------
# POST /users -- create user under reseller
# --------------------------------------------------------------------------
@router.post("/users", response_model=ResellerUserResponse, status_code=status.HTTP_201_CREATED)
async def create_reseller_user(
    body: ResellerUserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    svc = ResellerService(db)

    # Check reseller limits
    can_create = await svc.check_reseller_limits(reseller.id, "users")
    if not can_create:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reseller user limit reached.",
        )

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
        role=UserRole.USER,
        package_id=body.package_id,
        created_by=reseller.id,
    )
    db.add(user)
    await db.flush()

    await svc.increment_user_count(reseller.id)

    _log(db, request, reseller.id, "reseller.create_user",
         f"Reseller created user {body.username}")

    return ResellerUserResponse.model_validate(user)


# --------------------------------------------------------------------------
# PUT /users/{id} -- update reseller's user
# --------------------------------------------------------------------------
@router.put("/users/{user_id}", response_model=ResellerUserResponse, status_code=status.HTTP_200_OK)
async def update_reseller_user(
    user_id: uuid.UUID,
    body: ResellerUserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    user = await _get_reseller_user_or_404(user_id, reseller.id, db)
    update_data = body.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(user, field, value)

    db.add(user)
    await db.flush()

    _log(db, request, reseller.id, "reseller.update_user",
         f"Reseller updated user {user.username}: {list(update_data.keys())}")

    return ResellerUserResponse.model_validate(user)


# --------------------------------------------------------------------------
# DELETE /users/{id} -- delete reseller's user
# --------------------------------------------------------------------------
@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reseller_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    user = await _get_reseller_user_or_404(user_id, reseller.id, db)

    _log(db, request, reseller.id, "reseller.delete_user",
         f"Reseller deleted user {user.username}")

    svc = ResellerService(db)
    await svc.decrement_user_count(reseller.id)

    await db.delete(user)
    await db.flush()


# --------------------------------------------------------------------------
# POST /users/{id}/suspend
# --------------------------------------------------------------------------
@router.post("/users/{user_id}/suspend", response_model=ResellerUserResponse, status_code=status.HTTP_200_OK)
async def suspend_reseller_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    user = await _get_reseller_user_or_404(user_id, reseller.id, db)
    user.is_suspended = True
    db.add(user)
    await db.flush()

    _log(db, request, reseller.id, "reseller.suspend_user",
         f"Reseller suspended user {user.username}")

    return ResellerUserResponse.model_validate(user)


# --------------------------------------------------------------------------
# POST /users/{id}/unsuspend
# --------------------------------------------------------------------------
@router.post("/users/{user_id}/unsuspend", response_model=ResellerUserResponse, status_code=status.HTTP_200_OK)
async def unsuspend_reseller_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    user = await _get_reseller_user_or_404(user_id, reseller.id, db)
    user.is_suspended = False
    db.add(user)
    await db.flush()

    _log(db, request, reseller.id, "reseller.unsuspend_user",
         f"Reseller unsuspended user {user.username}")

    return ResellerUserResponse.model_validate(user)


# --------------------------------------------------------------------------
# GET /branding -- get current branding
# --------------------------------------------------------------------------
@router.get("/branding", response_model=ResellerBrandingResponse, status_code=status.HTTP_200_OK)
async def get_branding(
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    svc = ResellerService(db)
    branding = await svc.get_branding(reseller.id)
    if branding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No branding configured. Use PUT to create one.",
        )
    return ResellerBrandingResponse.model_validate(branding)


# --------------------------------------------------------------------------
# PUT /branding -- create or update branding
# --------------------------------------------------------------------------
@router.put("/branding", response_model=ResellerBrandingResponse, status_code=status.HTTP_200_OK)
async def update_branding(
    body: ResellerBrandingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    svc = ResellerService(db)
    data = body.model_dump(exclude_unset=True)
    branding = await svc.apply_branding(reseller.id, data)

    _log(db, request, reseller.id, "reseller.update_branding",
         f"Updated branding: {list(data.keys())}")

    return ResellerBrandingResponse.model_validate(branding)


# --------------------------------------------------------------------------
# GET /limits -- view resource limits vs usage
# --------------------------------------------------------------------------
@router.get("/limits", response_model=ResellerLimitResponse, status_code=status.HTTP_200_OK)
async def get_limits(
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    svc = ResellerService(db)
    limits = await svc.get_limits(reseller.id)
    if limits is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No resource limits configured for this reseller.",
        )
    return ResellerLimitResponse.model_validate(limits)


# --------------------------------------------------------------------------
# GET /packages -- list packages available to reseller's users
# --------------------------------------------------------------------------
@router.get("/packages", status_code=status.HTTP_200_OK)
async def list_packages(
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    result = await db.execute(select(Package).order_by(Package.name.asc()))
    packages = result.scalars().all()
    return {
        "items": [
            {
                "id": str(p.id),
                "name": p.name,
                "disk_quota_mb": p.disk_quota_mb,
                "bandwidth_gb": p.bandwidth_gb,
                "max_domains": p.max_domains,
                "max_databases": p.max_databases,
                "max_email_accounts": p.max_email_accounts,
                "max_ftp_accounts": p.max_ftp_accounts,
                "max_cron_jobs": p.max_cron_jobs,
                "price_monthly": str(p.price_monthly),
            }
            for p in packages
        ],
        "total": len(packages),
    }
