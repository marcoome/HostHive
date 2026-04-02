"""Monitoring router -- /api/v1/monitoring (admin only)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
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
from api.models.domains import Domain
from api.models.monitoring import AnomalyAlert, HealthCheck, MonitoringIncident
from api.models.users import User
from api.schemas.monitoring import (
    AnomalyListResponse,
    AnomalyAlertResponse,
    BandwidthListResponse,
    DiskPredictionResponse,
    DomainBandwidthResponse,
    HealthCheckListResponse,
    HealthCheckResponse,
    IncidentListResponse,
    IncidentResponse,
    RealtimeStatsResponse,
    TrafficHeatmapResponse,
)
from api.services.monitoring import MonitoringService

router = APIRouter()

_admin = require_role("admin")


def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# GET /health -- current health status for all services
# --------------------------------------------------------------------------
@router.get("/health", response_model=HealthCheckListResponse, status_code=status.HTTP_200_OK)
async def health_checks(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    try:
        agent = None  # health checks are direct network probes, no agent needed
        svc = MonitoringService(db, agent)
        results = await svc.run_health_checks()

        items = []
        for r in results:
            hc = HealthCheck(
                service_name=r.service_name,
                status=r.status,
                response_time_ms=r.response_time_ms,
                error_message=r.error_message,
            )
            items.append(HealthCheckResponse(
                id=hc.id,
                service_name=hc.service_name,
                status=hc.status,
                response_time_ms=hc.response_time_ms,
                error_message=hc.error_message,
                checked_at=datetime.now(timezone.utc),
            ))

        return HealthCheckListResponse(items=items, total=len(items))
    except Exception:
        return HealthCheckListResponse(items=[], total=0)


# --------------------------------------------------------------------------
# GET /health/history -- last 24h of health check records
# --------------------------------------------------------------------------
@router.get("/health/history", response_model=HealthCheckListResponse, status_code=status.HTTP_200_OK)
async def health_history(
    hours: int = Query(24, ge=1, le=168),
    service: str = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = select(HealthCheck).where(HealthCheck.checked_at >= since)
    if service:
        query = query.where(HealthCheck.service_name == service)
    query = query.order_by(HealthCheck.checked_at.desc())

    result = await db.execute(query)
    rows = result.scalars().all()

    return HealthCheckListResponse(
        items=[HealthCheckResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


# --------------------------------------------------------------------------
# GET /incidents -- list incidents
# --------------------------------------------------------------------------
@router.get("/incidents", response_model=IncidentListResponse, status_code=status.HTTP_200_OK)
async def list_incidents(
    resolved: bool = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    query = select(MonitoringIncident)
    if resolved is True:
        query = query.where(MonitoringIncident.resolved_at.is_not(None))
    elif resolved is False:
        query = query.where(MonitoringIncident.resolved_at.is_(None))
    query = query.order_by(MonitoringIncident.started_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()

    return IncidentListResponse(
        items=[IncidentResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


# --------------------------------------------------------------------------
# GET /anomalies -- unacknowledged anomaly alerts
# --------------------------------------------------------------------------
@router.get("/anomalies", response_model=AnomalyListResponse, status_code=status.HTTP_200_OK)
async def list_anomalies(
    acknowledged: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    query = (
        select(AnomalyAlert)
        .where(AnomalyAlert.is_acknowledged == acknowledged)
        .order_by(AnomalyAlert.created_at.desc())
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    return AnomalyListResponse(
        items=[AnomalyAlertResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


# --------------------------------------------------------------------------
# POST /anomalies/{id}/acknowledge -- dismiss anomaly
# --------------------------------------------------------------------------
@router.post("/anomalies/{anomaly_id}/acknowledge", status_code=status.HTTP_200_OK)
async def acknowledge_anomaly(
    anomaly_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    result = await db.execute(
        select(AnomalyAlert).where(AnomalyAlert.id == anomaly_id)
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found.")

    alert.is_acknowledged = True
    db.add(alert)
    await db.flush()

    _log(db, request, admin.id, "monitoring.acknowledge_anomaly",
         f"Acknowledged anomaly {anomaly_id} for metric {alert.metric_name}")

    return {"status": "acknowledged", "id": str(anomaly_id)}


# --------------------------------------------------------------------------
# GET /disk-prediction -- predictive disk usage
# --------------------------------------------------------------------------
def _safe_float(val, default: float = 0.0) -> float:
    """Return a safe float, replacing None/NaN/Inf with default."""
    import math
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    """Return a safe int, replacing None/NaN/Inf with default."""
    import math
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return int(f)
    except (TypeError, ValueError):
        return default


@router.get("/disk-prediction", response_model=DiskPredictionResponse, status_code=status.HTTP_200_OK)
async def disk_prediction(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    try:
        svc = MonitoringService(db)
        result = await svc.predict_disk_full()
        # Sanitise numeric fields to avoid NaN
        return DiskPredictionResponse(
            days_until_full=_safe_float(result.days_until_full, 0.0) if result.days_until_full is not None else None,
            current_usage_percent=_safe_float(result.current_usage_percent),
            current_used_gb=_safe_float(result.current_used_gb),
            total_gb=_safe_float(result.total_gb),
            trend_gb_per_day=_safe_float(result.trend_gb_per_day),
        )
    except Exception:
        return DiskPredictionResponse(
            days_until_full=None,
            current_usage_percent=0.0,
            current_used_gb=0.0,
            total_gb=0.0,
            trend_gb_per_day=0.0,
        )


# --------------------------------------------------------------------------
# GET /bandwidth/{domain} -- bandwidth per domain
# --------------------------------------------------------------------------
@router.get("/bandwidth/{domain}", response_model=BandwidthListResponse, status_code=status.HTTP_200_OK)
async def domain_bandwidth(
    domain: str = Path(..., max_length=255),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # Verify domain exists
    result = await db.execute(
        select(Domain).where(Domain.domain_name == domain)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")

    svc = MonitoringService(db)
    items = await svc.get_domain_bandwidth(domain, days)

    total_in = sum(i["bytes_in"] for i in items)
    total_out = sum(i["bytes_out"] for i in items)
    total_req = sum(i["requests_count"] for i in items)

    return BandwidthListResponse(
        domain=domain,
        items=[DomainBandwidthResponse(**i) for i in items],
        total_bytes_in=total_in,
        total_bytes_out=total_out,
        total_requests=total_req,
    )


# --------------------------------------------------------------------------
# GET /heatmap -- traffic heatmap
# --------------------------------------------------------------------------
@router.get("/heatmap", response_model=TrafficHeatmapResponse, status_code=status.HTTP_200_OK)
async def traffic_heatmap(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    svc = MonitoringService(db)
    return await svc.get_traffic_heatmap(days)


# --------------------------------------------------------------------------
# GET /realtime -- current stats snapshot
# --------------------------------------------------------------------------
@router.get("/realtime", response_model=RealtimeStatsResponse, status_code=status.HTTP_200_OK)
async def realtime_stats(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        data = await agent.get_server_stats()
    except Exception:
        data = {}

    return RealtimeStatsResponse(
        cpu_percent=_safe_float(data.get("cpu_percent")),
        memory_percent=_safe_float(data.get("memory_percent")),
        memory_used_mb=_safe_int(data.get("memory_used_mb")),
        memory_total_mb=_safe_int(data.get("memory_total_mb")),
        disk_percent=_safe_float(data.get("disk_percent")),
        disk_used_gb=_safe_float(data.get("disk_used_gb")),
        disk_total_gb=_safe_float(data.get("disk_total_gb")),
        load_avg_1=_safe_float(data.get("load_avg_1")),
        load_avg_5=_safe_float(data.get("load_avg_5")),
        load_avg_15=_safe_float(data.get("load_avg_15")),
        network_rx_bytes=_safe_int(data.get("network_rx_bytes")),
        network_tx_bytes=_safe_int(data.get("network_tx_bytes")),
        active_connections=_safe_int(data.get("active_connections")),
    )


# --------------------------------------------------------------------------
# WebSocket /ws/monitoring -- real-time stats stream (every 2s)
# --------------------------------------------------------------------------
@router.websocket("/ws/monitoring")
async def ws_monitoring(websocket: WebSocket):
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
                data = await agent.get_server_stats()
                await websocket.send_json(data)
            except Exception as exc:
                await websocket.send_json({"error": str(exc)})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
