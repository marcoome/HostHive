"""Docker router -- /api/v1/docker.

Container management: deploy, start/stop/restart, remove, logs, stats.
Docker Compose: deploy and validate.
WebSocket: live container log streaming.

Only available if Docker is installed on the server.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.docker import DockerContainer
from api.models.users import User
from api.schemas.docker import (
    ComposeDeploy,
    ComposeValidate,
    ComposeValidateResponse,
    ContainerActionResponse,
    ContainerDeploy,
    ContainerLogsResponse,
    ContainerResponse,
    ContainerStatsResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_container_or_404(
    container_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> DockerContainer:
    result = await db.execute(
        select(DockerContainer).where(DockerContainer.id == container_id)
    )
    container = result.scalar_one_or_none()
    if container is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found.")
    if not _is_admin(current_user) and container.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return container


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _check_docker_available():
    """Raise 503 if Docker is not installed / accessible."""
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Docker is not available on this server.",
            )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker is not installed on this server.",
        )


# ---------------------------------------------------------------------------
# GET /containers — list user's containers
# ---------------------------------------------------------------------------

@router.get("/containers", status_code=status.HTTP_200_OK)
async def list_containers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _check_docker_available()
    except HTTPException:
        return {"items": [], "total": 0, "docker_available": False}

    query = select(DockerContainer)
    count_query = select(func.count()).select_from(DockerContainer)

    if not _is_admin(current_user):
        query = query.where(DockerContainer.user_id == current_user.id)
        count_query = count_query.where(DockerContainer.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(
            query.order_by(DockerContainer.created_at.desc()).offset(skip).limit(limit)
        )
    ).scalars().all()

    return {
        "items": [ContainerResponse.model_validate(c) for c in results],
        "total": total,
    }


# ---------------------------------------------------------------------------
# POST /containers/deploy — deploy a new container
# ---------------------------------------------------------------------------

@router.post("/containers/deploy", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
async def deploy_container(
    body: ContainerDeploy,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()

    from agent.executors import docker_executor

    try:
        result = docker_executor.deploy_container(
            image=body.image,
            name=body.name,
            ports=body.ports,
            env=body.env,
            volumes=body.volumes,
            user=str(current_user.id),
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    # Store in DB
    container = DockerContainer(
        user_id=current_user.id,
        container_id=result["container_id"],
        name=body.name,
        image=body.image,
        ports_json=json.dumps(body.ports) if body.ports else None,
        env_json=json.dumps(body.env) if body.env else None,
        volumes_json=json.dumps(body.volumes) if body.volumes else None,
        status="running",
        domain=body.domain,
    )
    db.add(container)
    await db.flush()

    # Setup reverse proxy if domain is specified
    if body.domain and body.ports:
        try:
            host_port = list(body.ports.keys())[0]
            docker_executor.setup_nginx_proxy(body.domain, host_port)
        except Exception:
            pass  # non-fatal

    _log(db, request, current_user.id, "docker.deploy", f"Deployed container {body.name} ({body.image})")
    return ContainerResponse.model_validate(container)


# ---------------------------------------------------------------------------
# POST /containers — alias for deploy (frontend compatibility)
# ---------------------------------------------------------------------------

@router.post("/containers", response_model=ContainerResponse, status_code=status.HTTP_201_CREATED)
async def deploy_container_alias(
    body: ContainerDeploy,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await deploy_container(body=body, request=request, db=db, current_user=current_user)


# ---------------------------------------------------------------------------
# POST /containers/{id}/start, /stop, /restart
# ---------------------------------------------------------------------------

@router.post("/containers/{container_id}/start", response_model=ContainerActionResponse)
async def start_container(
    container_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)

    from agent.executors import docker_executor

    try:
        docker_executor.start_container(container.container_id, user=str(current_user.id))
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    container.status = "running"
    db.add(container)
    await db.flush()

    _log(db, request, current_user.id, "docker.start", f"Started container {container.name}")
    return ContainerActionResponse(container_id=container.container_id, action="started", success=True)


@router.post("/containers/{container_id}/stop", response_model=ContainerActionResponse)
async def stop_container(
    container_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)

    from agent.executors import docker_executor

    try:
        docker_executor.stop_container(container.container_id, user=str(current_user.id))
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    container.status = "stopped"
    db.add(container)
    await db.flush()

    _log(db, request, current_user.id, "docker.stop", f"Stopped container {container.name}")
    return ContainerActionResponse(container_id=container.container_id, action="stopped", success=True)


@router.post("/containers/{container_id}/restart", response_model=ContainerActionResponse)
async def restart_container(
    container_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)

    from agent.executors import docker_executor

    try:
        docker_executor.restart_container(container.container_id, user=str(current_user.id))
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    container.status = "running"
    db.add(container)
    await db.flush()

    _log(db, request, current_user.id, "docker.restart", f"Restarted container {container.name}")
    return ContainerActionResponse(container_id=container.container_id, action="restarted", success=True)


# ---------------------------------------------------------------------------
# DELETE /containers/{id} — remove container
# ---------------------------------------------------------------------------

@router.delete("/containers/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_container(
    container_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)

    from agent.executors import docker_executor

    try:
        docker_executor.remove_container(container.container_id, user=str(current_user.id))
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _log(db, request, current_user.id, "docker.remove", f"Removed container {container.name}")
    await db.delete(container)
    await db.flush()


# ---------------------------------------------------------------------------
# GET /containers/{id}/logs — container logs
# ---------------------------------------------------------------------------

@router.get("/containers/{container_id}/logs", response_model=ContainerLogsResponse)
async def container_logs(
    container_id: uuid.UUID,
    lines: int = Query(200, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)

    from agent.executors import docker_executor

    try:
        logs = docker_executor.get_container_logs(
            container.container_id, lines=lines, user=str(current_user.id),
        )
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return ContainerLogsResponse(container_id=container.container_id, logs=logs)


# ---------------------------------------------------------------------------
# GET /containers/{id}/stats — container resource usage
# ---------------------------------------------------------------------------

@router.get("/containers/{container_id}/stats", response_model=ContainerStatsResponse)
async def container_stats(
    container_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)

    from agent.executors import docker_executor

    try:
        stats = docker_executor.get_container_stats(
            container.container_id, user=str(current_user.id),
        )
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return ContainerStatsResponse(
        container_id=container.container_id,
        cpu_percent=stats.get("CPUPerc"),
        memory_usage=stats.get("MemUsage"),
        memory_limit=stats.get("MemLimit") if "MemLimit" in stats else None,
        memory_percent=stats.get("MemPerc"),
        network_io=stats.get("NetIO"),
        block_io=stats.get("BlockIO"),
    )


# ---------------------------------------------------------------------------
# POST /compose/deploy — deploy from docker-compose.yml
# ---------------------------------------------------------------------------

@router.post("/compose/deploy", status_code=status.HTTP_201_CREATED)
async def compose_deploy(
    body: ComposeDeploy,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_docker_available()

    from agent.executors import docker_executor

    try:
        containers = docker_executor.deploy_compose(
            compose_yaml=body.compose_yaml,
            project_name=body.project_name,
            user=str(current_user.id),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _log(
        db, request, current_user.id,
        "docker.compose_deploy",
        f"Deployed compose project {body.project_name}",
    )
    return {"project_name": body.project_name, "containers": containers}


# ---------------------------------------------------------------------------
# POST /compose/validate — validate compose file
# ---------------------------------------------------------------------------

@router.post("/compose/validate", response_model=ComposeValidateResponse)
async def compose_validate(body: ComposeValidate):
    _check_docker_available()

    from agent.executors import docker_executor

    errors = docker_executor.validate_compose(body.compose_yaml)
    return ComposeValidateResponse(valid=len(errors) == 0, errors=errors)


# ---------------------------------------------------------------------------
# WebSocket /ws/containers/{id}/logs — live log streaming
# ---------------------------------------------------------------------------

@router.websocket("/ws/containers/{container_id}/logs")
async def ws_container_logs(
    websocket: WebSocket,
    container_id: uuid.UUID,
):
    """Stream live container logs over WebSocket.

    Authentication is done via query param ``token`` (JWT access token).
    """
    await websocket.accept()

    # Authenticate via query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    from api.core.security import verify_token
    try:
        payload = verify_token(token, expected_type="access")
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")

    # Look up the container in DB
    from api.core.database import async_session_factory
    async with async_session_factory() as db:
        result = await db.execute(
            select(DockerContainer).where(DockerContainer.id == container_id)
        )
        container = result.scalar_one_or_none()
        if container is None:
            await websocket.close(code=4004, reason="Container not found")
            return

        # Check ownership (admins can see all)
        if user_id and str(container.user_id) != user_id:
            # Check if admin
            from api.models.users import User
            user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
            user = user_result.scalar_one_or_none()
            if not user or user.role.value != "admin":
                await websocket.close(code=4003, reason="Access denied")
                return

        docker_container_id = container.container_id

    # Stream logs using docker logs --follow via subprocess
    import subprocess
    process = subprocess.Popen(
        ["docker", "logs", "--follow", "--tail", "50", docker_container_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, process.stdout.readline)
            if not line:
                break
            await websocket.send_text(line.rstrip("\n"))
    except WebSocketDisconnect:
        pass
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
