"""SSL certificates router -- /api/v1/ssl."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.ssl_certificates import CertProvider, SSLCertificate
from api.models.users import User
from api.schemas.ssl import CustomCertInstall, SslCertificateResponse

router = APIRouter()


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_domain_for_user(
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
# GET / -- list all certs with expiry
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_certificates(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(SSLCertificate)
    count_query = select(func.count()).select_from(SSLCertificate)

    if not _is_admin(current_user):
        # Filter by domains owned by user
        user_domain_ids = select(Domain.id).where(Domain.user_id == current_user.id)
        query = query.where(SSLCertificate.domain_id.in_(user_domain_ids))
        count_query = count_query.where(SSLCertificate.domain_id.in_(user_domain_ids))

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(
        query.order_by(SSLCertificate.expires_at.asc().nullslast()).offset(skip).limit(limit)
    )).scalars().all()

    return {
        "items": [SslCertificateResponse.model_validate(c) for c in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST /issue/{domain_id} -- issue Let's Encrypt cert
# --------------------------------------------------------------------------
@router.post("/issue/{domain_id}", response_model=SslCertificateResponse, status_code=status.HTTP_201_CREATED)
async def issue_certificate(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_for_user(domain_id, db, current_user)
    agent = request.app.state.agent

    try:
        result = await agent.issue_ssl(domain.domain_name, current_user.email)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            try:
                body = exc.response.json()
                detail = body.get("detail", body.get("error", str(exc)))
            except Exception:
                detail = exc.response.text or str(exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SSL issuance failed: {detail}",
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error issuing SSL: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error issuing SSL: {exc}",
        )

    cert = SSLCertificate(
        domain_id=domain.id,
        domain_name=domain.domain_name,
        provider=CertProvider.LETS_ENCRYPT,
        cert_path=result.get("cert_path"),
        key_path=result.get("key_path"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        auto_renew=True,
        last_renewed_at=datetime.now(timezone.utc),
    )
    db.add(cert)

    # Update domain SSL status
    domain.ssl_enabled = True
    domain.ssl_cert_path = cert.cert_path
    domain.ssl_key_path = cert.key_path
    db.add(domain)
    await db.flush()

    _log(db, request, current_user.id, "ssl.issue", f"Issued LE cert for {domain.domain_name}")
    return SslCertificateResponse.model_validate(cert)


# --------------------------------------------------------------------------
# POST /install/{domain_id} -- upload custom cert
# --------------------------------------------------------------------------
@router.post("/install/{domain_id}", response_model=SslCertificateResponse, status_code=status.HTTP_201_CREATED)
async def install_custom_certificate(
    domain_id: uuid.UUID,
    body: CustomCertInstall,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_for_user(domain_id, db, current_user)
    agent = request.app.state.agent

    try:
        result = await agent.install_custom_ssl(
            domain.domain_name,
            body.certificate,
            body.private_key,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error installing cert: {exc}",
        )

    cert = SSLCertificate(
        domain_id=domain.id,
        domain_name=domain.domain_name,
        provider=CertProvider.CUSTOM,
        cert_path=result.get("cert_path"),
        key_path=result.get("key_path"),
        auto_renew=False,
    )
    db.add(cert)

    domain.ssl_enabled = True
    domain.ssl_cert_path = cert.cert_path
    domain.ssl_key_path = cert.key_path
    db.add(domain)
    await db.flush()

    _log(db, request, current_user.id, "ssl.install_custom", f"Installed custom cert for {domain.domain_name}")
    return SslCertificateResponse.model_validate(cert)


# --------------------------------------------------------------------------
# POST /renew/{domain_id} -- renew cert via agent
# --------------------------------------------------------------------------
@router.post("/renew/{domain_id}", response_model=SslCertificateResponse, status_code=status.HTTP_200_OK)
async def renew_certificate(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_for_user(domain_id, db, current_user)

    # Find existing cert
    result = await db.execute(
        select(SSLCertificate).where(SSLCertificate.domain_id == domain_id)
        .order_by(SSLCertificate.created_at.desc())
    )
    cert = result.scalar_one_or_none()
    if cert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No certificate found for this domain.",
        )

    agent = request.app.state.agent
    try:
        await agent.issue_ssl(domain.domain_name, current_user.email)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error renewing cert: {exc}",
        )

    cert.expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    cert.last_renewed_at = datetime.now(timezone.utc)
    db.add(cert)
    await db.flush()

    _log(db, request, current_user.id, "ssl.renew", f"Renewed cert for {domain.domain_name}")
    return SslCertificateResponse.model_validate(cert)


# --------------------------------------------------------------------------
# GET /expiring -- certs expiring in < 30 days
# --------------------------------------------------------------------------
@router.get("/expiring", status_code=status.HTTP_200_OK)
async def expiring_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    threshold = datetime.now(timezone.utc) + timedelta(days=30)
    query = select(SSLCertificate).where(
        SSLCertificate.expires_at.isnot(None),
        SSLCertificate.expires_at < threshold,
    )

    if not _is_admin(current_user):
        user_domain_ids = select(Domain.id).where(Domain.user_id == current_user.id)
        query = query.where(SSLCertificate.domain_id.in_(user_domain_ids))

    results = (await db.execute(query.order_by(SSLCertificate.expires_at.asc()))).scalars().all()

    return {
        "items": [SslCertificateResponse.model_validate(c) for c in results],
        "total": len(results),
    }
