"""Domains router -- /api/v1/domains."""

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

    doc_root = body.document_root or f"/home/{current_user.username}/{body.domain_name}/public_html"

    domain = Domain(
        user_id=current_user.id,
        domain_name=body.domain_name,
        document_root=doc_root,
        php_version=body.php_version,
    )
    db.add(domain)
    await db.flush()

    # Create vhost via agent
    agent = request.app.state.agent
    try:
        await agent.create_vhost(
            domain=body.domain_name,
            document_root=doc_root,
            php_version=body.php_version,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error creating vhost: {exc}",
        )

    _log(db, request, current_user.id, "domains.create", f"Created domain {body.domain_name}")
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

    for field, value in update_data.items():
        setattr(domain, field, value)
    db.add(domain)
    await db.flush()

    # Propagate config changes to agent
    agent = request.app.state.agent
    try:
        await agent.update_vhost(domain.domain_name, **update_data)
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

    agent = request.app.state.agent
    try:
        await agent.delete_vhost(domain.domain_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting vhost: {exc}",
        )

    _log(db, request, current_user.id, "domains.delete", f"Deleted domain {domain.domain_name}")
    await db.delete(domain)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/enable-ssl -- trigger certbot via agent
# --------------------------------------------------------------------------
@router.post("/{domain_id}/enable-ssl", response_model=DomainResponse, status_code=status.HTTP_200_OK)
async def enable_ssl(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    agent = request.app.state.agent

    try:
        result = await agent.issue_ssl(domain.domain_name, current_user.email)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error issuing SSL: {exc}",
        )

    domain.ssl_enabled = True
    domain.ssl_cert_path = result.get("cert_path")
    domain.ssl_key_path = result.get("key_path")
    db.add(domain)
    await db.flush()

    _log(db, request, current_user.id, "domains.enable_ssl", f"SSL enabled for {domain.domain_name}")
    return DomainResponse.model_validate(domain)


# --------------------------------------------------------------------------
# GET /{id}/logs -- last 100 lines of nginx log via agent
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
    agent = request.app.state.agent

    log_path = f"/var/log/nginx/{domain.domain_name}.{log_type}.log"
    try:
        result = await agent.read_file(log_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error reading logs: {exc}",
        )

    # Return last 100 lines
    content = result.get("content", "")
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
    agent = request.app.state.agent

    try:
        result = await agent._request(
            "GET",
            f"/vhost/{domain.domain_name}/stats",
        )
    except Exception:
        result = {}

    return {
        "domain": domain.domain_name,
        "bandwidth_bytes": result.get("bandwidth_bytes", 0),
        "requests_today": result.get("requests_today", 0),
        "requests_30d": result.get("requests_30d", 0),
    }
