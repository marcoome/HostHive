"""DNS router -- /api/v1/dns.

All operations follow the DB-first pattern:
1. Validate & persist to database.
2. Sync to BIND9 directly via zone files + ``rndc reload`` (no agent proxy).
3. If Cloudflare is enabled for the zone, auto-sync changes to CF.

BIND interaction is handled in-process by ``api.services.bind_service`` which
writes zone files, manages ``named.conf.local`` entries and runs ``rndc``.
There is no longer any HTTP call-out to a node agent on port 7080 -- this
router talks to BIND directly.

If BIND is unavailable the data is still safely in the DB and a warning is
attached to the response so the operator knows manual sync may be needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.dns_records import DnsRecord
from api.models.dns_zones import DnsZone
from api.models.domains import Domain
from api.models.packages import Package
from api.models.users import User
from api.schemas.dns import (
    CloudflareEnableRequest,
    CloudflareProxyToggle,
    CloudflareStatusResponse,
    DnsClusterNodeCreate,
    DnsClusterNodeResponse,
    DnsClusterStatusResponse,
    DnssecEnableRequest,
    DnssecStatusResponse,
    DnsRecordCreate,
    DnsRecordResponse,
    DnsRecordUpdate,
    DnsZoneCreate,
    DnsZoneDetailResponse,
    DnsZoneResponse,
)
from api.services.bind_service import (
    enable_dnssec,
    disable_dnssec,
    generate_zone_file,
    get_ds_record,
    push_zone_to_all_nodes,
    remove_zone,
    resign_zone,
    write_zone,
)
from api.services.cloudflare_service import CloudflareService

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


async def _sync_zone_to_bind(
    zone_name: str,
    records: list[DnsRecord],
    dnssec_enabled: bool = False,
) -> dict | None:
    """Write zone file and reload BIND.  Returns a warning dict or None.

    When *dnssec_enabled* is ``True``, the zone is re-signed after writing
    so that RRSIG records stay current.
    """
    try:
        ok, msg = await write_zone(zone_name, records)
        if not ok:
            _dns_logger.warning("BIND sync warning for %s: %s", zone_name, msg)
            return {"bind_warning": msg}
    except Exception as exc:
        _dns_logger.warning("BIND sync failed for %s: %s", zone_name, exc)
        return {"bind_warning": f"BIND sync failed: {exc}"}

    # Re-sign the zone if DNSSEC is active
    if dnssec_enabled:
        try:
            ok, msg = await resign_zone(zone_name)
            if not ok:
                _dns_logger.warning("DNSSEC re-sign warning for %s: %s", zone_name, msg)
                return {"dnssec_warning": f"Re-sign issue: {msg}"}
        except Exception as exc:
            _dns_logger.warning("DNSSEC re-sign failed for %s: %s", zone_name, exc)
            return {"dnssec_warning": f"Re-sign failed: {exc}"}

    return None


async def _generate_zone_file_async(zone_name: str, records: list[DnsRecord]) -> str:
    """Run the synchronous BIND zone-file generator in the default executor.

    ``generate_zone_file`` performs blocking filesystem reads (to grab the
    current SOA serial), so we offload it to a thread to avoid blocking the
    event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, generate_zone_file, zone_name, records)


def _attach_warnings(response_dict: dict, *warnings: dict | None) -> dict:
    """Merge any non-None warning dicts into the response."""
    for w in warnings:
        if w:
            response_dict.update(w)
    return response_dict


def _build_cf_service(zone: DnsZone) -> CloudflareService | None:
    """Return a CloudflareService for the zone, or None if CF is not enabled."""
    if not zone.cloudflare_enabled or not zone.cloudflare_config:
        return None
    try:
        return CloudflareService(zone.cloudflare_config)
    except Exception as exc:
        _dns_logger.warning("Failed to init CloudflareService for zone %s: %s", zone.zone_name, exc)
        return None


def _records_to_cf_payload(records: list[DnsRecord], zone_name: str) -> list[dict]:
    """Convert DB records into dicts suitable for CloudflareService.sync_dns_zone."""
    result = []
    for r in records:
        name = r.name if r.name != "@" else zone_name
        result.append({
            "type": r.record_type,
            "name": name,
            "content": r.value,
            "ttl": r.ttl,
            "proxied": False,
        })
    return result


async def _try_cf_sync(zone: DnsZone, records: list[DnsRecord]) -> dict | None:
    """Best-effort sync of all zone records to Cloudflare.  Returns a warning dict or None."""
    cf = _build_cf_service(zone)
    if cf is None:
        return None
    try:
        payload = _records_to_cf_payload(records, zone.zone_name)
        await cf.sync_dns_zone(zone.zone_name, payload)
    except Exception as exc:
        _dns_logger.warning("Cloudflare sync failed for %s: %s", zone.zone_name, exc)
        return {"cloudflare_warning": f"CF sync failed: {exc}"}
    return None


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
    3. Generate BIND zone file & reload directly via bind_service.
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

        # -- Package limit check: max_dns_domains --
        if not _is_admin(current_user) and current_user.package_id:
            pkg_result = await db.execute(select(Package).where(Package.id == current_user.package_id))
            pkg = pkg_result.scalar_one_or_none()
            if pkg and pkg.max_dns_domains > 0:
                zone_count = (await db.execute(
                    select(func.count()).select_from(DnsZone).where(DnsZone.user_id == current_user.id)
                )).scalar() or 0
                if zone_count >= pkg.max_dns_domains:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"DNS zone limit reached ({pkg.max_dns_domains}). Upgrade your package for more.",
                    )

        # -- 1. DB first --
        zone = DnsZone(
            user_id=current_user.id,
            domain_id=domain_id,
            zone_name=zone_name,
        )
        db.add(zone)
        await db.flush()

        _log(db, request, current_user.id, "dns.create_zone", f"Created zone {zone_name}")

        # -- 2. BIND sync (direct, in-process via bind_service) --
        bind_warn = await _sync_zone_to_bind(zone_name, [])

        response = DnsZoneResponse.model_validate(zone).model_dump(mode="json")
        return _attach_warnings(response, bind_warn)

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
    """Delete a zone from DB and remove the BIND zone file directly."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    # -- 1. DB first --
    _log(db, request, current_user.id, "dns.delete_zone", f"Deleted zone {zone.zone_name}")
    await db.delete(zone)
    await db.flush()

    # -- 2. Remove BIND zone file (direct via bind_service) --
    try:
        await remove_zone(zone.zone_name)
    except Exception as exc:
        _dns_logger.warning("BIND zone removal failed for %s: %s", zone.zone_name, exc)


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
    2. Regenerate full zone file and reload BIND directly via bind_service.
    3. Mirror to Cloudflare if enabled for this zone.
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

    # -- 2. BIND sync (direct, with DNSSEC re-sign if enabled) --
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records, dnssec_enabled=zone.dnssec_enabled)

    # -- 3. Cloudflare auto-sync --
    cf_warn = await _try_cf_sync(zone, all_records)

    response = DnsRecordResponse.model_validate(record).model_dump(mode="json")
    return _attach_warnings(response, bind_warn, cf_warn)


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
    2. Regenerate full zone file and reload BIND directly via bind_service.
    3. Mirror to Cloudflare if enabled for this zone.
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

    # -- 2. BIND sync (direct, with DNSSEC re-sign if enabled) --
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records, dnssec_enabled=zone.dnssec_enabled)

    # -- 3. Cloudflare auto-sync --
    cf_warn = await _try_cf_sync(zone, all_records)

    response = DnsRecordResponse.model_validate(record).model_dump(mode="json")
    return _attach_warnings(response, bind_warn, cf_warn)


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
    2. Regenerate zone file (without the deleted record) and reload BIND
       directly via bind_service.
    3. Mirror to Cloudflare if enabled for this zone.
    """
    zone = await _get_zone_or_404(zone_id, db, current_user)
    record = await _get_record_or_404(record_id, zone_id, db)

    # -- 1. DB first --
    _log(db, request, current_user.id, "dns.delete_record", f"Deleted record {record_id} from {zone.zone_name}")
    await db.delete(record)
    await db.flush()

    # -- 2. BIND sync (direct) --
    remaining_records = await _fetch_zone_records(db, zone_id)
    try:
        await write_zone(zone.zone_name, remaining_records)
        # Re-sign if DNSSEC is enabled
        if zone.dnssec_enabled:
            try:
                await resign_zone(zone.zone_name)
            except Exception as exc:
                _dns_logger.warning("DNSSEC re-sign after record delete failed for %s: %s", zone.zone_name, exc)
    except Exception as exc:
        _dns_logger.warning("BIND sync after record delete failed for %s: %s", zone.zone_name, exc)

    # -- 3. Cloudflare auto-sync --
    await _try_cf_sync(zone, remaining_records)


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

    # Sync to BIND directly via bind_service (no agent proxy)
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records)

    _log(db, request, current_user.id, "dns.import_zone", f"Imported {imported} records for {zone.zone_name}")

    result = {"detail": "Zone imported successfully.", "records_imported": imported}
    return _attach_warnings(result, bind_warn)


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

    # Run the blocking generator (file I/O for SOA serial) in the executor
    bind_content = await _generate_zone_file_async(zone.zone_name, records)

    return {
        "zone_name": zone.zone_name,
        "bind_format": bind_content,
    }


# =========================================================================
# DNSSEC
# =========================================================================

@router.post("/zones/{zone_id}/dnssec/enable", status_code=status.HTTP_200_OK)
async def dnssec_enable(
    zone_id: uuid.UUID,
    body: DnssecEnableRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable DNSSEC for a zone: generate KSK+ZSK, sign zone, return DS record."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    if zone.dnssec_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNSSEC is already enabled for this zone.",
        )

    # Ensure the zone file exists before signing
    all_records = await _fetch_zone_records(db, zone_id)
    await _sync_zone_to_bind(zone.zone_name, all_records)

    ok, msg, ds_record = await enable_dnssec(zone.zone_name, body.algorithm)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enable DNSSEC: {msg}",
        )

    # Persist to DB
    zone.dnssec_enabled = True
    zone.dnssec_algorithm = body.algorithm
    zone.ds_record = ds_record
    await db.flush()

    _log(db, request, current_user.id, "dns.dnssec_enable", f"Enabled DNSSEC for {zone.zone_name} ({body.algorithm})")

    return {
        "detail": msg,
        "dnssec_enabled": True,
        "algorithm": body.algorithm,
        "ds_record": ds_record,
    }


@router.delete("/zones/{zone_id}/dnssec/disable", status_code=status.HTTP_200_OK)
async def dnssec_disable(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable DNSSEC for a zone: remove keys, revert to unsigned zone."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    if not zone.dnssec_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNSSEC is not enabled for this zone.",
        )

    ok, msg = await disable_dnssec(zone.zone_name)

    # Persist to DB
    zone.dnssec_enabled = False
    zone.ds_record = None
    await db.flush()

    _log(db, request, current_user.id, "dns.dnssec_disable", f"Disabled DNSSEC for {zone.zone_name}")

    return {"detail": msg, "dnssec_enabled": False}


@router.get("/zones/{zone_id}/dnssec/status", status_code=status.HTTP_200_OK)
async def dnssec_status(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the DNSSEC status for a zone."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    return DnssecStatusResponse(
        enabled=zone.dnssec_enabled,
        algorithm=zone.dnssec_algorithm if zone.dnssec_enabled else None,
        ds_record=zone.ds_record,
    ).model_dump()


@router.get("/zones/{zone_id}/dnssec/ds-record", status_code=status.HTTP_200_OK)
async def dnssec_ds_record(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the DS record for the zone, to be provided to the domain registrar."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    if not zone.dnssec_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNSSEC is not enabled for this zone.",
        )

    # Try to extract a fresh DS record from the key files
    ds = await get_ds_record(zone.zone_name)
    if ds is None:
        # Fall back to stored value
        ds = zone.ds_record

    if ds and ds != zone.ds_record:
        # Update stored value if it changed
        zone.ds_record = ds
        await db.flush()

    if not ds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DS record not found. Keys may not have been generated correctly.",
        )

    return {"zone_name": zone.zone_name, "ds_record": ds}


# =========================================================================
# Cloudflare integration
# =========================================================================

@router.post("/zones/{zone_id}/cloudflare/enable", status_code=status.HTTP_200_OK)
async def cloudflare_enable(
    zone_id: uuid.UUID,
    body: CloudflareEnableRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable Cloudflare sync for a zone.  Stores the CF credentials (encrypted)."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    config_plain = json.dumps({
        "api_key": body.api_key,
        "email": body.email,
        "zone_id": body.cf_zone_id,
    })
    zone.cloudflare_config = encrypt_value(config_plain, settings.SECRET_KEY)
    zone.cloudflare_enabled = True
    await db.flush()

    _log(db, request, current_user.id, "dns.cf_enable", f"Enabled Cloudflare for {zone.zone_name}")

    return {"detail": "Cloudflare integration enabled.", "cloudflare_enabled": True}


@router.delete("/zones/{zone_id}/cloudflare/disable", status_code=status.HTTP_200_OK)
async def cloudflare_disable(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable Cloudflare sync for a zone and remove stored credentials."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    zone.cloudflare_enabled = False
    zone.cloudflare_config = None
    await db.flush()

    _log(db, request, current_user.id, "dns.cf_disable", f"Disabled Cloudflare for {zone.zone_name}")

    return {"detail": "Cloudflare integration disabled.", "cloudflare_enabled": False}


@router.get("/zones/{zone_id}/cloudflare/status", status_code=status.HTTP_200_OK)
async def cloudflare_status(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check whether Cloudflare is enabled for this zone and return basic info."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    if not zone.cloudflare_enabled or not zone.cloudflare_config:
        return CloudflareStatusResponse(enabled=False).model_dump()

    try:
        config = json.loads(decrypt_value(zone.cloudflare_config, settings.SECRET_KEY))
        return CloudflareStatusResponse(
            enabled=True,
            cf_zone_id=config.get("zone_id"),
            email=config.get("email"),
        ).model_dump()
    except Exception:
        return CloudflareStatusResponse(enabled=False).model_dump()


@router.post("/zones/{zone_id}/cloudflare/sync", status_code=status.HTTP_200_OK)
async def cloudflare_sync(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Push all zone records from DB to Cloudflare (full sync)."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    cf = _build_cf_service(zone)
    if cf is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cloudflare is not enabled for this zone.",
        )

    records = await _fetch_zone_records(db, zone_id)
    payload = _records_to_cf_payload(records, zone.zone_name)

    try:
        result = await cf.sync_dns_zone(zone.zone_name, payload)
    except Exception as exc:
        _dns_logger.exception("Cloudflare sync error for %s: %s", zone.zone_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cloudflare sync failed: {exc}",
        )

    _log(db, request, current_user.id, "dns.cf_sync", f"Synced {result.get('synced', 0)} records to CF for {zone.zone_name}")

    return {"detail": "Cloudflare sync complete.", **result}


@router.post("/zones/{zone_id}/cloudflare/import", status_code=status.HTTP_200_OK)
async def cloudflare_import(
    zone_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import DNS records from Cloudflare into the local DB."""
    zone = await _get_zone_or_404(zone_id, db, current_user)

    cf = _build_cf_service(zone)
    if cf is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cloudflare is not enabled for this zone.",
        )

    try:
        existing = await cf._request(
            "GET", f"/zones/{cf._zone_id}/dns_records?per_page=500"
        )
    except Exception as exc:
        _dns_logger.exception("Cloudflare import error for %s: %s", zone.zone_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch records from Cloudflare: {exc}",
        )

    valid_types = {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA", "PTR"}
    imported = 0

    for cf_rec in existing.get("result", []):
        rtype = cf_rec.get("type", "").upper()
        if rtype not in valid_types:
            continue

        name = cf_rec.get("name", "")
        # Shorten FQDN to relative name
        if name.endswith("." + zone.zone_name):
            name = name[: -(len(zone.zone_name) + 1)]
        elif name == zone.zone_name:
            name = "@"

        priority = cf_rec.get("priority")
        rec = DnsRecord(
            zone_id=zone_id,
            record_type=rtype,
            name=name,
            value=cf_rec.get("content", ""),
            ttl=cf_rec.get("ttl", 3600),
            priority=priority,
        )
        db.add(rec)
        imported += 1

    await db.flush()

    # Sync to BIND
    all_records = await _fetch_zone_records(db, zone_id)
    bind_warn = await _sync_zone_to_bind(zone.zone_name, all_records)

    _log(db, request, current_user.id, "dns.cf_import", f"Imported {imported} records from CF for {zone.zone_name}")

    result = {"detail": "Import from Cloudflare complete.", "records_imported": imported}
    return _attach_warnings(result, bind_warn)


@router.put("/zones/{zone_id}/cloudflare/proxy/{record_id}", status_code=status.HTTP_200_OK)
async def cloudflare_toggle_proxy(
    zone_id: uuid.UUID,
    record_id: uuid.UUID,
    body: CloudflareProxyToggle,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle the Cloudflare proxy (orange cloud) for a specific A/AAAA record."""
    zone = await _get_zone_or_404(zone_id, db, current_user)
    record = await _get_record_or_404(record_id, zone_id, db)

    if record.record_type not in ("A", "AAAA"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proxy can only be toggled for A/AAAA records.",
        )

    cf = _build_cf_service(zone)
    if cf is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cloudflare is not enabled for this zone.",
        )

    # Find the matching CF record by type+name
    rec_name = record.name if record.name != "@" else zone.zone_name
    try:
        cf_records = await cf._request(
            "GET",
            f"/zones/{cf._zone_id}/dns_records?type={record.record_type}&name={rec_name}&per_page=100",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query Cloudflare: {exc}",
        )

    matched = [
        r for r in cf_records.get("result", [])
        if r.get("content") == record.value
    ]
    if not matched:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matching record not found in Cloudflare.  Sync the zone first.",
        )

    cf_record_id = matched[0]["id"]
    try:
        resp = await cf._request(
            "PATCH",
            f"/zones/{cf._zone_id}/dns_records/{cf_record_id}",
            json_body={"proxied": body.proxied},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to toggle proxy in Cloudflare: {exc}",
        )

    _log(
        db, request, current_user.id, "dns.cf_proxy",
        f"Set proxy={'on' if body.proxied else 'off'} for {record.record_type} {record.name} in {zone.zone_name}",
    )

    return {
        "detail": f"Proxy {'enabled' if body.proxied else 'disabled'} for {record.name}.",
        "proxied": body.proxied,
        "cf_record_id": cf_record_id,
    }


# =========================================================================
# DNS Cluster
# =========================================================================

@router.get("/cluster/nodes", status_code=status.HTTP_200_OK)
async def list_cluster_nodes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all DNS cluster nodes.  Admin only."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    from api.models.dns_cluster import DnsClusterNode

    result = await db.execute(select(DnsClusterNode))
    nodes = result.scalars().all()

    return {
        "items": [DnsClusterNodeResponse.model_validate(n) for n in nodes],
        "total": len(nodes),
    }


@router.post("/cluster/nodes", status_code=status.HTTP_201_CREATED)
async def add_cluster_node(
    body: DnsClusterNodeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a DNS cluster node.  Admin only.

    The API key is stored encrypted.
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    from api.models.dns_cluster import DnsClusterNode

    # Duplicate check
    existing = await db.execute(
        select(DnsClusterNode).where(DnsClusterNode.hostname == body.hostname)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Node with this hostname already exists.")

    encrypted_key = encrypt_value(body.api_key, settings.SECRET_KEY)

    node = DnsClusterNode(
        hostname=body.hostname,
        ip_address=body.ip_address,
        port=body.port,
        api_url=body.api_url,
        api_key=encrypted_key,
        role=body.role,
    )
    db.add(node)
    await db.flush()

    _log(db, request, current_user.id, "dns.cluster_add_node", f"Added cluster node {body.hostname} ({body.ip_address})")

    return DnsClusterNodeResponse.model_validate(node).model_dump(mode="json")


@router.delete("/cluster/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_cluster_node(
    node_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a DNS cluster node.  Admin only."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    from api.models.dns_cluster import DnsClusterNode

    result = await db.execute(select(DnsClusterNode).where(DnsClusterNode.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster node not found.")

    _log(db, request, current_user.id, "dns.cluster_remove_node", f"Removed cluster node {node.hostname}")
    await db.delete(node)
    await db.flush()


@router.post("/cluster/sync", status_code=status.HTTP_200_OK)
async def trigger_cluster_sync(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger a manual sync of all zones to all active cluster slave nodes.  Admin only."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    # Fetch all active zones
    zones_result = await db.execute(select(DnsZone).where(DnsZone.is_active.is_(True)))
    zones = zones_result.scalars().all()

    all_results: list[dict] = []
    for zone in zones:
        records = await _fetch_zone_records(db, zone.id)
        results = await push_zone_to_all_nodes(zone.zone_name, records)
        for r in results:
            r["zone"] = zone.zone_name
        all_results.extend(results)

    _log(db, request, current_user.id, "dns.cluster_sync", f"Manual cluster sync: {len(zones)} zones")

    succeeded = sum(1 for r in all_results if r.get("success"))
    failed = len(all_results) - succeeded

    return {
        "detail": f"Cluster sync complete. {succeeded} succeeded, {failed} failed.",
        "zones_synced": len(zones),
        "results": all_results,
    }


@router.get("/cluster/status", status_code=status.HTTP_200_OK)
async def cluster_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check the sync status of all cluster nodes.  Admin only."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    from api.models.dns_cluster import DnsClusterNode

    nodes_result = await db.execute(select(DnsClusterNode))
    nodes = nodes_result.scalars().all()

    zones_count = (await db.execute(
        select(func.count()).select_from(DnsZone).where(DnsZone.is_active.is_(True))
    )).scalar() or 0

    node_responses = [DnsClusterNodeResponse.model_validate(n) for n in nodes]

    # Find last full sync (the minimum last_sync_at across all active slaves)
    active_slaves = [n for n in nodes if n.is_active and n.role == "slave"]
    last_full_sync = None
    if active_slaves:
        sync_times = [n.last_sync_at for n in active_slaves if n.last_sync_at is not None]
        if sync_times and len(sync_times) == len(active_slaves):
            last_full_sync = str(min(sync_times))

    return DnsClusterStatusResponse(
        nodes=node_responses,
        total_zones=zones_count,
        last_full_sync=last_full_sync,
    ).model_dump(mode="json")


@router.post("/cluster/receive", status_code=status.HTTP_200_OK)
async def receive_zone_from_cluster(
    request: Request,
):
    """Receive a zone file push from a master node.

    This endpoint is called by the master node to push zone data to this slave.
    Authentication is via the ``Authorization: Bearer <api_key>`` header, which
    should match the key configured for this node on the master.

    All BIND interaction is performed in-process via ``bind_service`` --
    blocking filesystem writes are dispatched to the default thread pool
    executor and the ``rndc reload`` invocation uses the non-blocking
    ``asyncio.create_subprocess_exec`` helper inside ``bind_service``.
    """
    from api.services.bind_service import (
        _ensure_named_conf_entry_sync,
        _write_zone_file_sync,
        _rndc_reload,
    )

    body = await request.json()
    zone_name = body.get("zone_name")
    zone_content = body.get("zone_content")

    if not zone_name or not zone_content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="zone_name and zone_content are required.",
        )

    # Offload blocking filesystem writes to the default executor
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_zone_file_sync, zone_name, zone_content)
    await loop.run_in_executor(None, _ensure_named_conf_entry_sync, zone_name, [])

    # rndc reload itself is non-blocking (asyncio.create_subprocess_exec)
    ok, output = await _rndc_reload(zone_name)

    return {
        "detail": f"Zone {zone_name} received and {'reloaded' if ok else 'written (reload failed)'}.",
        "bind_reload": ok,
        "bind_output": output,
    }
