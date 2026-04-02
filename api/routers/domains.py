"""Domains router -- /api/v1/domains.

All nginx operations are performed directly via nginx_service (no agent).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.users import User
from api.schemas.domains import DomainCreate, DomainResponse, DomainUpdate
from api.services import nginx_service

router = APIRouter()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_domain_or_404(
    domain_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Domain:
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and domain.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return domain


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# GET / -- list domains
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_domains(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Domain)
    count_query = select(func.count()).select_from(Domain)
    if not _is_admin(current_user):
        query = query.where(Domain.user_id == current_user.id)
        count_query = count_query.where(Domain.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(query.order_by(Domain.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return {
        "items": [DomainResponse.model_validate(d) for d in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create domain
# --------------------------------------------------------------------------
@router.post("", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    body: DomainCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Check uniqueness
    exists = await db.execute(
        select(Domain).where(Domain.domain_name == body.domain_name)
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Domain already exists.",
        )

    doc_root = body.document_root or f"/home/{current_user.username}/web/{body.domain_name}/public_html"

    # 1. Save to DB first
    domain = Domain(
        user_id=current_user.id,
        domain_name=body.domain_name,
        document_root=doc_root,
        php_version=body.php_version,
    )
    db.add(domain)
    await db.flush()

    # 2. Create nginx vhost, document root, index.html directly
    system_warning: str | None = None
    try:
        result = await nginx_service.create_vhost(
            domain=body.domain_name,
            username=current_user.username,
            document_root=doc_root,
            php_version=body.php_version,
        )
        if result.get("warnings"):
            system_warning = "; ".join(result["warnings"])
    except Exception as exc:
        system_warning = f"Domain saved to DB but system setup failed: {exc}"

    # 3. Auto-create DNS zone for this domain
    try:
        from api.models.dns_zones import DnsZone
        existing_zone = await db.execute(
            select(DnsZone).where(DnsZone.zone_name == body.domain_name)
        )
        if existing_zone.scalar_one_or_none() is None:
            zone = DnsZone(
                user_id=current_user.id,
                domain_id=domain.id,
                zone_name=body.domain_name,
            )
            db.add(zone)
            await db.flush()
    except Exception:
        pass  # DNS zone creation is optional

    _log(db, request, current_user.id, "domains.create", f"Created domain {body.domain_name}")

    response = DomainResponse.model_validate(domain)
    if system_warning:
        # Attach warning as extra info -- DomainResponse will ignore unknown
        # fields via model_config, so we return a dict instead.
        resp_dict = response.model_dump()
        resp_dict["system_warning"] = system_warning
        return resp_dict
    return response


# --------------------------------------------------------------------------
# GET /{id} -- single domain detail
# --------------------------------------------------------------------------
@router.get("/{domain_id}", status_code=status.HTTP_200_OK)
async def get_domain(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found.")
    if not _is_admin(current_user) and domain.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return DomainResponse.model_validate(domain)


# --------------------------------------------------------------------------
# PUT /{id} -- update domain config
# --------------------------------------------------------------------------
@router.put("/{domain_id}", response_model=DomainResponse, status_code=status.HTTP_200_OK)
async def update_domain(
    domain_id: uuid.UUID,
    body: DomainUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    update_data = body.model_dump(exclude_unset=True)

    old_php = domain.php_version

    for field, value in update_data.items():
        setattr(domain, field, value)
    db.add(domain)
    await db.flush()

    # If PHP version changed, rewrite the nginx vhost
    new_php = update_data.get("php_version")
    if new_php and new_php != old_php:
        try:
            await nginx_service.update_vhost_php(
                domain=domain.domain_name,
                document_root=domain.document_root,
                new_php_version=new_php,
                ssl_enabled=domain.ssl_enabled,
                cert_path=domain.ssl_cert_path,
                key_path=domain.ssl_key_path,
            )
        except Exception:
            pass  # non-fatal; DB record is source of truth

    _log(db, request, current_user.id, "domains.update", f"Updated domain {domain.domain_name}")
    return DomainResponse.model_validate(domain)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete domain
# --------------------------------------------------------------------------
@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    # Remove nginx config and symlink directly
    try:
        await nginx_service.delete_vhost(domain.domain_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"System error deleting vhost: {exc}",
        )

    _log(db, request, current_user.id, "domains.delete", f"Deleted domain {domain.domain_name}")
    await db.delete(domain)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/enable-ssl -- trigger certbot directly
# --------------------------------------------------------------------------
@router.post("/{domain_id}/enable-ssl", response_model=DomainResponse, status_code=status.HTTP_200_OK)
async def enable_ssl(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    # 1. Run certbot
    try:
        cert_result = await nginx_service.issue_letsencrypt(
            domain.domain_name, current_user.email,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SSL issuance failed: {exc}",
        )

    cert_path = cert_result["cert_path"]
    key_path = cert_result["key_path"]

    # 2. Update nginx config with SSL
    try:
        await nginx_service.apply_ssl_to_nginx(
            domain=domain.domain_name,
            document_root=domain.document_root,
            php_version=domain.php_version,
            cert_path=cert_path,
            key_path=key_path,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SSL applied by certbot but nginx update failed: {exc}",
        )

    # 3. Update DB
    domain.ssl_enabled = True
    domain.ssl_cert_path = cert_path
    domain.ssl_key_path = key_path
    db.add(domain)
    await db.flush()

    _log(db, request, current_user.id, "domains.enable_ssl", f"SSL enabled for {domain.domain_name}")
    return DomainResponse.model_validate(domain)


# --------------------------------------------------------------------------
# GET /{id}/logs -- last 100 lines of nginx log (direct)
# --------------------------------------------------------------------------
@router.get("/{domain_id}/logs", status_code=status.HTTP_200_OK)
async def domain_logs(
    domain_id: uuid.UUID,
    log_type: str = Query("access", pattern="^(access|error)$"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    log_path = f"/var/log/nginx/{domain.domain_name}.{log_type}.log"
    try:
        content = await nginx_service.read_log_file(log_path, lines=100)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading logs: {exc}",
        )

    lines = content.strip().split("\n") if content else []
    return {"domain": domain.domain_name, "log_type": log_type, "lines": lines[-100:]}


# --------------------------------------------------------------------------
# GET /{id}/stats -- bandwidth, requests per day
# --------------------------------------------------------------------------
@router.get("/{domain_id}/stats", status_code=status.HTTP_200_OK)
async def domain_stats(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    # Basic stats from access log -- count lines for today
    log_path = f"/var/log/nginx/{domain.domain_name}.access.log"
    try:
        content = await nginx_service.read_log_file(log_path, lines=10000)
        lines = content.strip().split("\n") if content else []
        total_lines = len(lines)
    except Exception:
        total_lines = 0

    return {
        "domain": domain.domain_name,
        "bandwidth_bytes": 0,
        "requests_today": total_lines,
        "requests_30d": total_lines,
    }
