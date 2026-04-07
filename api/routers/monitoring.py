"""Monitoring router -- /api/v1/monitoring (admin only).

All endpoints use psutil and asyncio subprocess directly for real system
data. This router never proxies to the on-host agent on port 7080 -- the
panel collects metrics in-process to avoid the agent dependency.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path as FastPath,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role, verify_token
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.monitoring import (
    AnomalyAlert,
    DomainBandwidth,
    HealthCheck,
    HealthStatus,
    MonitoringIncident,
)
from api.models.server_stats import ServerStat
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
logger = logging.getLogger("novapanel.monitoring")

_admin = require_role("admin")

# Thread-pool for blocking psutil / subprocess calls
_executor = ThreadPoolExecutor(max_workers=4)


def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _collect_system_metrics() -> Dict[str, Any]:
    """Blocking function that collects real system metrics via psutil.

    Designed to run in a thread-pool executor since some psutil calls block.
    """
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    disk_io = psutil.disk_io_counters()
    load = os.getloadavg()

    try:
        connections = len(psutil.net_connections())
    except (psutil.AccessDenied, OSError):
        connections = 0

    return {
        "cpu_percent": cpu_percent,
        "cpu_per_core": cpu_per_core,
        "memory_percent": mem.percent,
        "memory_used": mem.used,
        "memory_total": mem.total,
        "memory_used_mb": int(mem.used / (1024 * 1024)),
        "memory_total_mb": int(mem.total / (1024 * 1024)),
        "disk_percent": disk.percent,
        "disk_used": disk.used,
        "disk_total": disk.total,
        "disk_used_gb": round(disk.used / (1024 ** 3), 2),
        "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        "disk_read_bytes": disk_io.read_bytes if disk_io else 0,
        "disk_write_bytes": disk_io.write_bytes if disk_io else 0,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "network_rx_bytes": net.bytes_recv,
        "network_tx_bytes": net.bytes_sent,
        "load_1": load[0],
        "load_5": load[1],
        "load_15": load[2],
        "load_avg_1": load[0],
        "load_avg_5": load[1],
        "load_avg_15": load[2],
        "uptime_seconds": time.time() - psutil.boot_time(),
        "processes": len(psutil.pids()),
        "connections": connections,
        "active_connections": connections,
    }


async def _check_service_systemctl(service_name: str) -> Dict[str, Any]:
    """Check a single systemd service status using asyncio subprocess.

    Spawns `systemctl is-active <service>` non-blockingly and returns a
    dict suitable for building a HealthCheckResponse.
    """
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "service_name": service_name,
                "status": "unhealthy",
                "is_up": False,
                "response_time_ms": round(elapsed_ms, 2),
                "error_message": "Timeout checking service status",
            }

        elapsed_ms = (time.monotonic() - start) * 1000
        output = stdout.decode("utf-8", errors="replace").strip()
        is_active = output == "active"
        return {
            "service_name": service_name,
            "status": "healthy" if is_active else "unhealthy",
            "is_up": is_active,
            "response_time_ms": round(elapsed_ms, 2),
            "error_message": None if is_active else f"systemctl status: {output}",
        }
    except FileNotFoundError:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "service_name": service_name,
            "status": "unknown",
            "is_up": False,
            "response_time_ms": round(elapsed_ms, 2),
            "error_message": "systemctl not found (not a systemd system)",
        }
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "service_name": service_name,
            "status": "unhealthy",
            "is_up": False,
            "response_time_ms": round(elapsed_ms, 2),
            "error_message": str(exc),
        }


def _parse_nginx_access_log(log_path: str, days: int = 7) -> List[Dict[str, Any]]:
    """Parse nginx access log and return list of dicts with timestamp, bytes, status.

    Supports the default nginx combined log format. Blocking -- run in executor.
    """
    entries = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # nginx combined log format regex
    # 127.0.0.1 - - [02/Apr/2026:10:15:30 +0000] "GET /path HTTP/1.1" 200 1234 "ref" "ua"
    log_pattern = re.compile(
        r'(?P<ip>\S+)\s+\S+\s+\S+\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
        r'(?P<status>\d+)\s+'
        r'(?P<bytes>\d+|-)'
    )

    try:
        path = Path(log_path)
        if not path.exists():
            return entries

        with open(path, "r", errors="replace") as f:
            for line in f:
                m = log_pattern.match(line)
                if not m:
                    continue
                try:
                    ts = datetime.strptime(
                        m.group("timestamp"), "%d/%b/%Y:%H:%M:%S %z"
                    )
                    if ts < cutoff:
                        continue
                    byte_str = m.group("bytes")
                    byte_count = int(byte_str) if byte_str != "-" else 0
                    entries.append({
                        "timestamp": ts,
                        "status": int(m.group("status")),
                        "bytes": byte_count,
                        "method": m.group("method"),
                        "path": m.group("path"),
                    })
                except (ValueError, TypeError):
                    continue
    except (PermissionError, OSError) as exc:
        logger.warning("Cannot read nginx log %s: %s", log_path, exc)

    return entries


def _parse_nginx_domain_log(domain: str, days: int = 30) -> List[Dict[str, Any]]:
    """Parse domain-specific nginx access log. Blocking -- run in executor.

    Checks common log file locations for the domain.
    """
    candidate_paths = [
        f"/var/log/nginx/{domain}.access.log",
        f"/var/log/nginx/{domain}-access.log",
        f"/var/log/nginx/domains/{domain}.log",
        f"/var/log/nginx/domains/{domain}.access.log",
    ]

    for log_path in candidate_paths:
        if Path(log_path).exists():
            return _parse_nginx_access_log(log_path, days=days)

    # Fallback: parse the main access log and filter by Host header is not
    # easily possible from combined format, so return empty
    return []


# --------------------------------------------------------------------------
# GET /realtime -- current stats snapshot using psutil
# --------------------------------------------------------------------------
@router.get("/realtime", response_model=RealtimeStatsResponse, status_code=status.HTTP_200_OK)
async def realtime_stats(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return real-time system metrics collected directly via psutil.

    Never proxies to the on-host agent -- psutil runs in-process and is
    the single source of truth for these metrics.
    """
    loop = asyncio.get_running_loop()

    try:
        data = await loop.run_in_executor(_executor, _collect_system_metrics)
    except Exception as psutil_err:
        logger.warning("psutil collection failed: %s", psutil_err)
        data = {}

    return RealtimeStatsResponse(
        cpu_percent=_safe_float(data.get("cpu_percent")),
        cpu_per_core=data.get("cpu_per_core", []),
        memory_percent=_safe_float(data.get("memory_percent")),
        memory_used=_safe_int(data.get("memory_used")),
        memory_total=_safe_int(data.get("memory_total")),
        memory_used_mb=_safe_int(data.get("memory_used_mb")),
        memory_total_mb=_safe_int(data.get("memory_total_mb")),
        disk_percent=_safe_float(data.get("disk_percent")),
        disk_used=_safe_int(data.get("disk_used")),
        disk_total=_safe_int(data.get("disk_total")),
        disk_used_gb=_safe_float(data.get("disk_used_gb")),
        disk_total_gb=_safe_float(data.get("disk_total_gb")),
        disk_read_bytes=_safe_int(data.get("disk_read_bytes")),
        disk_write_bytes=_safe_int(data.get("disk_write_bytes")),
        net_bytes_sent=_safe_int(data.get("net_bytes_sent")),
        net_bytes_recv=_safe_int(data.get("net_bytes_recv")),
        network_rx_bytes=_safe_int(data.get("network_rx_bytes")),
        network_tx_bytes=_safe_int(data.get("network_tx_bytes")),
        load_1=_safe_float(data.get("load_1")),
        load_5=_safe_float(data.get("load_5")),
        load_15=_safe_float(data.get("load_15")),
        load_avg_1=_safe_float(data.get("load_avg_1")),
        load_avg_5=_safe_float(data.get("load_avg_5")),
        load_avg_15=_safe_float(data.get("load_avg_15")),
        uptime_seconds=_safe_float(data.get("uptime_seconds")),
        processes=_safe_int(data.get("processes")),
        connections=_safe_int(data.get("connections")),
        active_connections=_safe_int(data.get("active_connections")),
    )


# --------------------------------------------------------------------------
# GET /health -- real service health checks via systemctl + fallback
# --------------------------------------------------------------------------
@router.get("/health", response_model=HealthCheckListResponse, status_code=status.HTTP_200_OK)
async def health_checks(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Check actual service health using `systemctl is-active` via asyncio
    subprocess, with a fallback to network-probe health checks from
    MonitoringService when systemctl is unavailable.

    Never proxies to the on-host agent.
    """
    services_to_check = [
        "nginx", "postgresql", "redis-server",
        "exim4", "dovecot", "fail2ban", "proftpd",
    ]

    # Run all systemctl checks concurrently as native coroutines
    raw_results = await asyncio.gather(
        *(_check_service_systemctl(svc) for svc in services_to_check),
        return_exceptions=True,
    )

    systemctl_available = True
    results: List[Dict[str, Any]] = []
    for r in raw_results:
        if isinstance(r, Exception):
            logger.warning("Service check failed: %s", r)
            continue
        # If systemctl is not found, fall back to network probes
        if r.get("status") == "unknown" and "systemctl not found" in (r.get("error_message") or ""):
            systemctl_available = False
            break
        results.append(r)

    # Fallback: use network-probe based health checks from MonitoringService
    if not systemctl_available or not results:
        try:
            svc = MonitoringService(db, agent=None)
            probe_results = await svc.run_health_checks()
            results = []
            for pr in probe_results:
                results.append({
                    "service_name": pr.service_name,
                    "status": "healthy" if pr.is_up else "unhealthy",
                    "is_up": pr.is_up,
                    "response_time_ms": pr.response_time_ms,
                    "error_message": pr.error_message,
                })
        except Exception:
            results = []

    # Build response and persist to DB
    items: List[HealthCheckResponse] = []
    for r in results:
        is_up = r.get("is_up", r.get("status") == "healthy")
        if is_up:
            hc_status = HealthStatus.UP
        else:
            hc_status = HealthStatus.DOWN

        hc = HealthCheck(
            service_name=r["service_name"],
            status=hc_status,
            response_time_ms=r.get("response_time_ms", 0.0),
            error_message=r.get("error_message"),
        )
        db.add(hc)

        items.append(HealthCheckResponse(
            id=hc.id,
            service_name=hc.service_name,
            status=hc.status,
            response_time_ms=hc.response_time_ms,
            error_message=hc.error_message,
            checked_at=datetime.now(timezone.utc),
        ))

    try:
        await db.flush()
    except Exception as exc:
        logger.warning("Failed to persist health checks: %s", exc)

    return HealthCheckListResponse(items=items, total=len(items))


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
# GET /disk-prediction -- real disk data + DB-based trend analysis
# --------------------------------------------------------------------------
@router.get("/disk-prediction", response_model=DiskPredictionResponse, status_code=status.HTTP_200_OK)
async def disk_prediction(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Predict when disk will be full using current psutil data + historical
    growth rate from the ServerStat table."""
    loop = asyncio.get_running_loop()

    # Get current real disk usage via psutil
    try:
        disk = await loop.run_in_executor(_executor, psutil.disk_usage, "/")
        current_used_gb = round(disk.used / (1024 ** 3), 2)
        total_gb = round(disk.total / (1024 ** 3), 2)
        current_pct = disk.percent
    except Exception:
        current_used_gb = 0.0
        total_gb = 0.0
        current_pct = 0.0

    # Compute trend from ServerStat table (last 7 days of historical data)
    trend_gb_per_day = 0.0
    days_until_full: Optional[float] = None

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(ServerStat.disk_used_gb, ServerStat.created_at)
            .where(ServerStat.created_at >= cutoff)
            .order_by(ServerStat.created_at.asc())
        )
        rows = result.all()

        if len(rows) >= 2:
            t0 = rows[0].created_at
            xs = [(r.created_at - t0).total_seconds() / 3600 for r in rows]
            ys = [r.disk_used_gb for r in rows]

            n = len(xs)
            sum_x = sum(xs)
            sum_y = sum(ys)
            sum_xy = sum(x * y for x, y in zip(xs, ys))
            sum_xx = sum(x * x for x in xs)

            denom = n * sum_xx - sum_x * sum_x
            if denom != 0:
                slope = (n * sum_xy - sum_x * sum_y) / denom
                trend_gb_per_day = slope * 24  # GB per hour -> GB per day

            remaining = total_gb - current_used_gb
            if trend_gb_per_day > 0 and remaining > 0:
                days_until_full = round(remaining / trend_gb_per_day, 1)
    except Exception as exc:
        logger.warning("Failed to compute disk trend from DB: %s", exc)

    return DiskPredictionResponse(
        days_until_full=days_until_full,
        current_usage_percent=_safe_float(current_pct),
        current_used_gb=_safe_float(current_used_gb),
        total_gb=_safe_float(total_gb),
        trend_gb_per_day=_safe_float(round(trend_gb_per_day, 4)),
    )


# --------------------------------------------------------------------------
# GET /heatmap -- traffic heatmap from nginx access logs
# --------------------------------------------------------------------------
@router.get("/heatmap", response_model=TrafficHeatmapResponse, status_code=status.HTTP_200_OK)
async def traffic_heatmap(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Generate a traffic heatmap from real nginx access logs.

    Falls back to DB-based DomainBandwidth data if logs are unavailable.
    """
    loop = asyncio.get_running_loop()

    # Try parsing real nginx access logs first
    log_path = "/var/log/nginx/access.log"
    entries = await loop.run_in_executor(
        _executor, partial(_parse_nginx_access_log, log_path, days)
    )

    if entries:
        # Group by (day_of_week or date, hour)
        heatmap: Dict[str, List[int]] = defaultdict(lambda: [0] * 24)
        for entry in entries:
            ts = entry["timestamp"]
            day_label = ts.strftime("%Y-%m-%d")
            hour = ts.hour
            heatmap[day_label][hour] += 1

        # Sort by date descending, limit to requested days
        sorted_days = sorted(heatmap.keys(), reverse=True)[:days]
        labels_days = sorted_days
        data = [heatmap[d] for d in sorted_days]

        return TrafficHeatmapResponse(
            labels_days=labels_days,
            labels_hours=list(range(24)),
            data=data,
        )

    # Fallback: use DB DomainBandwidth data via MonitoringService
    try:
        svc = MonitoringService(db)
        return await svc.get_traffic_heatmap(days)
    except Exception:
        # Return empty heatmap
        return TrafficHeatmapResponse(
            labels_days=[],
            labels_hours=list(range(24)),
            data=[],
        )


# --------------------------------------------------------------------------
# GET /bandwidth/{domain} -- bandwidth from nginx domain logs
# --------------------------------------------------------------------------
@router.get("/bandwidth/{domain}", response_model=BandwidthListResponse, status_code=status.HTTP_200_OK)
async def domain_bandwidth(
    domain: str = FastPath(..., max_length=255),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Get bandwidth data for a specific domain from nginx logs.

    Falls back to DB DomainBandwidth records if logs are unavailable.
    """
    # Verify domain exists
    result = await db.execute(
        select(Domain).where(Domain.domain_name == domain)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")

    loop = asyncio.get_running_loop()

    # Try parsing real nginx domain logs
    log_entries = await loop.run_in_executor(
        _executor, partial(_parse_nginx_domain_log, domain, days)
    )

    if log_entries:
        # Aggregate by date
        daily: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"bytes_in": 0, "bytes_out": 0, "requests_count": 0}
        )
        for entry in log_entries:
            day_str = entry["timestamp"].strftime("%Y-%m-%d")
            daily[day_str]["bytes_out"] += entry["bytes"]
            daily[day_str]["requests_count"] += 1
            # Estimate bytes_in as ~10% of bytes_out (request headers vs response body)
            daily[day_str]["bytes_in"] += max(entry["bytes"] // 10, 200)

        sorted_dates = sorted(daily.keys())
        items = []
        for d in sorted_dates:
            items.append(DomainBandwidthResponse(
                date=date.fromisoformat(d),
                bytes_in=daily[d]["bytes_in"],
                bytes_out=daily[d]["bytes_out"],
                requests_count=daily[d]["requests_count"],
            ))

        total_in = sum(i.bytes_in for i in items)
        total_out = sum(i.bytes_out for i in items)
        total_req = sum(i.requests_count for i in items)

        return BandwidthListResponse(
            domain=domain,
            items=items,
            total_bytes_in=total_in,
            total_bytes_out=total_out,
            total_requests=total_req,
        )

    # Fallback: use DB via MonitoringService
    svc = MonitoringService(db)
    db_items = await svc.get_domain_bandwidth(domain, days)

    total_in = sum(i["bytes_in"] for i in db_items)
    total_out = sum(i["bytes_out"] for i in db_items)
    total_req = sum(i["requests_count"] for i in db_items)

    return BandwidthListResponse(
        domain=domain,
        items=[DomainBandwidthResponse(**i) for i in db_items],
        total_bytes_in=total_in,
        total_bytes_out=total_out,
        total_requests=total_req,
    )


# --------------------------------------------------------------------------
# WebSocket /ws/monitoring -- real-time stats stream (every 2s)
# --------------------------------------------------------------------------
@router.websocket("/ws/monitoring")
async def ws_monitoring(websocket: WebSocket):
    """Stream real system metrics via WebSocket every 2 seconds using psutil.

    Never proxies to the on-host agent -- psutil is collected in-process.
    """
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
    loop = asyncio.get_running_loop()

    try:
        while True:
            try:
                data = await loop.run_in_executor(_executor, _collect_system_metrics)
                await websocket.send_json(data)
            except Exception as psutil_err:
                await websocket.send_json({"error": str(psutil_err)})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        # Connection broken
        pass
