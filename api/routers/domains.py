"""Domains router -- /api/v1/domains.

Webserver operations are dispatched to nginx_service, apache_service, or both
depending on the domain's ``webserver`` field (nginx | apache | nginx_apache).
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
from api.core.config import settings
from api.schemas.domains import (
    CacheUpdate,
    DomainCreate,
    DomainResponse,
    DomainUpdate,
    ErrorPagesUpdate,
    HotlinkUpdate,
    SubdomainCreate,
    SubdomainResponse,
    SubdomainUpdate,
)
from api.services import apache_service, nginx_service

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
# GET /templates -- list available nginx templates
# --------------------------------------------------------------------------
@router.get("/templates", status_code=status.HTTP_200_OK)
async def get_nginx_templates(
    current_user: User = Depends(get_current_user),
):
    """Return the list of available nginx vhost templates."""
    return {"templates": nginx_service.list_templates()}


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
    # Only list top-level domains (not subdomains)
    query = select(Domain).where(Domain.is_subdomain.is_(False))
    count_query = select(func.count()).select_from(Domain).where(Domain.is_subdomain.is_(False))
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
    ws = body.webserver.value if hasattr(body.webserver, "value") else body.webserver

    tpl = body.nginx_template.value if hasattr(body.nginx_template, "value") else (body.nginx_template or "default")

    # 1. Save to DB first
    domain = Domain(
        user_id=current_user.id,
        domain_name=body.domain_name,
        document_root=doc_root,
        php_version=body.php_version,
        webserver=ws,
        nginx_template=tpl,
        custom_nginx_config=body.custom_nginx_config,
    )
    db.add(domain)
    await db.flush()

    # 2. Create webserver vhost(s) based on the chosen mode
    system_warning: str | None = None
    try:
        all_warnings: list[str] = []

        if ws == "nginx":
            result = await nginx_service.create_vhost(
                domain=body.domain_name,
                username=current_user.username,
                document_root=doc_root,
                php_version=body.php_version,
                template_name=tpl,
                custom_nginx_config=body.custom_nginx_config,
            )
            all_warnings.extend(result.get("warnings", []))

        elif ws == "apache":
            result = await apache_service.create_vhost(
                domain=body.domain_name,
                username=current_user.username,
                document_root=doc_root,
                php_version=body.php_version,
            )
            all_warnings.extend(result.get("warnings", []))

        elif ws == "nginx_apache":
            # Apache on port 8080 handles PHP / .htaccess
            apache_result = await apache_service.create_vhost_proxy_mode(
                domain=body.domain_name,
                username=current_user.username,
                document_root=doc_root,
                php_version=body.php_version,
            )
            all_warnings.extend(apache_result.get("warnings", []))

            # Nginx on port 80/443 reverse-proxies to Apache 8080
            nginx_result = await nginx_service.create_vhost(
                domain=body.domain_name,
                username=current_user.username,
                document_root=doc_root,
                php_version=body.php_version,
                template_name="proxy",
                custom_nginx_config=body.custom_nginx_config,
                backend_port=8080,
            )
            all_warnings.extend(nginx_result.get("warnings", []))

        if all_warnings:
            system_warning = "; ".join(all_warnings)
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

    # Normalize enum values to plain strings for DB storage
    if "nginx_template" in update_data and update_data["nginx_template"] is not None:
        v = update_data["nginx_template"]
        update_data["nginx_template"] = v.value if hasattr(v, "value") else v

    old_php = domain.php_version
    old_template = domain.nginx_template
    old_custom = domain.custom_nginx_config

    for field, value in update_data.items():
        setattr(domain, field, value)
    db.add(domain)
    await db.flush()

    # Determine if the nginx vhost needs to be regenerated
    new_php = update_data.get("php_version")
    new_template = update_data.get("nginx_template")
    new_custom = update_data.get("custom_nginx_config")
    needs_regen = (
        (new_php and new_php != old_php)
        or (new_template is not None and new_template != old_template)
        or ("custom_nginx_config" in update_data and new_custom != old_custom)
    )

    ws = domain.webserver or "nginx"
    if needs_regen:
        try:
            tpl = domain.nginx_template or "default"
            if ws in ("nginx", "nginx_apache"):
                await nginx_service.update_vhost(
                    domain=domain.domain_name,
                    document_root=domain.document_root,
                    php_version=domain.php_version,
                    ssl_enabled=domain.ssl_enabled,
                    cert_path=domain.ssl_cert_path,
                    key_path=domain.ssl_key_path,
                    template_name=tpl if ws == "nginx" else "proxy",
                    custom_nginx_config=domain.custom_nginx_config,
                    backend_port=8080,
                )
            if ws in ("apache", "nginx_apache"):
                await apache_service.update_vhost_php(
                    domain=domain.domain_name,
                    document_root=domain.document_root,
                    new_php_version=domain.php_version,
                    ssl_enabled=domain.ssl_enabled if ws == "apache" else False,
                    cert_path=domain.ssl_cert_path if ws == "apache" else None,
                    key_path=domain.ssl_key_path if ws == "apache" else None,
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

    # Remove webserver config(s) based on the domain's webserver type
    ws = domain.webserver or "nginx"
    try:
        if ws in ("nginx", "nginx_apache"):
            await nginx_service.delete_vhost(domain.domain_name)
        if ws in ("apache", "nginx_apache"):
            await apache_service.delete_vhost(domain.domain_name)
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
    ws = domain.webserver or "nginx"

    # 1. Run certbot (use the plugin matching the front-facing webserver)
    try:
        if ws == "apache":
            cert_result = await apache_service.issue_letsencrypt(
                domain.domain_name, current_user.email,
            )
        else:
            # nginx or nginx_apache -- nginx terminates SSL in both cases
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

    # 2. Update webserver config with SSL
    try:
        if ws == "apache":
            await apache_service.apply_ssl(
                domain=domain.domain_name,
                document_root=domain.document_root,
                php_version=domain.php_version,
                cert_path=cert_path,
                key_path=key_path,
            )
        else:
            tpl = domain.nginx_template or "default"
            await nginx_service.apply_ssl_to_nginx(
                domain=domain.domain_name,
                document_root=domain.document_root,
                php_version=domain.php_version,
                cert_path=cert_path,
                key_path=key_path,
                template_name=tpl if ws == "nginx" else "proxy",
                custom_nginx_config=domain.custom_nginx_config,
                backend_port=8080,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SSL applied by certbot but webserver update failed: {exc}",
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
# PUT /{id}/cache -- enable/disable/configure cache
# --------------------------------------------------------------------------
@router.put("/{domain_id}/cache", response_model=DomainResponse, status_code=status.HTTP_200_OK)
async def update_cache(
    domain_id: uuid.UUID,
    body: CacheUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    update_data = body.model_dump(exclude_unset=True)

    # Normalize enum values
    if "cache_type" in update_data and update_data["cache_type"] is not None:
        v = update_data["cache_type"]
        update_data["cache_type"] = v.value if hasattr(v, "value") else v

    for field, value in update_data.items():
        setattr(domain, field, value)
    db.add(domain)
    await db.flush()

    # Regenerate nginx vhost with updated cache settings
    ws = domain.webserver or "nginx"
    if ws in ("nginx", "nginx_apache"):
        try:
            tpl = domain.nginx_template or "default"
            await nginx_service.update_vhost(
                domain=domain.domain_name,
                document_root=domain.document_root,
                php_version=domain.php_version,
                ssl_enabled=domain.ssl_enabled,
                cert_path=domain.ssl_cert_path,
                key_path=domain.ssl_key_path,
                template_name=tpl if ws == "nginx" else "proxy",
                custom_nginx_config=domain.custom_nginx_config,
                backend_port=8080,
                cache_enabled=domain.cache_enabled,
                cache_type=domain.cache_type,
                cache_ttl=domain.cache_ttl,
                cache_bypass_cookie=domain.cache_bypass_cookie,
            )
        except Exception:
            pass  # non-fatal; DB record is source of truth

    _log(db, request, current_user.id, "domains.cache_update", f"Cache settings updated for {domain.domain_name}")
    return DomainResponse.model_validate(domain)


# --------------------------------------------------------------------------
# POST /{id}/cache/purge -- purge cache for domain
# --------------------------------------------------------------------------
@router.post("/{domain_id}/cache/purge", status_code=status.HTTP_200_OK)
async def purge_cache(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    if not domain.cache_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Caching is not enabled for this domain.",
        )

    try:
        result = await nginx_service.purge_cache(domain.domain_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to purge cache: {exc}",
        )

    _log(db, request, current_user.id, "domains.cache_purge", f"Cache purged for {domain.domain_name}")
    return {"ok": True, "domain": domain.domain_name, "warnings": result.get("warnings", [])}


# --------------------------------------------------------------------------
# GET /{id}/hotlink -- get hotlink protection settings
# --------------------------------------------------------------------------
@router.get("/{domain_id}/hotlink", status_code=status.HTTP_200_OK)
async def get_hotlink(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    return {
        "hotlink_protection": domain.hotlink_protection,
        "hotlink_allowed_domains": domain.hotlink_allowed_domains,
        "hotlink_extensions": domain.hotlink_extensions,
        "hotlink_redirect_url": domain.hotlink_redirect_url,
    }


# --------------------------------------------------------------------------
# PUT /{id}/hotlink -- enable/configure hotlink protection
# --------------------------------------------------------------------------
@router.put("/{domain_id}/hotlink", response_model=DomainResponse, status_code=status.HTTP_200_OK)
async def update_hotlink(
    domain_id: uuid.UUID,
    body: HotlinkUpdate,
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

    # Regenerate nginx vhost with updated hotlink settings
    ws = domain.webserver or "nginx"
    if ws in ("nginx", "nginx_apache"):
        try:
            tpl = domain.nginx_template or "default"
            await nginx_service.update_vhost(
                domain=domain.domain_name,
                document_root=domain.document_root,
                php_version=domain.php_version,
                ssl_enabled=domain.ssl_enabled,
                cert_path=domain.ssl_cert_path,
                key_path=domain.ssl_key_path,
                template_name=tpl if ws == "nginx" else "proxy",
                custom_nginx_config=domain.custom_nginx_config,
                backend_port=8080,
                cache_enabled=domain.cache_enabled,
                cache_type=domain.cache_type,
                cache_ttl=domain.cache_ttl,
                cache_bypass_cookie=domain.cache_bypass_cookie,
                hotlink_protection=domain.hotlink_protection,
                hotlink_allowed_domains=domain.hotlink_allowed_domains,
                hotlink_extensions=domain.hotlink_extensions,
                hotlink_redirect_url=domain.hotlink_redirect_url,
            )
        except Exception:
            pass  # non-fatal; DB record is source of truth

    _log(db, request, current_user.id, "domains.hotlink_update", f"Hotlink protection updated for {domain.domain_name}")
    return DomainResponse.model_validate(domain)


# --------------------------------------------------------------------------
# GET /{id}/error-pages -- get current error page config
# --------------------------------------------------------------------------
@router.get("/{domain_id}/error-pages", status_code=status.HTTP_200_OK)
async def get_error_pages(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    return {
        "domain": domain.domain_name,
        "error_pages": domain.custom_error_pages or {},
    }


# --------------------------------------------------------------------------
# PUT /{id}/error-pages -- update error pages
# --------------------------------------------------------------------------
@router.put("/{domain_id}/error-pages", status_code=status.HTTP_200_OK)
async def update_error_pages(
    domain_id: uuid.UUID,
    body: ErrorPagesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    # Store as string-keyed dict for JSON compatibility; nginx templates
    # will iterate over the mapping.
    error_pages = {str(code): page for code, page in body.error_pages.items()} if body.error_pages else None
    domain.custom_error_pages = error_pages
    db.add(domain)
    await db.flush()

    # Regenerate nginx vhost with updated error pages
    ws = domain.webserver or "nginx"
    if ws in ("nginx", "nginx_apache"):
        try:
            tpl = domain.nginx_template or "default"
            await nginx_service.update_vhost(
                domain=domain.domain_name,
                document_root=domain.document_root,
                php_version=domain.php_version,
                ssl_enabled=domain.ssl_enabled,
                cert_path=domain.ssl_cert_path,
                key_path=domain.ssl_key_path,
                template_name=tpl if ws == "nginx" else "proxy",
                custom_nginx_config=domain.custom_nginx_config,
                backend_port=8080,
                cache_enabled=domain.cache_enabled,
                cache_type=domain.cache_type,
                cache_ttl=domain.cache_ttl,
                cache_bypass_cookie=domain.cache_bypass_cookie,
                custom_error_pages=domain.custom_error_pages,
            )
        except Exception:
            pass  # non-fatal; DB record is source of truth

    _log(db, request, current_user.id, "domains.error_pages_update", f"Error pages updated for {domain.domain_name}")
    return {
        "domain": domain.domain_name,
        "error_pages": domain.custom_error_pages or {},
    }


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
    ws = domain.webserver or "nginx"

    # Choose log directory based on the front-facing webserver
    if ws == "apache":
        log_path = f"/var/log/apache2/{domain.domain_name}.{log_type}.log"
        reader = apache_service.read_log_file
    else:
        log_path = f"/var/log/nginx/{domain.domain_name}.{log_type}.log"
        reader = nginx_service.read_log_file

    try:
        content = await reader(log_path, lines=100)
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


# ==========================================================================
# Subdomain management
# ==========================================================================


# --------------------------------------------------------------------------
# GET /{id}/subdomains -- list subdomains for a domain
# --------------------------------------------------------------------------
@router.get("/{domain_id}/subdomains", status_code=status.HTTP_200_OK)
async def list_subdomains(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all subdomains belonging to the given parent domain."""
    parent = await _get_domain_or_404(domain_id, db, current_user)

    result = await db.execute(
        select(Domain)
        .where(Domain.parent_domain_id == parent.id, Domain.is_subdomain.is_(True))
        .order_by(Domain.created_at.desc())
    )
    subs = result.scalars().all()

    return {
        "items": [SubdomainResponse.model_validate(s) for s in subs],
        "total": len(subs),
    }


# --------------------------------------------------------------------------
# POST /{id}/subdomains -- create a subdomain
# --------------------------------------------------------------------------
@router.post(
    "/{domain_id}/subdomains",
    response_model=SubdomainResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subdomain(
    domain_id: uuid.UUID,
    body: SubdomainCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a subdomain under an existing parent domain.

    This creates an nginx vhost, a DNS A record pointing to the server IP,
    and optionally issues an SSL certificate.
    """
    parent = await _get_domain_or_404(domain_id, db, current_user)

    # Prevent creating subdomains of subdomains
    if parent.is_subdomain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create a subdomain of a subdomain.",
        )

    fqdn = f"{body.subdomain_prefix}.{parent.domain_name}"

    # Check uniqueness
    existing = await db.execute(select(Domain).where(Domain.domain_name == fqdn))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Subdomain '{fqdn}' already exists.",
        )

    doc_root = body.document_root or f"/home/{current_user.username}/web/{parent.domain_name}/subdomains/{body.subdomain_prefix}/public_html"
    ws = parent.webserver or "nginx"

    # 1. Save to DB
    subdomain = Domain(
        user_id=current_user.id,
        domain_name=fqdn,
        document_root=doc_root,
        php_version=body.php_version,
        webserver=ws,
        nginx_template=parent.nginx_template or "default",
        parent_domain_id=parent.id,
        is_subdomain=True,
    )
    db.add(subdomain)
    await db.flush()

    # 2. Create webserver vhost
    system_warning: str | None = None
    try:
        tpl = parent.nginx_template or "default"
        if ws in ("nginx", "nginx_apache"):
            result = await nginx_service.create_vhost(
                domain=fqdn,
                username=current_user.username,
                document_root=doc_root,
                php_version=body.php_version,
                template_name=tpl if ws == "nginx" else "proxy",
                backend_port=8080,
            )
        elif ws == "apache":
            result = await apache_service.create_vhost(
                domain=fqdn,
                username=current_user.username,
                document_root=doc_root,
                php_version=body.php_version,
            )
        else:
            result = {"warnings": []}
    except Exception as exc:
        system_warning = f"Subdomain saved but vhost creation failed: {exc}"

    # 3. Auto-create DNS A record pointing to server IP
    try:
        from api.models.dns_zones import DnsZone
        from api.models.dns_records import DnsRecord

        zone_result = await db.execute(
            select(DnsZone).where(DnsZone.zone_name == parent.domain_name)
        )
        zone = zone_result.scalar_one_or_none()
        if zone:
            # Check if A record already exists
            existing_record = await db.execute(
                select(DnsRecord).where(
                    DnsRecord.zone_id == zone.id,
                    DnsRecord.record_type == "A",
                    DnsRecord.name == body.subdomain_prefix,
                )
            )
            if existing_record.scalar_one_or_none() is None:
                dns_record = DnsRecord(
                    zone_id=zone.id,
                    record_type="A",
                    name=body.subdomain_prefix,
                    value=settings.server_ip,
                    ttl=3600,
                )
                db.add(dns_record)
                await db.flush()
    except Exception:
        pass  # DNS record creation is optional / best-effort

    # 4. Optionally issue SSL
    if body.enable_ssl:
        try:
            cert_result = await nginx_service.issue_letsencrypt(fqdn, current_user.email)
            subdomain.ssl_enabled = True
            subdomain.ssl_cert_path = cert_result["cert_path"]
            subdomain.ssl_key_path = cert_result["key_path"]

            tpl = parent.nginx_template or "default"
            await nginx_service.apply_ssl_to_nginx(
                domain=fqdn,
                document_root=doc_root,
                php_version=body.php_version,
                cert_path=cert_result["cert_path"],
                key_path=cert_result["key_path"],
                template_name=tpl if ws == "nginx" else "proxy",
                backend_port=8080,
            )
            db.add(subdomain)
            await db.flush()
        except Exception as exc:
            if system_warning:
                system_warning += f"; SSL issuance failed: {exc}"
            else:
                system_warning = f"Subdomain created but SSL issuance failed: {exc}"

    _log(db, request, current_user.id, "subdomains.create", f"Created subdomain {fqdn}")

    response = SubdomainResponse.model_validate(subdomain)
    if system_warning:
        resp_dict = response.model_dump()
        resp_dict["system_warning"] = system_warning
        return resp_dict
    return response


# --------------------------------------------------------------------------
# PUT /{id}/subdomains/{sub_id} -- update subdomain
# --------------------------------------------------------------------------
@router.put(
    "/{domain_id}/subdomains/{sub_id}",
    response_model=SubdomainResponse,
    status_code=status.HTTP_200_OK,
)
async def update_subdomain(
    domain_id: uuid.UUID,
    sub_id: uuid.UUID,
    body: SubdomainUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a subdomain's document root or PHP version."""
    parent = await _get_domain_or_404(domain_id, db, current_user)

    result = await db.execute(
        select(Domain).where(
            Domain.id == sub_id,
            Domain.parent_domain_id == parent.id,
            Domain.is_subdomain.is_(True),
        )
    )
    subdomain = result.scalar_one_or_none()
    if subdomain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdomain not found.")

    update_data = body.model_dump(exclude_unset=True)
    old_php = subdomain.php_version

    for field, value in update_data.items():
        setattr(subdomain, field, value)
    db.add(subdomain)
    await db.flush()

    # Regenerate nginx vhost if PHP version or document root changed
    needs_regen = (
        update_data.get("php_version") and update_data["php_version"] != old_php
    ) or "document_root" in update_data

    ws = subdomain.webserver or "nginx"
    if needs_regen and ws in ("nginx", "nginx_apache"):
        try:
            tpl = subdomain.nginx_template or "default"
            await nginx_service.update_vhost(
                domain=subdomain.domain_name,
                document_root=subdomain.document_root,
                php_version=subdomain.php_version,
                ssl_enabled=subdomain.ssl_enabled,
                cert_path=subdomain.ssl_cert_path,
                key_path=subdomain.ssl_key_path,
                template_name=tpl if ws == "nginx" else "proxy",
                backend_port=8080,
            )
        except Exception:
            pass  # non-fatal

    _log(db, request, current_user.id, "subdomains.update", f"Updated subdomain {subdomain.domain_name}")
    return SubdomainResponse.model_validate(subdomain)


# --------------------------------------------------------------------------
# DELETE /{id}/subdomains/{sub_id} -- remove subdomain
# --------------------------------------------------------------------------
@router.delete(
    "/{domain_id}/subdomains/{sub_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_subdomain(
    domain_id: uuid.UUID,
    sub_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a subdomain, its vhost, and its DNS A record."""
    parent = await _get_domain_or_404(domain_id, db, current_user)

    result = await db.execute(
        select(Domain).where(
            Domain.id == sub_id,
            Domain.parent_domain_id == parent.id,
            Domain.is_subdomain.is_(True),
        )
    )
    subdomain = result.scalar_one_or_none()
    if subdomain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdomain not found.")

    # 1. Remove vhost
    ws = subdomain.webserver or "nginx"
    try:
        if ws in ("nginx", "nginx_apache"):
            await nginx_service.delete_vhost(subdomain.domain_name)
        if ws in ("apache", "nginx_apache"):
            await apache_service.delete_vhost(subdomain.domain_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"System error deleting subdomain vhost: {exc}",
        )

    # 2. Remove DNS A record (best-effort)
    try:
        from api.models.dns_zones import DnsZone
        from api.models.dns_records import DnsRecord

        # Extract the prefix from the FQDN
        prefix = subdomain.domain_name.replace(f".{parent.domain_name}", "")

        zone_result = await db.execute(
            select(DnsZone).where(DnsZone.zone_name == parent.domain_name)
        )
        zone = zone_result.scalar_one_or_none()
        if zone:
            record_result = await db.execute(
                select(DnsRecord).where(
                    DnsRecord.zone_id == zone.id,
                    DnsRecord.record_type == "A",
                    DnsRecord.name == prefix,
                )
            )
            record = record_result.scalar_one_or_none()
            if record:
                await db.delete(record)
    except Exception:
        pass  # DNS cleanup is best-effort

    _log(db, request, current_user.id, "subdomains.delete", f"Deleted subdomain {subdomain.domain_name}")
    await db.delete(subdomain)
    await db.flush()
