"""Status page router -- /api/v1/status (PUBLIC, except incident creation)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.integrations import (
    IncidentSeverity,
    IncidentStatus,
    StatusIncident,
)
from api.models.users import User

router = APIRouter()

_admin = require_role("admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=client_ip,
    ))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ServiceStatus(BaseModel):
    name: str
    status: str  # "operational", "degraded", "outage"
    last_check: datetime | None = None


class IncidentResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    severity: IncidentSeverity
    status: IncidentStatus
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IncidentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    severity: IncidentSeverity = IncidentSeverity.MINOR


class IncidentUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    severity: Optional[IncidentSeverity] = None
    status: Optional[IncidentStatus] = None


class StatusPageResponse(BaseModel):
    overall: str
    services: list[ServiceStatus]
    active_incidents: int


# ---------------------------------------------------------------------------
# Static service list (would normally come from monitoring checks)
# ---------------------------------------------------------------------------

_SERVICES = [
    "Web Server (Nginx)",
    "Database (MariaDB)",
    "Mail (Postfix/Dovecot)",
    "DNS (PowerDNS)",
    "FTP (ProFTPD)",
    "SSL (Let's Encrypt)",
    "Firewall",
    "Backup System",
]


# ---------------------------------------------------------------------------
# GET / -- public status of all services
# ---------------------------------------------------------------------------
@router.get("", response_model=StatusPageResponse, status_code=status.HTTP_200_OK)
async def public_status(
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    # Count active (unresolved) incidents
    active_result = await db.execute(
        select(StatusIncident).where(StatusIncident.status != IncidentStatus.RESOLVED)
    )
    active_incidents = active_result.scalars().all()

    # Derive overall status from active incidents
    severities = {i.severity for i in active_incidents}
    if IncidentSeverity.CRITICAL in severities:
        overall = "major_outage"
    elif IncidentSeverity.MAJOR in severities:
        overall = "partial_outage"
    elif active_incidents:
        overall = "degraded"
    else:
        overall = "operational"

    services = [
        ServiceStatus(name=s, status="operational", last_check=now)
        for s in _SERVICES
    ]

    return StatusPageResponse(
        overall=overall,
        services=services,
        active_incidents=len(active_incidents),
    )


# ---------------------------------------------------------------------------
# GET /incidents -- list incidents last 30 days (public)
# ---------------------------------------------------------------------------
@router.get("/incidents", status_code=status.HTTP_200_OK)
async def list_incidents(
    db: AsyncSession = Depends(get_db),
) -> list[IncidentResponse]:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    result = await db.execute(
        select(StatusIncident)
        .where(StatusIncident.created_at >= since)
        .order_by(StatusIncident.created_at.desc())
    )
    incidents = result.scalars().all()
    return [IncidentResponse.model_validate(i) for i in incidents]


# ---------------------------------------------------------------------------
# POST /incidents -- create incident (admin only)
# ---------------------------------------------------------------------------
@router.post("/incidents", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: IncidentCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    incident = StatusIncident(
        title=body.title,
        description=body.description,
        severity=body.severity,
        status=IncidentStatus.INVESTIGATING,
    )
    db.add(incident)
    await db.flush()

    _log(db, request, admin.id, "status.incident.create", f"Created incident: {body.title}")
    return IncidentResponse.model_validate(incident)


# ---------------------------------------------------------------------------
# PUT /incidents/{id} -- update incident status (admin only)
# ---------------------------------------------------------------------------
@router.put("/incidents/{incident_id}", response_model=IncidentResponse, status_code=status.HTTP_200_OK)
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    result = await db.execute(
        select(StatusIncident).where(StatusIncident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(incident, field, value)

    # Auto-set resolved_at when status becomes RESOLVED
    if body.status == IncidentStatus.RESOLVED and incident.resolved_at is None:
        incident.resolved_at = datetime.now(timezone.utc)

    db.add(incident)
    await db.flush()

    _log(db, request, admin.id, "status.incident.update", f"Updated incident {incident_id}")
    return IncidentResponse.model_validate(incident)


# ---------------------------------------------------------------------------
# GET /widget -- embeddable status widget (HTML/JSON)
# ---------------------------------------------------------------------------
@router.get("/widget", status_code=status.HTTP_200_OK)
async def status_widget(
    format: str = "json",
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    active_result = await db.execute(
        select(StatusIncident).where(StatusIncident.status != IncidentStatus.RESOLVED)
    )
    active_incidents = active_result.scalars().all()

    severities = {i.severity for i in active_incidents}
    if IncidentSeverity.CRITICAL in severities:
        overall = "major_outage"
        color = "#e74c3c"
        label = "Major Outage"
    elif IncidentSeverity.MAJOR in severities:
        overall = "partial_outage"
        color = "#e67e22"
        label = "Partial Outage"
    elif active_incidents:
        overall = "degraded"
        color = "#f1c40f"
        label = "Degraded Performance"
    else:
        overall = "operational"
        color = "#2ecc71"
        label = "All Systems Operational"

    if format == "html":
        from fastapi.responses import HTMLResponse
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
.hh-status {{font-family:sans-serif;padding:12px 20px;border-radius:6px;
background:{color};color:#fff;text-align:center;font-size:14px;}}
</style></head>
<body><div class="hh-status">{label}</div></body>
</html>"""
        return HTMLResponse(content=html)

    return {
        "overall": overall,
        "label": label,
        "color": color,
        "active_incidents": len(active_incidents),
        "updated_at": now.isoformat(),
    }
