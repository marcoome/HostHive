"""DNS router -- /api/v1/dns.

All operations follow the DB-first pattern:
1. Validate & persist to database.
2. Try to sync to BIND9 (directly via zone files + ``rndc reload``).
3. Optionally try the agent as a secondary sync path.

If BIND or the agent is unavailable the data is still safely in the DB and
a warning is attached to the response so the operator knows manual sync may
be needed.
"""

from __future__ import annotations

import logging
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
    DnsRecordUpdate,
    DnsZoneCreate,
    DnsZoneDetailResponse,
    DnsZoneResponse,
)
from api.services.bind_service import generate_zone_file, remove_zone, write_zone

router = APIRouter()
_dns_logger = logging.getLogger("hosthive.dns")


# =========================================================================
# Helpers
# =========================================================================

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


async def _get_record_or_404(
    record_id: uuid.UUID,
    zone_id: uuid.UUID,
    db: AsyncSession,
) -> DnsRecord:
    result = await db.execute(
        select(DnsRecord).where(DnsRecord.id == record_id, DnsRecord.zone_id == zone_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DNS record not found.")
    return record


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _fetch_zone_records(db: AsyncSession, zone_id: uuid.UUID) -> list[DnsRecord]:
    """Return all DNS records for a zone from the DB."""
    result = await db.execute(select(DnsRecord).where(DnsRecord.zone_id == zone_id))
    return list(result.scalars().all())


async def _sync_zone_to_bind(zone_name: str, records: list[DnsRecord]) -> dict | None:
    """Write zone file and reload BIND.  Returns a warning dict or None."""
    try:
        ok, msg = await write_zone(zone_name, records)
        if not ok:
            _dns_logger.warning("BIND sync warning for %s: %s", zone_name, msg)
            return {"bind_warning": msg}
    except Exception as exc:
        _dns_logger.warning("BIND sync failed for %s: %s", zone_name, exc)
        return {"bind_warning": f"BIND sync failed: {exc}"}
    return None


async def _try_agent(request: Request, coro_factory, label: str) -> dict | None:
    """Try calling the agent; return a warning dict on failure, None on success."""
    try:
        agent = getattr(request.app.state, "agent", None)
        if agent is None:
            return {"agent_warning": "Agent not configured."}
        await coro_factory(agent)
    except Exception as exc:
        _dns_logger.warning("Agent error (%s): %s", label, exc)
        return {"agent_warning": f"Agent error: {exc}"}
    return None


def _attach_warnings(response_dict: dict, *warnings: dict | None) -> dict:
    """Merge any non-None warning dicts into the response."""
    for w in warnings:
        if w:
            response_dict.update(w)
    return response_dict


# =========================================================================
# Zones
# =========================================================================

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
    """Create a DNS zone.

    1. Validate domain ownership (if domain_id given).
    2. Persist zone to DB.
    3. Generate BIND zone file & reload.
    4. Try agent as secondary sync.
    """
    try:
        # -- Domain ownership check --
        domain_id = body.domain_id
        if domain_id is not None:
            domain_result = await db.execute(select(Domain).where(Domain.id == domain_id))
            domain = domain_result.scalar_one_or_none()
            if domain is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
            if not _is_admin(current_user) and domain.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to domain.")
        else:
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
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="zone_name is required.",
            )

        # -- Duplicate check --
        exists = await db.execute(select(DnsZone).where(DnsZone.zone_name == zone_name))
        if exists.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Zone already exists.")

        # -- 1. DB first --
        zone = DnsZone(
            user_id=current_user.id,
            domain_id=domain_id,
            zone_name=zone_name,
        )
        db.add(zone)
        await db.flush()

        _log(db, request, current_user.id, "dns.create_zone", f"Created zone {zone_name}")

        # -- 2. BIND sync (direct) --
        bind_warn = await _sync_zone_to_bind(zone_name, [])

        # -- 3. Agent sync (best-effort) --
        agent_warn = await _try_agent(
            request,
            lambda ag: ag.create_zone(zone_name),
            f"create_zone({zone_name})",
        )

        response = DnsZoneResponse.model_validate(zone).model_dump(mode="json")
        return _attach_warnings(response, bind_warn, agent_warn)

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
    records = await _fetch_zone_records(db, zone_id)

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
    """Delete a zone from DB, remove BIND zone file, and try agent."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    # -- 1. DB first --
    _log(db, request, current_user.id, "dns.delete_zone", f"Deleted zone {zone.zone_name}")
    await db.delete(zone)
    await db.flush()

    # -- 2. Remove BIND zone file --
    try:
        await remove_zone(zone.zone_name)
    except Exception as exc:
        _dns_logger.warning("BIND zone removal failed for %s: %s", zone.zone_name, exc)

    # -- 3. Agent (best-effort) --
    await _try_agent(
        request,
        lambda ag: ag.delete_zone(zone.zone_name),
        f"delete_zone({zone.zone_name})",
    )


# =========================================================================
# Records within zones
# =========================================================================

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
    """Create a DNS record.

    1. Persist to DB.
    2. Regenerate full zone file and reload BIND.
    3. Try agent as secondary sync.
    """
    zone = await _get_zone_or_404(zone_id, db, current_user)

    # -- 1. DB first --
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

    # -- 2. BIND sync --
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records)

    # -- 3. Agent sync --
    agent_warn = await _try_agent(
        request,
        lambda ag: ag.add_dns_record(
            zone=zone.zone_name,
            record_type=body.record_type,
            name=body.name,
            value=body.value,
            ttl=body.ttl,
            priority=body.priority,
        ),
        f"add_record({zone.zone_name})",
    )

    response = DnsRecordResponse.model_validate(record).model_dump(mode="json")
    return _attach_warnings(response, bind_warn, agent_warn)


@router.put("/zones/{zone_id}/records/{record_id}", status_code=status.HTTP_200_OK)
async def update_record(
    zone_id: uuid.UUID,
    record_id: uuid.UUID,
    body: DnsRecordUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing DNS record.

    1. Update fields in DB.
    2. Regenerate full zone file and reload BIND.
    3. Try agent as secondary sync.
    """
    zone = await _get_zone_or_404(zone_id, db, current_user)
    record = await _get_record_or_404(record_id, zone_id, db)

    # -- 1. Apply partial update to DB --
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update.",
        )

    for field, value in update_data.items():
        setattr(record, field, value)
    await db.flush()

    _log(
        db, request, current_user.id, "dns.update_record",
        f"Updated record {record_id} in {zone.zone_name}",
    )

    # -- 2. BIND sync --
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records)

    # -- 3. Agent sync (best-effort: delete old + create new) --
    agent_warn = await _try_agent(
        request,
        lambda ag: ag.add_dns_record(
            zone=zone.zone_name,
            record_type=record.record_type,
            name=record.name,
            value=record.value,
            ttl=record.ttl,
            priority=record.priority,
        ),
        f"update_record({zone.zone_name})",
    )

    response = DnsRecordResponse.model_validate(record).model_dump(mode="json")
    return _attach_warnings(response, bind_warn, agent_warn)


@router.delete("/zones/{zone_id}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    zone_id: uuid.UUID,
    record_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a DNS record.

    1. Remove from DB.
    2. Regenerate zone file (without the deleted record) and reload BIND.
    3. Try agent as secondary sync.
    """
    zone = await _get_zone_or_404(zone_id, db, current_user)
    record = await _get_record_or_404(record_id, zone_id, db)

    # -- 1. DB first --
    _log(db, request, current_user.id, "dns.delete_record", f"Deleted record {record_id} from {zone.zone_name}")
    await db.delete(record)
    await db.flush()

    # -- 2. BIND sync --
    remaining_records = await _fetch_zone_records(db, zone_id)
    try:
        await write_zone(zone.zone_name, remaining_records)
    except Exception as exc:
        _dns_logger.warning("BIND sync after record delete failed for %s: %s", zone.zone_name, exc)

    # -- 3. Agent sync --
    await _try_agent(
        request,
        lambda ag: ag.delete_dns_record(zone.zone_name, str(record_id)),
        f"delete_record({zone.zone_name})",
    )


# =========================================================================
# Import / Export
# =========================================================================

@router.post("/zones/{zone_id}/import", status_code=status.HTTP_200_OK)
async def import_zone(
    zone_id: uuid.UUID,
    file: UploadFile,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a BIND zone file.

    Parses each resource record line, saves to DB, then regenerates the zone
    file and reloads BIND.
    """
    zone = await _get_zone_or_404(zone_id, db, current_user)
    content = (await file.read()).decode("utf-8")

    imported = 0
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("$"):
            continue
        # Very basic RR parser: NAME TTL CLASS TYPE RDATA
        # Also handles: NAME CLASS TYPE RDATA (no explicit TTL)
        parts = line.split()
        if len(parts) < 4:
            continue

        # Determine layout
        name = parts[0]
        idx = 1

        # Optional TTL (numeric)
        ttl = 3600
        if parts[idx].isdigit():
            ttl = int(parts[idx])
            idx += 1

        # Class (IN)
        if idx < len(parts) and parts[idx].upper() == "IN":
            idx += 1

        if idx + 1 >= len(parts):
            continue

        record_type = parts[idx].upper()
        idx += 1

        # Priority for MX/SRV
        priority = None
        if record_type in ("MX", "SRV") and idx + 1 < len(parts) and parts[idx].isdigit():
            priority = int(parts[idx])
            idx += 1

        value = " ".join(parts[idx:])

        # Skip SOA records (we generate those)
        if record_type == "SOA":
            continue

        valid_types = {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA", "PTR"}
        if record_type not in valid_types:
            continue

        rec = DnsRecord(
            zone_id=zone_id,
            record_type=record_type,
            name=name,
            value=value.strip('"'),
            ttl=ttl,
            priority=priority,
        )
        db.add(rec)
        imported += 1

    await db.flush()

    # Sync to BIND
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records)

    # Try agent too
    agent_warn = await _try_agent(
        request,
        lambda ag: ag._request(
            "POST",
            f"/dns/zone/{zone.zone_name}/import",
            json_body={"zone_data": content},
        ),
        f"import_zone({zone.zone_name})",
    )

    _log(db, request, current_user.id, "dns.import_zone", f"Imported {imported} records for {zone.zone_name}")

    result = {"detail": "Zone imported successfully.", "records_imported": imported}
    return _attach_warnings(result, bind_warn, agent_warn)


@router.get("/zones/{zone_id}/export", status_code=status.HTTP_200_OK)
async def export_zone(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export zone as a BIND-format zone file generated from DB records."""
    zone = await _get_zone_or_404(zone_id, db, current_user)
    records = await _fetch_zone_records(db, zone_id)

    bind_content = generate_zone_file(zone.zone_name, records)

    return {
        "zone_name": zone.zone_name,
        "bind_format": bind_content,
    }
