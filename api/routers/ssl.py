"""SSL certificates router -- /api/v1/ssl.

All certbot and file operations are performed directly via nginx_service (no agent).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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
from api.services import nginx_service

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
# POST /issue/{domain_id} -- issue Let's Encrypt cert (direct certbot)
# --------------------------------------------------------------------------
@router.post("/issue/{domain_id}", response_model=SslCertificateResponse, status_code=status.HTTP_201_CREATED)
async def issue_certificate(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_for_user(domain_id, db, current_user)

    # 1. Save cert record to DB first
    cert = SSLCertificate(
        domain_id=domain.id,
        domain_name=domain.domain_name,
        provider=CertProvider.LETS_ENCRYPT,
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        auto_renew=True,
        last_renewed_at=datetime.now(timezone.utc),
    )
    db.add(cert)
    await db.flush()

    # 2. Run certbot directly
    system_warning: str | None = None
    try:
        cert_result = await nginx_service.issue_letsencrypt(
            domain.domain_name, current_user.email,
        )
        cert.cert_path = cert_result["cert_path"]
        cert.key_path = cert_result["key_path"]
    except Exception as exc:
        system_warning = f"Certificate saved to DB but certbot failed: {exc}"
        # Set fallback paths so DB record is consistent
        cert.cert_path = f"/etc/letsencrypt/live/{domain.domain_name}/fullchain.pem"
        cert.key_path = f"/etc/letsencrypt/live/{domain.domain_name}/privkey.pem"
        db.add(cert)
        await db.flush()

        # Update domain SSL status even on failure (DB is source of truth)
        domain.ssl_enabled = False
        domain.ssl_cert_path = cert.cert_path
        domain.ssl_key_path = cert.key_path
        db.add(domain)
        await db.flush()

        _log(db, request, current_user.id, "ssl.issue", f"SSL issue attempted for {domain.domain_name} (certbot failed)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SSL issuance failed: {exc}",
        )

    # 3. Update nginx config with SSL
    try:
        await nginx_service.apply_ssl_to_nginx(
            domain=domain.domain_name,
            document_root=domain.document_root,
            php_version=domain.php_version,
            cert_path=cert.cert_path,
            key_path=cert.key_path,
        )
    except Exception as exc:
        system_warning = f"Certificate issued but nginx SSL update failed: {exc}"

    # 4. Update domain record
    domain.ssl_enabled = True
    domain.ssl_cert_path = cert.cert_path
    domain.ssl_key_path = cert.key_path
    db.add(domain)
    db.add(cert)
    await db.flush()

    _log(db, request, current_user.id, "ssl.issue", f"Issued LE cert for {domain.domain_name}")
    return SslCertificateResponse.model_validate(cert)


# --------------------------------------------------------------------------
# POST /install/{domain_id} -- upload custom cert (direct file write)
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

    # 1. Save cert record to DB first
    cert = SSLCertificate(
        domain_id=domain.id,
        domain_name=domain.domain_name,
        provider=CertProvider.CUSTOM,
        auto_renew=False,
    )
    db.add(cert)
    await db.flush()

    # 2. Write cert and key to /etc/ssl/hosthive/{domain}/
    try:
        file_result = await nginx_service.install_custom_ssl(
            domain=domain.domain_name,
            certificate=body.certificate,
            private_key=body.private_key,
            chain=body.chain,
        )
        cert.cert_path = file_result["cert_path"]
        cert.key_path = file_result["key_path"]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save certificate files: {exc}",
        )

    # 3. Update nginx config with SSL
    try:
        await nginx_service.apply_ssl_to_nginx(
            domain=domain.domain_name,
            document_root=domain.document_root,
            php_version=domain.php_version,
            cert_path=cert.cert_path,
            key_path=cert.key_path,
        )
    except Exception as exc:
        # Non-fatal: files are saved, nginx just needs manual reload
        pass

    # 4. Update domain record
    domain.ssl_enabled = True
    domain.ssl_cert_path = cert.cert_path
    domain.ssl_key_path = cert.key_path
    db.add(domain)
    db.add(cert)
    await db.flush()

    _log(db, request, current_user.id, "ssl.install_custom", f"Installed custom cert for {domain.domain_name}")
    return SslCertificateResponse.model_validate(cert)


# --------------------------------------------------------------------------
# POST /renew/{domain_id} -- renew cert (direct certbot)
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

    # Run certbot directly to renew
    try:
        cert_result = await nginx_service.issue_letsencrypt(
            domain.domain_name, current_user.email,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Certificate renewal failed: {exc}",
        )

    # Update nginx config with (potentially new) cert paths
    try:
        await nginx_service.apply_ssl_to_nginx(
            domain=domain.domain_name,
            document_root=domain.document_root,
            php_version=domain.php_version,
            cert_path=cert_result["cert_path"],
            key_path=cert_result["key_path"],
        )
    except Exception:
        pass  # Non-fatal: cert renewed, nginx may need manual reload

    # Update DB records
    cert.cert_path = cert_result["cert_path"]
    cert.key_path = cert_result["key_path"]
    cert.expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    cert.last_renewed_at = datetime.now(timezone.utc)
    db.add(cert)

    domain.ssl_cert_path = cert_result["cert_path"]
    domain.ssl_key_path = cert_result["key_path"]
    db.add(domain)
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
