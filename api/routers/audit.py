"""Audit log router -- /api/v1/audit (admin only)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

router = APIRouter()

_admin = require_role("admin")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AuditEntryResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    action: str
    details: str | None = None
    ip_address: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditListResponse(BaseModel):
    items: list[AuditEntryResponse]
    total: int
    page: int
    per_page: int


class SuspiciousEntryResponse(BaseModel):
    user_id: uuid.UUID
    minute: str
    action_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_filters(
    query,
    count_query,
    user_id: uuid.UUID | None,
    action: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    ip_address: str | None,
):
    if user_id is not None:
        query = query.where(ActivityLog.user_id == user_id)
        count_query = count_query.where(ActivityLog.user_id == user_id)
    if action is not None:
        # Prefix match: "domain.*" -> LIKE 'domain.%'
        like_pattern = action.replace("*", "%")
        query = query.where(ActivityLog.action.like(like_pattern))
        count_query = count_query.where(ActivityLog.action.like(like_pattern))
    if date_from is not None:
        query = query.where(ActivityLog.created_at >= date_from)
        count_query = count_query.where(ActivityLog.created_at >= date_from)
    if date_to is not None:
        query = query.where(ActivityLog.created_at <= date_to)
        count_query = count_query.where(ActivityLog.created_at <= date_to)
    if ip_address is not None:
        query = query.where(ActivityLog.ip_address == ip_address)
        count_query = count_query.where(ActivityLog.ip_address == ip_address)
    return query, count_query


# ---------------------------------------------------------------------------
# GET / -- list audit log entries (paginated)
# ---------------------------------------------------------------------------
@router.get("", response_model=AuditListResponse, status_code=status.HTTP_200_OK)
async def list_audit_entries(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    ip_address: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(ActivityLog)
    count_query = select(func.count()).select_from(ActivityLog)

    # Non-admin users can only see their own activity
    if current_user.role.value != "admin":
        query = query.where(ActivityLog.user_id == current_user.id)
        count_query = count_query.where(ActivityLog.user_id == current_user.id)

    query, count_query = _apply_filters(query, count_query, user_id, action, date_from, date_to, ip_address)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(
            query.order_by(ActivityLog.created_at.desc()).offset(skip).limit(limit)
        )
    ).scalars().all()

    return AuditListResponse(
        items=[AuditEntryResponse.model_validate(r) for r in results],
        total=total,
        page=(skip // limit) + 1,
        per_page=limit,
    )


# ---------------------------------------------------------------------------
# GET /export -- export audit log as CSV (streaming)
# ---------------------------------------------------------------------------
@router.get("/export", status_code=status.HTTP_200_OK)
async def export_audit_csv(
    user_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    ip_address: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    query = select(ActivityLog)
    count_query = select(func.count()).select_from(ActivityLog)  # not used but needed for helper
    query, _ = _apply_filters(query, count_query, user_id, action, date_from, date_to, ip_address)
    query = query.order_by(ActivityLog.created_at.desc())

    results = (await db.execute(query)).scalars().all()

    def _generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "user_id", "action", "details", "ip_address", "created_at"])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for entry in results:
            writer.writerow([
                str(entry.id),
                str(entry.user_id) if entry.user_id else "",
                entry.action,
                entry.details or "",
                entry.ip_address or "",
                entry.created_at.isoformat() if entry.created_at else "",
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


# ---------------------------------------------------------------------------
# GET /suspicious -- users with > 10 actions/minute
# ---------------------------------------------------------------------------
@router.get("/suspicious", status_code=status.HTTP_200_OK)
async def suspicious_activity(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
) -> list[SuspiciousEntryResponse]:
    try:
        # Look at the last 24 hours for suspicious bursts
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        stmt = (
            select(
                ActivityLog.user_id,
                func.date_trunc("minute", ActivityLog.created_at).label("minute"),
                func.count().label("action_count"),
            )
            .where(ActivityLog.created_at >= since)
            .where(ActivityLog.user_id.is_not(None))
            .group_by(ActivityLog.user_id, text("minute"))
            .having(func.count() > 10)
            .order_by(text("action_count DESC"))
        )

        result = await db.execute(stmt)
        rows = result.all()

        return [
            SuspiciousEntryResponse(
                user_id=row.user_id,
                minute=row.minute.isoformat() if row.minute else "",
                action_count=row.action_count,
            )
            for row in rows
        ]
    except Exception:
        return []
