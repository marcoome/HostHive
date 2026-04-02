"""Environments router -- /api/v1/environments

Manages Docker-based user isolation: create/destroy environments,
switch webservers, switch DB versions, manage PHP versions, toggle
Redis/Memcached, update resource limits, and view usage.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, require_role
from api.models.activity_log import ActivityLog
from api.models.packages import Package
from api.models.user_environment import UserEnvironment
from api.models.users import User
from api.schemas.environments import (
    CacheToggle,
    ContainerListResponse,
    DbSwitch,
    EnvironmentCreate,
    EnvironmentResponse,
    OperationResponse,
    PhpVersionAdd,
    PhpVersionRemove,
    ResourceUpdate,
    ResourceUsageResponse,
    WebserverSwitch,
)

router = APIRouter()

_admin = require_role("admin")
_admin_or_reseller = require_role("admin", "reseller")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_env_or_404(user_id: uuid.UUID, db: AsyncSession) -> UserEnvironment:
    result = await db.execute(
        select(UserEnvironment).where(UserEnvironment.user_id == user_id),
    )
    env = result.scalar_one_or_none()
    if env is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User environment not found.",
        )
    return env


async def _get_user_or_404(user_id: uuid.UUID, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return user


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _get_agent(request: Request):
    """Return the agent client from app state."""
    return request.app.state.agent


# ---------------------------------------------------------------------------
# GET / -- list all environments (admin)
# ---------------------------------------------------------------------------

@router.get("/", status_code=status.HTTP_200_OK)
async def list_environments(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    count_q = select(func.count()).select_from(UserEnvironment)
    total = (await db.execute(count_q)).scalar() or 0

    results = (
        await db.execute(
            select(UserEnvironment)
            .order_by(UserEnvironment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
    ).scalars().all()

    return {
        "items": [EnvironmentResponse.model_validate(e) for e in results],
        "total": total,
    }


# ---------------------------------------------------------------------------
# GET /{user_id} -- get environment details
# ---------------------------------------------------------------------------

@router.get("/{user_id}", response_model=EnvironmentResponse, status_code=status.HTTP_200_OK)
async def get_environment(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Users can see their own environment; admins can see any
    if current_user.role.value not in ("admin", "reseller") and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
    env = await _get_env_or_404(user_id, db)
    return EnvironmentResponse.model_validate(env)


# ---------------------------------------------------------------------------
# POST /{user_id}/create -- create environment (admin)
# ---------------------------------------------------------------------------

@router.post("/{user_id}/create", response_model=OperationResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    user_id: uuid.UUID,
    body: EnvironmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)

    # Check if environment already exists
    existing = await db.execute(
        select(UserEnvironment).where(UserEnvironment.user_id == user_id),
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Environment already exists for this user.",
        )

    # Build plan dict from user's package + overrides from body
    plan = {
        "cpu_cores": 1.0,
        "ram_mb": 1024,
        "io_bandwidth_mbps": 100,
        "default_webserver": body.webserver,
        "default_db_version": body.db_version,
        "redis_enabled": body.redis_enabled,
        "redis_memory_mb": body.redis_memory_mb,
        "memcached_enabled": body.memcached_enabled,
        "memcached_memory_mb": body.memcached_memory_mb,
    }

    # Override from package if user has one
    if user.package:
        pkg = user.package
        plan["cpu_cores"] = getattr(pkg, "cpu_cores", 1.0)
        plan["ram_mb"] = getattr(pkg, "ram_mb", 1024)
        plan["io_bandwidth_mbps"] = getattr(pkg, "io_bandwidth_mbps", 100)
        if not body.webserver:
            plan["default_webserver"] = getattr(pkg, "default_webserver", "nginx")
        if not body.db_version:
            plan["default_db_version"] = getattr(pkg, "default_db_version", "mariadb11")
        plan["redis_enabled"] = body.redis_enabled or getattr(pkg, "redis_enabled", False)
        plan["memcached_enabled"] = body.memcached_enabled or getattr(pkg, "memcached_enabled", False)

    # Call the agent to create the Docker environment
    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/create", json={
        "username": user.username,
        "plan": plan,
    })

    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to create environment"),
        )

    env_data = result.get("data", {})

    # Persist to database
    env = UserEnvironment(
        user_id=user_id,
        docker_network=env_data.get("network", f"hosthive_net_{user.username}"),
        webserver=env_data.get("webserver", body.webserver),
        db_version=env_data.get("db_version", body.db_version),
        php_versions=env_data.get("php_versions", body.php_versions),
        redis_enabled=body.redis_enabled,
        memcached_enabled=body.memcached_enabled,
        container_ids=env_data.get("container_ids", {}),
        cpu_limit=plan["cpu_cores"],
        memory_limit_mb=plan["ram_mb"],
        status="active",
    )
    db.add(env)
    await db.flush()

    _log(db, request, admin.id, "environment.create", f"Created environment for user {user.username}")

    return OperationResponse(ok=True, detail="Environment created", data=env_data)


# ---------------------------------------------------------------------------
# DELETE /{user_id} -- destroy environment (admin)
# ---------------------------------------------------------------------------

@router.delete("/{user_id}", response_model=OperationResponse, status_code=status.HTTP_200_OK)
async def destroy_environment(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/destroy", json={
        "username": user.username,
    })

    env.status = "destroyed"
    await db.delete(env)
    await db.flush()

    _log(db, request, admin.id, "environment.destroy", f"Destroyed environment for user {user.username}")

    return OperationResponse(ok=True, detail="Environment destroyed", data=result.get("data"))


# ---------------------------------------------------------------------------
# POST /{user_id}/switch-webserver
# ---------------------------------------------------------------------------

@router.post("/{user_id}/switch-webserver", response_model=OperationResponse)
async def switch_webserver(
    user_id: uuid.UUID,
    body: WebserverSwitch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/switch-webserver", json={
        "username": user.username,
        "webserver": body.webserver,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Switch failed"))

    env.webserver = body.webserver
    data = result.get("data", {})
    if "container_id" in data:
        env.container_ids = {**env.container_ids, "web": data["container_id"]}
    await db.flush()

    _log(db, request, admin.id, "environment.switch_webserver",
         f"Switched {user.username} webserver to {body.webserver}")

    return OperationResponse(ok=True, detail=f"Webserver switched to {body.webserver}", data=data)


# ---------------------------------------------------------------------------
# POST /{user_id}/switch-db
# ---------------------------------------------------------------------------

@router.post("/{user_id}/switch-db", response_model=OperationResponse)
async def switch_db(
    user_id: uuid.UUID,
    body: DbSwitch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/switch-db", json={
        "username": user.username,
        "version": body.db_version,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Switch failed"))

    env.db_version = body.db_version
    data = result.get("data", {})
    if "container_id" in data:
        env.container_ids = {**env.container_ids, "db": data["container_id"]}
    await db.flush()

    _log(db, request, admin.id, "environment.switch_db",
         f"Switched {user.username} DB to {body.db_version}")

    return OperationResponse(ok=True, detail=f"DB switched to {body.db_version}", data=data)


# ---------------------------------------------------------------------------
# POST /{user_id}/add-php
# ---------------------------------------------------------------------------

@router.post("/{user_id}/add-php", response_model=OperationResponse)
async def add_php(
    user_id: uuid.UUID,
    body: PhpVersionAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/add-php", json={
        "username": user.username,
        "version": body.version,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Add PHP failed"))

    # Update php_versions list
    versions = list(env.php_versions or [])
    if body.version not in versions:
        versions.append(body.version)
        env.php_versions = versions
    data = result.get("data", {})
    if "container_id" in data:
        key = f"php{body.version.replace('.', '')}"
        env.container_ids = {**env.container_ids, key: data["container_id"]}
    await db.flush()

    _log(db, request, admin.id, "environment.add_php",
         f"Added PHP {body.version} for {user.username}")

    return OperationResponse(ok=True, detail=f"PHP {body.version} added", data=data)


# ---------------------------------------------------------------------------
# POST /{user_id}/remove-php
# ---------------------------------------------------------------------------

@router.post("/{user_id}/remove-php", response_model=OperationResponse)
async def remove_php(
    user_id: uuid.UUID,
    body: PhpVersionRemove,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    versions = list(env.php_versions or [])
    if body.version not in versions:
        raise HTTPException(status_code=400, detail=f"PHP {body.version} not installed")
    if len(versions) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last PHP version")

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/remove-php", json={
        "username": user.username,
        "version": body.version,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Remove PHP failed"))

    versions.remove(body.version)
    env.php_versions = versions
    key = f"php{body.version.replace('.', '')}"
    container_ids = dict(env.container_ids or {})
    container_ids.pop(key, None)
    env.container_ids = container_ids
    await db.flush()

    _log(db, request, admin.id, "environment.remove_php",
         f"Removed PHP {body.version} for {user.username}")

    return OperationResponse(ok=True, detail=f"PHP {body.version} removed", data=result.get("data"))


# ---------------------------------------------------------------------------
# POST /{user_id}/toggle-redis
# ---------------------------------------------------------------------------

@router.post("/{user_id}/toggle-redis", response_model=OperationResponse)
async def toggle_redis(
    user_id: uuid.UUID,
    body: CacheToggle,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/toggle-redis", json={
        "username": user.username,
        "enable": body.enable,
        "memory_mb": body.memory_mb,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Toggle failed"))

    env.redis_enabled = body.enable
    data = result.get("data", {})
    container_ids = dict(env.container_ids or {})
    if body.enable and "container_id" in data:
        container_ids["redis"] = data["container_id"]
    elif not body.enable:
        container_ids.pop("redis", None)
    env.container_ids = container_ids
    await db.flush()

    action = "enabled" if body.enable else "disabled"
    _log(db, request, admin.id, "environment.toggle_redis",
         f"Redis {action} for {user.username}")

    return OperationResponse(ok=True, detail=f"Redis {action}", data=data)


# ---------------------------------------------------------------------------
# POST /{user_id}/toggle-memcached
# ---------------------------------------------------------------------------

@router.post("/{user_id}/toggle-memcached", response_model=OperationResponse)
async def toggle_memcached(
    user_id: uuid.UUID,
    body: CacheToggle,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/toggle-memcached", json={
        "username": user.username,
        "enable": body.enable,
        "memory_mb": body.memory_mb,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Toggle failed"))

    env.memcached_enabled = body.enable
    data = result.get("data", {})
    container_ids = dict(env.container_ids or {})
    if body.enable and "container_id" in data:
        container_ids["memcached"] = data["container_id"]
    elif not body.enable:
        container_ids.pop("memcached", None)
    env.container_ids = container_ids
    await db.flush()

    action = "enabled" if body.enable else "disabled"
    _log(db, request, admin.id, "environment.toggle_memcached",
         f"Memcached {action} for {user.username}")

    return OperationResponse(ok=True, detail=f"Memcached {action}", data=data)


# ---------------------------------------------------------------------------
# PUT /{user_id}/resources -- update resource limits
# ---------------------------------------------------------------------------

@router.put("/{user_id}/resources", response_model=OperationResponse)
async def update_resources(
    user_id: uuid.UUID,
    body: ResourceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    env = await _get_env_or_404(user_id, db)

    agent = _get_agent(request)
    result = await agent.post("/docker-isolation/update-resources", json={
        "username": user.username,
        "cpu": body.cpu_cores,
        "memory_mb": body.ram_mb,
        "io_bps": body.io_bandwidth_mbps * 1024 * 1024,
    })

    env.cpu_limit = body.cpu_cores
    env.memory_limit_mb = body.ram_mb
    await db.flush()

    _log(db, request, admin.id, "environment.update_resources",
         f"Updated resources for {user.username}: cpu={body.cpu_cores}, ram={body.ram_mb}MB")

    return OperationResponse(ok=True, detail="Resource limits updated", data=result.get("data"))


# ---------------------------------------------------------------------------
# GET /{user_id}/usage -- current resource usage
# ---------------------------------------------------------------------------

@router.get("/{user_id}/usage", response_model=ResourceUsageResponse)
async def get_usage(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value not in ("admin", "reseller") and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    user = await _get_user_or_404(user_id, db)
    agent = _get_agent(request)
    result = await agent.get(f"/docker-isolation/usage/{user.username}")
    data = result.get("data", {})

    return ResourceUsageResponse(
        username=user.username,
        total_cpu_percent=data.get("total_cpu_percent", 0.0),
        containers=data.get("containers", []),
        container_count=data.get("container_count", 0),
    )


# ---------------------------------------------------------------------------
# GET /{user_id}/containers -- list containers with status
# ---------------------------------------------------------------------------

@router.get("/{user_id}/containers", response_model=ContainerListResponse)
async def get_containers(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value not in ("admin", "reseller") and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    user = await _get_user_or_404(user_id, db)
    agent = _get_agent(request)
    result = await agent.get(f"/docker-isolation/containers/{user.username}")
    containers = result.get("data", [])

    return ContainerListResponse(
        username=user.username,
        containers=containers if isinstance(containers, list) else [],
        total=len(containers) if isinstance(containers, list) else 0,
    )
