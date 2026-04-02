"""Server router -- /api/v1/server (admin only)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role, verify_token
from api.models.activity_log import ActivityLog
from api.models.server_stats import ServerStat
from api.models.users import User
from api.schemas.server import FirewallRule

router = APIRouter()

_admin = require_role("admin")


def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# GET /stats -- current CPU/RAM/disk/net via agent
# --------------------------------------------------------------------------
@router.get("/stats", status_code=status.HTTP_200_OK)
async def server_stats(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent.get_server_stats()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error: {exc}",
        )
    return result


# --------------------------------------------------------------------------
# GET /stats/history -- last 24h from ServerStat table
# --------------------------------------------------------------------------
@router.get("/stats/history", status_code=status.HTTP_200_OK)
async def stats_history(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = (await db.execute(
        select(ServerStat)
        .where(ServerStat.created_at >= since)
        .order_by(ServerStat.created_at.asc())
    )).scalars().all()

    return {
        "items": [
            {
                "id": str(s.id),
                "cpu_percent": s.cpu_percent,
                "memory_percent": s.memory_percent,
                "memory_used_mb": s.memory_used_mb,
                "disk_percent": s.disk_percent,
                "disk_used_gb": s.disk_used_gb,
                "load_avg_1": s.load_avg_1,
                "load_avg_5": s.load_avg_5,
                "load_avg_15": s.load_avg_15,
                "network_rx_bytes": s.network_rx_bytes,
                "network_tx_bytes": s.network_tx_bytes,
                "active_connections": s.active_connections,
                "created_at": s.created_at.isoformat(),
            }
            for s in results
        ],
        "total": len(results),
    }


# --------------------------------------------------------------------------
# GET /services -- all service statuses
# --------------------------------------------------------------------------
@router.get("/services", status_code=status.HTTP_200_OK)
async def list_services(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/system/services")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error: {exc}",
        )
    return result


# --------------------------------------------------------------------------
# POST /services/{name}/restart
# --------------------------------------------------------------------------
@router.post("/services/{service_name}/restart", status_code=status.HTTP_200_OK)
async def restart_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent.service_action(service_name, "restart")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error restarting {service_name}: {exc}",
        )

    _log(db, request, admin.id, "server.restart_service", f"Restarted service {service_name}")
    return result


# --------------------------------------------------------------------------
# POST /services/{name}/start
# --------------------------------------------------------------------------
@router.post("/services/{service_name}/start", status_code=status.HTTP_200_OK)
async def start_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/service/restart",
            json_body={"name": service_name, "action": "start"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error starting {service_name}: {exc}",
        )
    _log(db, request, admin.id, "server.start_service", f"Started service {service_name}")
    return result


# --------------------------------------------------------------------------
# POST /services/{name}/stop
# --------------------------------------------------------------------------
@router.post("/services/{service_name}/stop", status_code=status.HTTP_200_OK)
async def stop_service(
    service_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/service/restart",
            json_body={"name": service_name, "action": "stop"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error stopping {service_name}: {exc}",
        )
    _log(db, request, admin.id, "server.stop_service", f"Stopped service {service_name}")
    return result


# --------------------------------------------------------------------------
# Firewall
# --------------------------------------------------------------------------

@router.get("/firewall", status_code=status.HTTP_200_OK)
async def firewall_rules(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/system/firewall")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error: {exc}",
        )
    return result


@router.post("/firewall", status_code=status.HTTP_201_CREATED)
async def add_firewall_rule(
    body: FirewallRule,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent.firewall_add_rule(body.model_dump())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error adding rule: {exc}",
        )

    _log(db, request, admin.id, "server.firewall_add", f"Added firewall rule: {body.model_dump()}")
    return result


@router.delete("/firewall/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_firewall_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        await agent.firewall_delete_rule(rule_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting rule: {exc}",
        )

    _log(db, request, admin.id, "server.firewall_delete", f"Deleted firewall rule {rule_id}")


# --------------------------------------------------------------------------
# Fail2ban
# --------------------------------------------------------------------------

@router.get("/fail2ban", status_code=status.HTTP_200_OK)
async def fail2ban_jails(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/system/fail2ban")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error: {exc}",
        )
    return result


@router.post("/fail2ban/unban", status_code=status.HTTP_200_OK)
async def fail2ban_unban(
    ip: str = Query(..., max_length=45),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST",
            "/system/fail2ban/unban",
            json_body={"ip": ip},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error unbanning IP: {exc}",
        )

    _log(db, request, admin.id, "server.fail2ban_unban", f"Unbanned IP {ip}")
    return result


# --------------------------------------------------------------------------
# POST /fail2ban/{jail}/enable
# --------------------------------------------------------------------------
@router.post("/fail2ban/{jail_name}/enable", status_code=status.HTTP_200_OK)
async def fail2ban_enable_jail(
    jail_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/fail2ban/enable",
            json_body={"jail": jail_name},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error enabling jail {jail_name}: {exc}",
        )
    _log(db, request, admin.id, "server.fail2ban_enable", f"Enabled jail {jail_name}")
    return result


# --------------------------------------------------------------------------
# POST /fail2ban/{jail}/disable
# --------------------------------------------------------------------------
@router.post("/fail2ban/{jail_name}/disable", status_code=status.HTTP_200_OK)
async def fail2ban_disable_jail(
    jail_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST", "/system/fail2ban/disable",
            json_body={"jail": jail_name},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error disabling jail {jail_name}: {exc}",
        )
    _log(db, request, admin.id, "server.fail2ban_disable", f"Disabled jail {jail_name}")
    return result


# --------------------------------------------------------------------------
# GET /logs -- query param variant for frontend compatibility
# --------------------------------------------------------------------------
@router.get("/logs", status_code=status.HTTP_200_OK)
async def get_service_logs_query(
    service: str = Query(...),
    lines: int = Query(200, ge=1, le=1000),
    request: Request = None,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "GET",
            f"/system/logs/{service}",
            params={"lines": lines},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error fetching logs: {exc}",
        )
    return result


# --------------------------------------------------------------------------
# GET /logs/{service} -- last 200 lines via agent
# --------------------------------------------------------------------------
@router.get("/logs/{service}", status_code=status.HTTP_200_OK)
async def service_logs(
    service: str,
    lines: int = Query(200, ge=1, le=1000),
    request: Request = None,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "GET",
            f"/system/logs/{service}",
            params={"lines": lines},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error fetching logs: {exc}",
        )
    return result


# --------------------------------------------------------------------------
# WebSocket /ws/terminal -- admin terminal (bidirectional)
# --------------------------------------------------------------------------
@router.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    # Authenticate via query param token
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = verify_token(token, expected_type="access")
        if payload.get("role") != "admin":
            await websocket.close(code=4003, reason="Admin required")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    agent = websocket.app.state.agent

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                command = msg.get("command", "")
                if not command:
                    await websocket.send_json({"error": "Empty command"})
                    continue

                result = await agent._request(
                    "POST",
                    "/terminal/exec",
                    json_body={"command": command},
                )
                await websocket.send_json(result)
            except Exception as exc:
                await websocket.send_json({"error": str(exc)})
    except WebSocketDisconnect:
        pass


# --------------------------------------------------------------------------
# WebSocket /ws/logs/{service} -- live log streaming
# --------------------------------------------------------------------------
@router.websocket("/ws/logs/{service}")
async def ws_log_stream(websocket: WebSocket, service: str):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = verify_token(token, expected_type="access")
        if payload.get("role") != "admin":
            await websocket.close(code=4003, reason="Admin required")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    agent = websocket.app.state.agent

    try:
        while True:
            try:
                result = await agent._request(
                    "GET",
                    f"/system/logs/{service}/tail",
                    params={"lines": 20},
                )
                await websocket.send_json(result)
            except Exception as exc:
                await websocket.send_json({"error": str(exc)})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
