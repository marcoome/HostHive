"""Packages router -- /api/v1/packages (admin only)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.packages import Package, PackageType
from api.models.reseller import ResellerLimit
from api.models.users import User, UserRole
from api.schemas.packages import PackageCreate, PackageResponse, PackageUpdate
from api.schemas.users import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_admin = require_role("admin")

SHELL_PATHS = {
    "nologin": "/usr/sbin/nologin",
    "bash": "/bin/bash",
    "sh": "/bin/sh",
    "rbash": "/bin/rbash",
}


async def _apply_shell_for_user(username: str, shell_access: bool, shell_type: str) -> None:
    """Set the login shell for a system user via usermod."""
    shell = SHELL_PATHS.get(shell_type, "/usr/sbin/nologin") if shell_access else "/usr/sbin/nologin"
    try:
        proc = await asyncio.create_subprocess_exec(
            "usermod", "-s", shell, username,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            logger.warning("usermod failed for %s (rc=%s)", username, proc.returncode)
    except Exception as exc:
        logger.warning("Failed to set shell for %s: %s", username, exc)


async def _get_package_or_404(pkg_id: uuid.UUID, db: AsyncSession) -> Package:
    result = await db.execute(select(Package).where(Package.id == pkg_id))
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found.")
    return pkg


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def sync_reseller_limit_from_package(
    db: AsyncSession,
    reseller_id: uuid.UUID,
    pkg: Package,
) -> ResellerLimit:
    """Create or update a reseller's ResellerLimit row from a reseller-type package.

    Called whenever a reseller-type package is assigned to a reseller account
    (on create or update). Resource caps come from the package; live ``used_*``
    counters are preserved.
    """
    if pkg.package_type != PackageType.RESELLER:
        raise ValueError("sync_reseller_limit_from_package requires a reseller-type package")

    result = await db.execute(
        select(ResellerLimit).where(ResellerLimit.reseller_id == reseller_id)
    )
    limits = result.scalar_one_or_none()

    # Convert GB -> MB for the disk column (ResellerLimit stores MB).
    new_max_disk_mb = int(pkg.max_total_disk_gb) * 1024

    if limits is None:
        limits = ResellerLimit(
            reseller_id=reseller_id,
            max_users=pkg.max_users,
            max_total_disk_mb=new_max_disk_mb,
            max_total_bandwidth_gb=pkg.max_total_bandwidth_gb,
            used_users=0,
            used_disk_mb=0,
            used_bandwidth_gb=0.0,
        )
    else:
        limits.max_users = pkg.max_users
        limits.max_total_disk_mb = new_max_disk_mb
        limits.max_total_bandwidth_gb = pkg.max_total_bandwidth_gb

    db.add(limits)
    await db.flush()
    return limits


# --------------------------------------------------------------------------
# GET / -- list packages
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_packages(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type: PackageType | None = Query(
        None,
        description="Filter by package_type: 'user' or 'reseller'",
    ),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    base_q = select(Package)
    count_q = select(func.count()).select_from(Package)
    if type is not None:
        base_q = base_q.where(Package.package_type == type)
        count_q = count_q.where(Package.package_type == type)

    total = (await db.execute(count_q)).scalar() or 0
    results = (
        await db.execute(base_q.order_by(Package.name).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [PackageResponse.model_validate(p) for p in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create package
# --------------------------------------------------------------------------
@router.post("", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    body: PackageCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    exists = await db.execute(select(Package).where(Package.name == body.name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Package name already exists.")

    pkg = Package(**body.model_dump())
    db.add(pkg)
    await db.flush()

    _log(
        db,
        request,
        admin.id,
        "packages.create",
        f"Created {pkg.package_type.value} package {body.name}",
    )
    return PackageResponse.model_validate(pkg)


# --------------------------------------------------------------------------
# GET /{id} -- package detail
# --------------------------------------------------------------------------
@router.get("/{pkg_id}", response_model=PackageResponse, status_code=status.HTTP_200_OK)
async def get_package(
    pkg_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    return PackageResponse.model_validate(await _get_package_or_404(pkg_id, db))


# --------------------------------------------------------------------------
# PUT /{id} -- update package
# --------------------------------------------------------------------------
@router.put("/{pkg_id}", response_model=PackageResponse, status_code=status.HTTP_200_OK)
async def update_package(
    pkg_id: uuid.UUID,
    body: PackageUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    pkg = await _get_package_or_404(pkg_id, db)
    update_data = body.model_dump(exclude_unset=True)

    # --------------------------------------------------------------
    # package_type change -- admin only, and only when no users are
    # currently assigned to this package. Changing the type while
    # users are attached would silently break the role/type invariant
    # enforced in routers/users.py::_resolve_and_validate_package.
    # --------------------------------------------------------------
    new_type = update_data.pop("package_type", None)
    if new_type is not None and new_type != pkg.package_type:
        assignee_count = (await db.execute(
            select(func.count()).select_from(User).where(User.package_id == pkg_id)
        )).scalar() or 0
        if assignee_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot change package_type: {assignee_count} user(s) are "
                    f"currently assigned to '{pkg.name}'. Reassign or remove "
                    f"them first."
                ),
            )
        pkg.package_type = new_type

    # After a possible type switch, re-evaluate "effective" type for the
    # field-stripping pass below.
    effective_type = pkg.package_type

    # Strip out reseller-only fields when this is a user-type package, and
    # vice versa, to keep the two domains cleanly separated.
    if effective_type == PackageType.USER:
        for f in ("max_users", "max_total_disk_gb", "max_total_bandwidth_gb", "max_total_domains"):
            update_data.pop(f, None)

    shell_changed = "shell_access" in update_data or "shell_type" in update_data
    reseller_alloc_changed = effective_type == PackageType.RESELLER and any(
        k in update_data
        for k in ("max_users", "max_total_disk_gb", "max_total_bandwidth_gb", "max_total_domains")
    )

    for field, value in update_data.items():
        setattr(pkg, field, value)
    db.add(pkg)
    await db.flush()

    # If shell settings changed, apply to all users on this package
    if shell_changed:
        users_result = await db.execute(
            select(User).where(User.package_id == pkg_id)
        )
        for user in users_result.scalars().all():
            await _apply_shell_for_user(user.username, pkg.shell_access, pkg.shell_type)

    # If a reseller-package's allocation changed, propagate the new caps to
    # every reseller currently assigned to it.
    if reseller_alloc_changed:
        resellers_result = await db.execute(
            select(User).where(
                User.package_id == pkg_id,
                User.role == UserRole.RESELLER,
            )
        )
        for reseller in resellers_result.scalars().all():
            await sync_reseller_limit_from_package(db, reseller.id, pkg)

    _log(db, request, admin.id, "packages.update", f"Updated package {pkg.name}")
    return PackageResponse.model_validate(pkg)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete package
# --------------------------------------------------------------------------
@router.delete("/{pkg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(
    pkg_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    pkg = await _get_package_or_404(pkg_id, db)

    # Check if any users are on this package
    user_count = (await db.execute(
        select(func.count()).select_from(User).where(User.package_id == pkg_id)
    )).scalar() or 0
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete package with {user_count} assigned user(s).",
        )

    _log(db, request, admin.id, "packages.delete", f"Deleted package {pkg.name}")
    await db.delete(pkg)
    await db.flush()


# --------------------------------------------------------------------------
# GET /{id}/users -- users on this package
# --------------------------------------------------------------------------
@router.get("/{pkg_id}/users", status_code=status.HTTP_200_OK)
async def package_users(
    pkg_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    await _get_package_or_404(pkg_id, db)  # ensure exists

    count_query = select(func.count()).select_from(User).where(User.package_id == pkg_id)
    total = (await db.execute(count_query)).scalar() or 0

    results = (await db.execute(
        select(User)
        .where(User.package_id == pkg_id)
        .options(selectinload(User.package), selectinload(User.environment))
        .offset(skip).limit(limit)
    )).scalars().all()

    return {
        "items": [UserResponse.model_validate(u) for u in results],
        "total": total,
    }
