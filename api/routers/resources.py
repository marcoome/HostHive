"""Resource limits router -- /api/v1/resources (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.resources import ResourceLimit
from api.models.users import User
from api.schemas.resources import (
    DomainUsageResponse,
    PHPFPMLimitsResponse,
    PHPFPMLimitsUpdate,
    ResourceOverviewEntry,
    UserLimitsResponse,
    UserLimitsUpdate,
    UserUsageResponse,
)

router = APIRouter()


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# --------------------------------------------------------------------------
# GET /users/{username}/usage -- current resource usage
# --------------------------------------------------------------------------


@router.get("/users/{username}/usage", response_model=UserUsageResponse)
async def get_user_usage(
    username: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/resources/user/{username}/usage")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to get usage"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# PUT /users/{username}/limits -- set CPU/RAM/IO limits
# --------------------------------------------------------------------------


@router.put("/users/{username}/limits", response_model=UserLimitsResponse)
async def set_user_limits(
    username: str,
    body: UserLimitsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    # Call agent to apply cgroup limits
    agent = request.app.state.agent
    resp = await agent.post("/resources/user/limits", json={
        "username": username,
        "cpu_percent": body.cpu_percent,
        "memory_mb": body.memory_mb,
        "io_weight": body.io_weight,
    })
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to set limits"))

    # Persist to DB
    result = await db.execute(
        select(ResourceLimit).where(ResourceLimit.user_id == current_user.id)
    )
    limit_row = result.scalar_one_or_none()
    if limit_row:
        limit_row.cpu_percent = body.cpu_percent
        limit_row.memory_mb = body.memory_mb
        limit_row.io_weight = body.io_weight
    else:
        # Look up user by username to get their id
        from api.models.users import User as UserModel
        user_result = await db.execute(
            select(UserModel).where(UserModel.username == username)
        )
        target_user = user_result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(status_code=404, detail=f"User {username} not found")

        db.add(ResourceLimit(
            user_id=target_user.id,
            cpu_percent=body.cpu_percent,
            memory_mb=body.memory_mb,
            io_weight=body.io_weight,
        ))

    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /users/{username}/limits -- get current limits
# --------------------------------------------------------------------------


@router.get("/users/{username}/limits", response_model=UserLimitsResponse)
async def get_user_limits(
    username: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/resources/user/{username}/limits")
    if not resp.get("ok", True):
        raise HTTPException(status_code=404, detail=resp.get("error", "No limits found"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /domains/{domain}/usage -- domain resource usage
# --------------------------------------------------------------------------


@router.get("/domains/{domain}/usage", response_model=DomainUsageResponse)
async def get_domain_usage(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/resources/domain/{domain}/usage")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to get usage"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# PUT /domains/{domain}/php-limits -- set PHP-FPM pool limits
# --------------------------------------------------------------------------


@router.put("/domains/{domain}/php-limits", response_model=PHPFPMLimitsResponse)
async def set_domain_php_limits(
    domain: str,
    body: PHPFPMLimitsUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.post("/resources/domain/php-limits", json={
        "domain": domain,
        "max_children": body.max_children,
        "memory_limit": body.memory_limit,
        "php_version": body.php_version,
    })
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to set PHP limits"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /overview -- all users resource usage overview
# --------------------------------------------------------------------------


@router.get("/overview", response_model=list[ResourceOverviewEntry])
async def resource_overview(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get("/resources/overview")
    return resp.get("data", [])
