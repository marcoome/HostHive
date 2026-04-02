"""Packages router -- /api/v1/packages (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.packages import Package
from api.models.users import User
from api.schemas.packages import PackageCreate, PackageResponse, PackageUpdate
from api.schemas.users import UserResponse

router = APIRouter()

_admin = require_role("admin")


async def _get_package_or_404(pkg_id: uuid.UUID, db: AsyncSession) -> Package:
    result = await db.execute(select(Package).where(Package.id == pkg_id))
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found.")
    return pkg


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# GET / -- list packages
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_packages(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    count_query = select(func.count()).select_from(Package)
    total = (await db.execute(count_query)).scalar() or 0

    results = (await db.execute(
        select(Package).order_by(Package.name).offset(skip).limit(limit)
    )).scalars().all()

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

    _log(db, request, admin.id, "packages.create", f"Created package {body.name}")
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
    for field, value in update_data.items():
        setattr(pkg, field, value)
    db.add(pkg)
    await db.flush()

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
