"""Docker router -- /api/v1/docker.

Container management: deploy, start/stop/restart, remove, logs, stats.
Docker Compose: deploy and validate.
WebSocket: live container log streaming.

This router talks to Docker DIRECTLY via the local `docker` CLI through
``subprocess`` calls executed in a thread-pool (via
``asyncio.run_in_executor``). It does NOT proxy through any agent on
port 7080.

Only available if Docker is installed on the server.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Dict, List, Optional

import yaml
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
# Subprocess helpers (run docker CLI in a thread-pool executor)
# ---------------------------------------------------------------------------

# Disallow shell metacharacters in identifiers we hand to ``docker``.
_SAFE_IMAGE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-:/@"
)
_SAFE_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _validate_image(image: str) -> None:
    if not image or any(c not in _SAFE_IMAGE_CHARS for c in image):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image reference: {image!r}",
        )


def _validate_name(name: str) -> None:
    if not name or any(c not in _SAFE_NAME_CHARS for c in name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid container name: {name!r}",
        )


def _validate_container_id(cid: str) -> None:
    # Docker container IDs are hex; names follow same rules as _SAFE_NAME_CHARS.
    if not cid or any(c not in _SAFE_NAME_CHARS for c in cid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid container id: {cid!r}",
        )


def _run_sync(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Synchronous subprocess wrapper. Always called via run_in_executor."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def _run_docker(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a docker CLI command in a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run_sync(cmd, timeout))


# ---------------------------------------------------------------------------
# Misc helpers
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


async def _check_docker_available():
    """Raise 503 if Docker is not installed / accessible."""
    if shutil.which("docker") is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker is not installed on this server.",
        )
    try:
        r = await _run_docker(["docker", "info"], timeout=10)
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker did not respond in time.",
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker is not installed on this server.",
        )
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker is not available on this server.",
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
        await _check_docker_available()
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
    await _check_docker_available()

    _validate_image(body.image)
    _validate_name(body.name)

    cmd: List[str] = ["docker", "run", "-d", "--name", body.name, "--restart", "unless-stopped"]

    # Port mappings: {host_port: container_port}
    if body.ports:
        for host_port, container_port in body.ports.items():
            host_port_s = str(host_port).strip()
            container_port_s = str(container_port).strip()
            if not host_port_s.isdigit() or not container_port_s.replace("/tcp", "").replace("/udp", "").isdigit():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid port mapping {host_port_s}:{container_port_s}",
                )
            cmd.extend(["-p", f"{host_port_s}:{container_port_s}"])

    # Environment variables: {KEY: VALUE}
    if body.env:
        for key, value in body.env.items():
            if not key or "=" in key or "\n" in key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid env var name: {key!r}",
                )
            cmd.extend(["-e", f"{key}={value}"])

    # Volume mounts: {host_path: container_path}
    if body.volumes:
        for host_path, container_path in body.volumes.items():
            if not host_path or not container_path or "\n" in host_path or "\n" in container_path:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid volume mount.",
                )
            cmd.extend(["-v", f"{host_path}:{container_path}"])

    cmd.append(body.image)

    r = await _run_docker(cmd, timeout=180)
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker run failed: {r.stderr.strip() or r.stdout.strip()}",
        )

    container_cli_id = r.stdout.strip()
    if not container_cli_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="docker run did not return a container id.",
        )

    # Store in DB
    container = DockerContainer(
        user_id=current_user.id,
        container_id=container_cli_id,
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
    await _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)
    _validate_container_id(container.container_id)

    r = await _run_docker(["docker", "start", container.container_id], timeout=60)
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker start failed: {r.stderr.strip() or r.stdout.strip()}",
        )

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
    await _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)
    _validate_container_id(container.container_id)

    r = await _run_docker(["docker", "stop", container.container_id], timeout=60)
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker stop failed: {r.stderr.strip() or r.stdout.strip()}",
        )

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
    await _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)
    _validate_container_id(container.container_id)

    r = await _run_docker(["docker", "restart", container.container_id], timeout=120)
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker restart failed: {r.stderr.strip() or r.stdout.strip()}",
        )

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
    await _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)
    _validate_container_id(container.container_id)

    # Force remove (stops the container if running).
    r = await _run_docker(["docker", "rm", "-f", container.container_id], timeout=60)
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker rm failed: {r.stderr.strip() or r.stdout.strip()}",
        )

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
    await _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)
    _validate_container_id(container.container_id)

    r = await _run_docker(
        ["docker", "logs", "--tail", str(lines), container.container_id],
        timeout=30,
    )
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker logs failed: {r.stderr.strip()}",
        )

    # Combine stdout and stderr (docker writes container logs to both).
    logs = (r.stdout or "") + (r.stderr or "")
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
    await _check_docker_available()
    container = await _get_container_or_404(container_id, db, current_user)
    _validate_container_id(container.container_id)

    # --no-stream avoids the long-running streaming mode.
    r = await _run_docker(
        [
            "docker", "stats", "--no-stream", "--format",
            "{{json .}}",
            container.container_id,
        ],
        timeout=30,
    )
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docker stats failed: {r.stderr.strip() or r.stdout.strip()}",
        )

    raw = (r.stdout or "").strip().splitlines()
    stats: Dict[str, Any] = {}
    if raw:
        try:
            stats = json.loads(raw[0])
        except json.JSONDecodeError:
            stats = {}

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
# Compose helpers
# ---------------------------------------------------------------------------

async def _compose_command_prefix() -> List[str]:
    """Return ``docker compose`` if available, falling back to ``docker-compose``."""
    r = await _run_docker(["docker", "compose", "version"], timeout=10)
    if r.returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose") is not None:
        return ["docker-compose"]
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Docker Compose is not installed on this server.",
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
    await _check_docker_available()

    # Validate YAML up front so we get a clean 400 instead of opaque CLI errors.
    try:
        yaml.safe_load(body.compose_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid compose YAML: {exc}",
        )

    compose_prefix = await _compose_command_prefix()

    # Write compose YAML to a temp file owned by this process.
    tmpdir = tempfile.mkdtemp(prefix=f"compose-{body.project_name}-")
    compose_path = os.path.join(tmpdir, "docker-compose.yml")
    try:
        with open(compose_path, "w", encoding="utf-8") as f:
            f.write(body.compose_yaml)

        cmd = compose_prefix + [
            "-f", compose_path,
            "-p", body.project_name,
            "up", "-d",
        ]
        r = await _run_docker(cmd, timeout=600)
        if r.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"docker compose up failed: {r.stderr.strip() or r.stdout.strip()}",
            )

        # List the containers that compose created so we can return them.
        ps = await _run_docker(
            compose_prefix + ["-f", compose_path, "-p", body.project_name, "ps", "--format", "{{json .}}"],
            timeout=30,
        )
        containers: List[Dict[str, Any]] = []
        if ps.returncode == 0:
            for line in (ps.stdout or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    _log(
        db, request, current_user.id,
        "docker.compose_deploy",
        f"Deployed compose project {body.project_name}",
    )
    return {"project_name": body.project_name, "containers": containers}


# ---------------------------------------------------------------------------
# POST /compose — alias for frontend compatibility
# Frontend sends { yaml } instead of { compose_yaml, project_name }.
# ---------------------------------------------------------------------------

@router.post("/compose", status_code=status.HTTP_201_CREATED)
async def compose_deploy_alias(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Check Docker availability with graceful fallback
    try:
        await _check_docker_available()
    except HTTPException:
        return {"detail": "Docker not available", "project_name": None, "containers": []}

    # Normalise payload: frontend sends {yaml} while backend expects {compose_yaml, project_name}
    compose_yaml = body.get("yaml") or body.get("compose_yaml") or ""
    project_name = body.get("project_name") or "compose-project"
    normalised = ComposeDeploy(compose_yaml=compose_yaml, project_name=project_name)
    return await compose_deploy(body=normalised, request=request, db=db, current_user=current_user)


# ---------------------------------------------------------------------------
# POST /compose/validate — validate compose file
# ---------------------------------------------------------------------------

@router.post("/compose/validate", response_model=ComposeValidateResponse)
async def compose_validate(body: ComposeValidate):
    await _check_docker_available()

    errors: List[str] = []

    # Quick local syntax check.
    try:
        parsed = yaml.safe_load(body.compose_yaml)
    except yaml.YAMLError as exc:
        return ComposeValidateResponse(valid=False, errors=[f"YAML parse error: {exc}"])

    if not isinstance(parsed, dict) or "services" not in parsed:
        errors.append("compose file must define a top-level 'services' key")

    # Use ``docker compose config`` for the authoritative check.
    try:
        compose_prefix = await _compose_command_prefix()
    except HTTPException:
        # No compose CLI -- fall back to local-only validation.
        return ComposeValidateResponse(valid=len(errors) == 0, errors=errors)

    tmpdir = tempfile.mkdtemp(prefix="compose-validate-")
    compose_path = os.path.join(tmpdir, "docker-compose.yml")
    try:
        with open(compose_path, "w", encoding="utf-8") as f:
            f.write(body.compose_yaml)

        r = await _run_docker(
            compose_prefix + ["-f", compose_path, "config", "--quiet"],
            timeout=30,
        )
        if r.returncode != 0:
            errors.append((r.stderr.strip() or r.stdout.strip() or "compose validation failed"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

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

    try:
        _validate_container_id(docker_container_id)
    except HTTPException:
        await websocket.close(code=4000, reason="Invalid container id")
        return

    # Stream logs using docker logs --follow via subprocess
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
