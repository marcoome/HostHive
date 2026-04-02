"""Apps router -- /api/v1/apps.

Deploy and manage Node.js / Python applications.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.apps import App
from api.models.users import User
from api.schemas.apps import (
    AppDeployRequest,
    AppEnvUpdate,
    AppListEntry,
    AppLogsResponse,
    AppStatusResponse,
    AppStopStartResponse,
)

router = APIRouter()


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


# --------------------------------------------------------------------------
# GET / -- list all running apps
# --------------------------------------------------------------------------


@router.get("", response_model=list[AppListEntry])
async def list_apps(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.get("/apps/list")
    return resp.get("data", [])


# --------------------------------------------------------------------------
# POST /deploy -- deploy Node.js or Python app
# --------------------------------------------------------------------------


@router.post("/deploy", response_model=AppStatusResponse)
async def deploy_app(
    body: AppDeployRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent

    if body.runtime == "nodejs":
        resp = await agent.post("/apps/deploy/nodejs", json={
            "domain": body.domain,
            "path": body.path,
            "port": body.port,
            "node_version": body.version or "20",
        })
    elif body.runtime == "python":
        resp = await agent.post("/apps/deploy/python", json={
            "domain": body.domain,
            "path": body.path,
            "port": body.port,
            "python_version": body.version or "3.11",
        })
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported runtime: {body.runtime}")

    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Deployment failed"))

    # Persist to DB
    db.add(App(
        user_id=current_user.id,
        domain=body.domain,
        runtime=body.runtime,
        port=body.port,
        path=body.path,
        status="running",
        version=body.version,
    ))

    data = resp.get("data", resp)
    return data


# --------------------------------------------------------------------------
# POST /{domain}/stop
# --------------------------------------------------------------------------


@router.post("/{domain}/stop", response_model=AppStopStartResponse)
async def stop_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.post("/apps/stop", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Stop failed"))

    # Update DB
    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if app_row:
        app_row.status = "stopped"

    return {"domain": domain, "action": "stop", "success": True}


# --------------------------------------------------------------------------
# POST /{domain}/start
# --------------------------------------------------------------------------


@router.post("/{domain}/start", response_model=AppStopStartResponse)
async def start_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.post("/apps/restart", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Start failed"))

    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if app_row:
        app_row.status = "running"

    return {"domain": domain, "action": "start", "success": True}


# --------------------------------------------------------------------------
# POST /{domain}/restart
# --------------------------------------------------------------------------


@router.post("/{domain}/restart", response_model=AppStopStartResponse)
async def restart_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.post("/apps/restart", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Restart failed"))

    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if app_row:
        app_row.status = "running"

    return {"domain": domain, "action": "restart", "success": True}


# --------------------------------------------------------------------------
# GET /{domain}/status -- app status + resource usage
# --------------------------------------------------------------------------


@router.get("/{domain}/status", response_model=AppStatusResponse)
async def app_status(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.get(f"/apps/status/{domain}")
    if not resp.get("ok", True):
        raise HTTPException(status_code=404, detail=resp.get("error", "App not found"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /{domain}/logs -- app logs
# --------------------------------------------------------------------------


@router.get("/{domain}/logs", response_model=AppLogsResponse)
async def app_logs(
    domain: str,
    lines: int = Query(200, ge=1, le=10000),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.get(f"/apps/logs/{domain}", params={"lines": lines})
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# PUT /{domain}/env -- update environment variables
# --------------------------------------------------------------------------


@router.put("/{domain}/env")
async def update_env_vars(
    domain: str,
    body: AppEnvUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.put(f"/apps/env/{domain}", json={
        "domain": domain,
        "env_dict": body.env_vars,
    })
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to update env vars"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# WebSocket /ws/apps/{domain}/logs -- live log streaming
# --------------------------------------------------------------------------


@router.websocket("/ws/apps/{domain}/logs")
async def ws_app_logs(websocket: WebSocket, domain: str):
    """Stream live application logs via WebSocket.

    Clients receive log lines as they are written.
    """
    import asyncio
    from pathlib import Path

    await websocket.accept()

    log_path = Path(f"/var/log/hosthive/apps/{domain}.stdout.log")

    try:
        # Start tailing the log file
        if not log_path.exists():
            await websocket.send_text(f"No log file found for {domain}")
            await websocket.close()
            return

        # Use tail -f approach via asyncio subprocess
        proc = await asyncio.create_subprocess_exec(
            "tail", "-f", "-n", "50", str(log_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_output():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await websocket.send_text(line.decode("utf-8", errors="replace").rstrip())

        read_task = asyncio.create_task(read_output())

        # Wait for client disconnect
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            read_task.cancel()
            proc.terminate()

    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
