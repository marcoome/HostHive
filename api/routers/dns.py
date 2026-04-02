"""DNS router -- /api/v1/dns."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.dns_records import DnsRecord
from api.models.dns_zones import DnsZone
from api.models.domains import Domain
from api.models.users import User
from api.schemas.dns import (
    DnsRecordCreate,
    DnsRecordResponse,
    DnsZoneCreate,
    DnsZoneDetailResponse,
    DnsZoneResponse,
)

router = APIRouter()


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_zone_or_404(
    zone_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> DnsZone:
    result = await db.execute(select(DnsZone).where(DnsZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DNS zone not found.")
    if not _is_admin(current_user) and zone.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return zone


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# ==========================================================================
# Zones
# ==========================================================================

@router.get("/zones", status_code=status.HTTP_200_OK)
async def list_zones(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(DnsZone)
    count_query = select(func.count()).select_from(DnsZone)
    if not _is_admin(current_user):
        query = query.where(DnsZone.user_id == current_user.id)
        count_query = count_query.where(DnsZone.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    return {
        "items": [DnsZoneResponse.model_validate(z) for z in results],
        "total": total,
    }


@router.post("/zones", status_code=status.HTTP_201_CREATED)
async def create_zone(
    body: DnsZoneCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import logging
    _dns_logger = logging.getLogger("hosthive.dns")

    try:
        # If domain_id is provided, verify domain ownership
        domain_id = body.domain_id
        if domain_id is not None:
            domain_result = await db.execute(select(Domain).where(Domain.id == domain_id))
            domain = domain_result.scalar_one_or_none()
            if domain is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
            if not _is_admin(current_user) and domain.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to domain.")
        else:
            # Try to look up the domain by zone_name (frontend sends name only)
            domain_result = await db.execute(
                select(Domain).where(Domain.domain_name == body.zone_name)
            )
            domain = domain_result.scalar_one_or_none()
            if domain is not None:
                if not _is_admin(current_user) and domain.user_id != current_user.id:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to domain.")
                domain_id = domain.id

        zone_name = body.zone_name
        if not zone_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="zone_name is required.")

        exists = await db.execute(select(DnsZone).where(DnsZone.zone_name == zone_name))
        if exists.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Zone already exists.")

        agent = request.app.state.agent
        agent_ok = True
        try:
            await agent.create_zone(zone_name)
        except Exception as exc:
            # Log the agent error but still create the zone record in the database.
            # The zone can be synced to the agent later.
            agent_ok = False
            _dns_logger.warning(
                "Agent error creating zone %s (will create DB record anyway): %s",
                zone_name, exc,
            )

        zone = DnsZone(
            user_id=current_user.id,
            domain_id=domain_id,
            zone_name=zone_name,
        )
        db.add(zone)
        await db.flush()

        _log(db, request, current_user.id, "dns.create_zone", f"Created zone {zone_name}")

        response = DnsZoneResponse.model_validate(zone)
        # If agent failed, still return 201 but include a warning
        if not agent_ok:
            return {
                **response.model_dump(mode="json"),
                "warning": "Zone created in database but agent provisioning failed. It may need manual sync.",
            }
        return response

    except HTTPException:
        raise
    except Exception as exc:
        _dns_logger.exception("Unexpected error creating DNS zone: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create DNS zone: {exc}",
        )


@router.get("/zones/{zone_id}", response_model=DnsZoneDetailResponse, status_code=status.HTTP_200_OK)
async def get_zone(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(zone_id, db, current_user)
    records_result = await db.execute(
        select(DnsRecord).where(DnsRecord.zone_id == zone_id)
    )
    records = records_result.scalars().all()

    resp = DnsZoneDetailResponse.model_validate(zone)
    resp.records = [DnsRecordResponse.model_validate(r) for r in records]
    return resp


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(zone_id, db, current_user)
    agent = request.app.state.agent

    try:
        await agent.delete_zone(zone.zone_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting zone: {exc}",
        )

    _log(db, request, current_user.id, "dns.delete_zone", f"Deleted zone {zone.zone_name}")
    await db.delete(zone)
    await db.flush()


# ==========================================================================
# Records within zones
# ==========================================================================

@router.get("/zones/{zone_id}/records", status_code=status.HTTP_200_OK)
async def list_records(
    zone_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_zone_or_404(zone_id, db, current_user)  # authz

    count_query = select(func.count()).select_from(DnsRecord).where(DnsRecord.zone_id == zone_id)
    total = (await db.execute(count_query)).scalar() or 0

    results = (await db.execute(
        select(DnsRecord).where(DnsRecord.zone_id == zone_id).offset(skip).limit(limit)
    )).scalars().all()

    return {
        "items": [DnsRecordResponse.model_validate(r) for r in results],
        "total": total,
    }


@router.post("/zones/{zone_id}/records", response_model=DnsRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_record(
    zone_id: uuid.UUID,
    body: DnsRecordCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(zone_id, db, current_user)
    agent = request.app.state.agent

    try:
        await agent.add_dns_record(
            zone=zone.zone_name,
            record_type=body.record_type,
            name=body.name,
            value=body.value,
            ttl=body.ttl,
            priority=body.priority,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error adding record: {exc}",
        )

    record = DnsRecord(
        zone_id=zone_id,
        record_type=body.record_type,
        name=body.name,
        value=body.value,
        ttl=body.ttl,
        priority=body.priority,
    )
    db.add(record)
    await db.flush()

    _log(db, request, current_user.id, "dns.create_record", f"Added {body.record_type} record to {zone.zone_name}")
    return DnsRecordResponse.model_validate(record)


@router.delete("/zones/{zone_id}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    zone_id: uuid.UUID,
    record_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(zone_id, db, current_user)

    result = await db.execute(
        select(DnsRecord).where(DnsRecord.id == record_id, DnsRecord.zone_id == zone_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DNS record not found.")

    agent = request.app.state.agent
    try:
        await agent.delete_dns_record(zone.zone_name, str(record_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting record: {exc}",
        )

    _log(db, request, current_user.id, "dns.delete_record", f"Deleted record {record_id} from {zone.zone_name}")
    await db.delete(record)
    await db.flush()


# ==========================================================================
# Import / Export
# ==========================================================================

@router.post("/zones/{zone_id}/import", status_code=status.HTTP_200_OK)
async def import_zone(
    zone_id: uuid.UUID,
    file: UploadFile,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(zone_id, db, current_user)
    content = (await file.read()).decode("utf-8")

    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST",
            f"/dns/zone/{zone.zone_name}/import",
            json_body={"zone_data": content},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error importing zone: {exc}",
        )

    _log(db, request, current_user.id, "dns.import_zone", f"Imported zone file for {zone.zone_name}")
    return {"detail": "Zone imported successfully.", "records_imported": result.get("records_imported", 0)}


@router.get("/zones/{zone_id}/export", status_code=status.HTTP_200_OK)
async def export_zone(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(zone_id, db, current_user)

    # Build BIND-format zone file from DB records
    records_result = await db.execute(
        select(DnsRecord).where(DnsRecord.zone_id == zone_id)
    )
    records = records_result.scalars().all()

    lines = [
        f"; Zone file for {zone.zone_name}",
        f"$ORIGIN {zone.zone_name}.",
        f"$TTL 3600",
        "",
    ]
    for r in records:
        priority_part = f"{r.priority} " if r.priority is not None else ""
        lines.append(f"{r.name}\t{r.ttl}\tIN\t{r.record_type}\t{priority_part}{r.value}")

    return {
        "zone_name": zone.zone_name,
        "bind_format": "\n".join(lines),
    }
