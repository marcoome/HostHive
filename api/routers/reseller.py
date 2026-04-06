"""Reseller router -- /api/v1/reseller (reseller role only).

Strict isolation: resellers can only see/manage users they created
(user.created_by == reseller.id).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

logger = logging.getLogger("hosthive.reseller")
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.database import get_db
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.packages import Package
from api.models.reseller import ResellerBranding, ResellerLimit
from api.models.users import User, UserRole
from api.schemas.reseller import (
    RateLimitResponse,
    RateLimitUpdate,
    RateLimitUsageResponse,
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
_admin = require_role("admin")


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
        select(User)
        .where(User.id == user_id, User.created_by == reseller_id)
        .options(selectinload(User.package), selectinload(User.environment))
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
    base = (
        select(User)
        .where(User.created_by == reseller.id)
        .options(selectinload(User.package), selectinload(User.environment))
    )
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
        return {
            "id": str(reseller.id),
            "user_id": str(reseller.id),
            "logo_url": None,
            "primary_color": "#4f46e5",
            "panel_title": "HostHive",
            "custom_domain": None,
            "hide_hosthive_branding": False,
            "custom_css": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
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
        return {
            "id": str(reseller.id),
            "reseller_id": str(reseller.id),
            "max_users": 0,
            "max_total_disk_mb": 0,
            "max_total_bandwidth_gb": 0,
            "used_users": 0,
            "used_disk_mb": 0,
            "used_bandwidth_gb": 0.0,
            "api_rate_limit_per_minute": 100,
            "api_rate_limit_per_hour": 3000,
            "api_burst_limit": 20,
        }
    return ResellerLimitResponse.model_validate(limits)


# --------------------------------------------------------------------------
# GET /packages -- list packages available to reseller's users
# --------------------------------------------------------------------------
@router.get("/packages", status_code=status.HTTP_200_OK)
async def list_packages(
    scope: str = Query("all", description="all | reseller | global"),
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    """List packages visible to this reseller.

    scope=all     -- global + reseller's own (default)
    scope=reseller -- only packages created by this reseller
    scope=global  -- only admin/global packages (created_by IS NULL)
    """
    from sqlalchemy import or_

    if scope == "reseller":
        q = select(Package).where(Package.created_by == reseller.id)
    elif scope == "global":
        q = select(Package).where(Package.created_by.is_(None))
    else:
        # all: global + own
        q = select(Package).where(
            or_(Package.created_by.is_(None), Package.created_by == reseller.id)
        )

    result = await db.execute(q.order_by(Package.name.asc()))
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
                "created_by": str(p.created_by) if p.created_by else None,
            }
            for p in packages
        ],
        "total": len(packages),
    }


# --------------------------------------------------------------------------
# POST /packages -- reseller creates own package
# --------------------------------------------------------------------------
@router.post("/packages", status_code=status.HTTP_201_CREATED)
async def create_reseller_package(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    """Create a package scoped to this reseller.

    Package limits cannot exceed the reseller's own allocation.
    """
    from api.schemas.packages import PackageCreate

    svc = ResellerService(db)
    limits = await svc.get_limits(reseller.id)
    if limits is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No reseller limits configured. Contact admin.",
        )

    # Validate the body via PackageCreate schema (ignore created_by from body)
    try:
        pkg_data = PackageCreate(**body)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Enforce: package resource limits must not exceed reseller allocation
    if pkg_data.disk_quota_mb > limits.max_total_disk_mb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"disk_quota_mb ({pkg_data.disk_quota_mb}) exceeds your allocation ({limits.max_total_disk_mb} MB).",
        )
    if pkg_data.bandwidth_gb > limits.max_total_bandwidth_gb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"bandwidth_gb ({pkg_data.bandwidth_gb}) exceeds your allocation ({limits.max_total_bandwidth_gb} GB).",
        )

    # Check name uniqueness
    exists = await db.execute(select(Package).where(Package.name == pkg_data.name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Package name already exists.",
        )

    pkg = Package(**pkg_data.model_dump(), created_by=reseller.id)
    db.add(pkg)
    await db.flush()

    _log(db, request, reseller.id, "reseller.create_package",
         f"Reseller created package {pkg_data.name}")

    return {
        "id": str(pkg.id),
        "name": pkg.name,
        "disk_quota_mb": pkg.disk_quota_mb,
        "bandwidth_gb": pkg.bandwidth_gb,
        "max_domains": pkg.max_domains,
        "max_databases": pkg.max_databases,
        "max_email_accounts": pkg.max_email_accounts,
        "max_ftp_accounts": pkg.max_ftp_accounts,
        "max_cron_jobs": pkg.max_cron_jobs,
        "price_monthly": str(pkg.price_monthly),
        "created_by": str(pkg.created_by),
    }


# --------------------------------------------------------------------------
# PUT /packages/{id} -- reseller updates own package
# --------------------------------------------------------------------------
@router.put("/packages/{pkg_id}", status_code=status.HTTP_200_OK)
async def update_reseller_package(
    pkg_id: uuid.UUID,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    """Update a reseller-owned package. Cannot modify global packages."""
    result = await db.execute(
        select(Package).where(Package.id == pkg_id, Package.created_by == reseller.id)
    )
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Package not found or not owned by you.",
        )

    svc = ResellerService(db)
    limits = await svc.get_limits(reseller.id)

    # Only update allowed fields
    allowed = {
        "name", "disk_quota_mb", "bandwidth_gb", "max_domains", "max_databases",
        "max_email_accounts", "max_ftp_accounts", "max_cron_jobs", "price_monthly",
    }
    for field, value in body.items():
        if field not in allowed:
            continue
        # Enforce allocation limits on resource fields
        if field == "disk_quota_mb" and limits and value > limits.max_total_disk_mb:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"disk_quota_mb ({value}) exceeds your allocation ({limits.max_total_disk_mb} MB).",
            )
        if field == "bandwidth_gb" and limits and value > limits.max_total_bandwidth_gb:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"bandwidth_gb ({value}) exceeds your allocation ({limits.max_total_bandwidth_gb} GB).",
            )
        setattr(pkg, field, value)

    db.add(pkg)
    await db.flush()

    _log(db, request, reseller.id, "reseller.update_package",
         f"Reseller updated package {pkg.name}")

    return {
        "id": str(pkg.id),
        "name": pkg.name,
        "disk_quota_mb": pkg.disk_quota_mb,
        "bandwidth_gb": pkg.bandwidth_gb,
        "max_domains": pkg.max_domains,
        "max_databases": pkg.max_databases,
        "max_email_accounts": pkg.max_email_accounts,
        "max_ftp_accounts": pkg.max_ftp_accounts,
        "max_cron_jobs": pkg.max_cron_jobs,
        "price_monthly": str(pkg.price_monthly),
        "created_by": str(pkg.created_by),
    }


# --------------------------------------------------------------------------
# DELETE /packages/{id} -- reseller deletes own package
# --------------------------------------------------------------------------
@router.delete("/packages/{pkg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reseller_package(
    pkg_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    """Delete a reseller-owned package. Cannot delete global packages."""
    result = await db.execute(
        select(Package).where(Package.id == pkg_id, Package.created_by == reseller.id)
    )
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Package not found or not owned by you.",
        )

    # Check if any users are on this package
    user_count = (await db.execute(
        select(func.count()).select_from(User).where(User.package_id == pkg_id)
    )).scalar() or 0
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete package with {user_count} assigned user(s).",
        )

    _log(db, request, reseller.id, "reseller.delete_package",
         f"Reseller deleted package {pkg.name}")

    await db.delete(pkg)
    await db.flush()


# ==========================================================================
# Rate Limit management endpoints
# ==========================================================================

# --------------------------------------------------------------------------
# GET /rate-limits -- current reseller rate limit settings
# --------------------------------------------------------------------------
@router.get("/rate-limits", response_model=RateLimitResponse, status_code=status.HTTP_200_OK)
async def get_rate_limits(
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    """Return the current API rate-limit configuration for this reseller."""
    result = await db.execute(
        select(ResellerLimit).where(ResellerLimit.reseller_id == reseller.id)
    )
    limits = result.scalar_one_or_none()
    if limits is None:
        # Return defaults when no limits row exists
        return RateLimitResponse(
            reseller_id=reseller.id,
            api_rate_limit_per_minute=100,
            api_rate_limit_per_hour=3000,
            api_burst_limit=20,
        )
    return RateLimitResponse(
        reseller_id=limits.reseller_id,
        api_rate_limit_per_minute=limits.api_rate_limit_per_minute,
        api_rate_limit_per_hour=limits.api_rate_limit_per_hour,
        api_burst_limit=limits.api_burst_limit,
    )


# --------------------------------------------------------------------------
# PUT /rate-limits -- update rate limits (admin only)
# --------------------------------------------------------------------------
@router.put("/rate-limits", response_model=RateLimitResponse, status_code=status.HTTP_200_OK)
async def update_rate_limits(
    body: RateLimitUpdate,
    request: Request,
    reseller_id: uuid.UUID = Query(..., description="ID of the reseller whose limits to update"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Update API rate limits for a specific reseller. Admin only."""
    result = await db.execute(
        select(ResellerLimit).where(ResellerLimit.reseller_id == reseller_id)
    )
    limits = result.scalar_one_or_none()
    if limits is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reseller limits not found. Create reseller limits first.",
        )

    update_data = body.model_dump(exclude_unset=True)

    # Validate: per-minute must be <= per-hour
    new_per_minute = update_data.get("api_rate_limit_per_minute", limits.api_rate_limit_per_minute)
    new_per_hour = update_data.get("api_rate_limit_per_hour", limits.api_rate_limit_per_hour)
    if new_per_minute > new_per_hour:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_rate_limit_per_minute cannot exceed api_rate_limit_per_hour.",
        )

    for field, value in update_data.items():
        setattr(limits, field, value)

    db.add(limits)
    await db.flush()

    _log(db, request, admin.id, "admin.update_reseller_rate_limits",
         f"Updated rate limits for reseller {reseller_id}: {list(update_data.keys())}")

    return RateLimitResponse(
        reseller_id=limits.reseller_id,
        api_rate_limit_per_minute=limits.api_rate_limit_per_minute,
        api_rate_limit_per_hour=limits.api_rate_limit_per_hour,
        api_burst_limit=limits.api_burst_limit,
    )


# --------------------------------------------------------------------------
# GET /rate-limits/usage -- current usage stats from Redis
# --------------------------------------------------------------------------
@router.get("/rate-limits/usage", response_model=RateLimitUsageResponse, status_code=status.HTTP_200_OK)
async def get_rate_limit_usage(
    request: Request,
    db: AsyncSession = Depends(get_db),
    reseller: User = Depends(_reseller),
):
    """Return live API rate-limit usage for this reseller (calls this minute/hour)."""
    import time as _time

    result = await db.execute(
        select(ResellerLimit).where(ResellerLimit.reseller_id == reseller.id)
    )
    limits = result.scalar_one_or_none()
    limit_per_minute = limits.api_rate_limit_per_minute if limits else 100
    limit_per_hour = limits.api_rate_limit_per_hour if limits else 3000
    burst_limit = limits.api_burst_limit if limits else 20

    # Read counters from Redis
    redis_client = getattr(request.app.state, "redis", None)
    used_minute = 0
    used_hour = 0
    now = _time.time()

    if redis_client is not None:
        try:
            reseller_id_str = str(reseller.id)
            minute_key = f"ratelimit:reseller:{reseller_id_str}:minute"
            hour_key = f"ratelimit:reseller:{reseller_id_str}:hour"

            # Clean stale entries then count
            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(minute_key, "-inf", now - 60)
            pipe.zcard(minute_key)
            pipe.zremrangebyscore(hour_key, "-inf", now - 3600)
            pipe.zcard(hour_key)
            results = await pipe.execute()

            used_minute = results[1]
            used_hour = results[3]
        except Exception as exc:
            logger.debug("Failed to read rate-limit usage from Redis: %s", exc)

    from datetime import datetime, timezone

    return RateLimitUsageResponse(
        reseller_id=reseller.id,
        api_rate_limit_per_minute=limit_per_minute,
        api_rate_limit_per_hour=limit_per_hour,
        api_burst_limit=burst_limit,
        used_this_minute=used_minute,
        used_this_hour=used_hour,
        remaining_this_minute=max(0, limit_per_minute - used_minute),
        remaining_this_hour=max(0, limit_per_hour - used_hour),
        minute_resets_at=datetime.fromtimestamp(now + 60, tz=timezone.utc),
        hour_resets_at=datetime.fromtimestamp(now + 3600, tz=timezone.utc),
    )
