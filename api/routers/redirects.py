"""Redirects router -- /api/v1/domains/{domain_id}/redirects.

Manages URL redirects for a domain and regenerates nginx config on changes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.redirects import Redirect
from api.models.users import User
from api.schemas.redirects import RedirectCreate, RedirectResponse, RedirectUpdate
from api.services import nginx_service

router = APIRouter()

VALID_REDIRECT_TYPES = {301, 302, 307}


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


async def _regenerate_nginx_for_domain(domain: Domain, db: AsyncSession) -> list[str]:
    """Regenerate the nginx vhost with current redirect rules.

    Returns a list of warnings (empty on full success).
    """
    ws = domain.webserver or "nginx"
    if ws not in ("nginx", "nginx_apache"):
        return []

    # Fetch all active redirects for this domain
    result = await db.execute(
        select(Redirect)
        .where(Redirect.domain_id == domain.id, Redirect.is_active == True)  # noqa: E712
        .order_by(Redirect.created_at)
    )
    redirects = result.scalars().all()

    # Build redirect snippet
    redirect_lines: list[str] = []
    for r in redirects:
        if r.is_regex:
            redirect_lines.append(f"location ~ {r.source_path} {{ return {r.redirect_type} {r.destination_url}; }}")
        else:
            redirect_lines.append(f"location = {r.source_path} {{ return {r.redirect_type} {r.destination_url}; }}")

    redirect_snippet = "\n".join(redirect_lines) if redirect_lines else None

    # Merge with existing custom config
    custom_parts: list[str] = []
    # Strip any previously injected redirect block from custom_nginx_config
    existing_custom = domain.custom_nginx_config or ""
    cleaned = _strip_redirect_block(existing_custom)
    if cleaned.strip():
        custom_parts.append(cleaned.strip())
    if redirect_snippet:
        custom_parts.append(f"# -- HostHive Redirects (auto-managed) --\n{redirect_snippet}\n# -- End Redirects --")

    merged_custom = "\n\n".join(custom_parts) if custom_parts else None

    try:
        tpl = domain.nginx_template or "default"
        result = await nginx_service.update_vhost(
            domain=domain.domain_name,
            document_root=domain.document_root,
            php_version=domain.php_version,
            ssl_enabled=domain.ssl_enabled,
            cert_path=domain.ssl_cert_path,
            key_path=domain.ssl_key_path,
            template_name=tpl if ws == "nginx" else "proxy",
            custom_nginx_config=merged_custom,
            backend_port=8080,
            cache_enabled=domain.cache_enabled,
            cache_type=domain.cache_type,
            cache_ttl=domain.cache_ttl,
            cache_bypass_cookie=domain.cache_bypass_cookie,
        )
        return result.get("warnings", [])
    except Exception as exc:
        return [f"Nginx regeneration failed: {exc}"]


def _strip_redirect_block(config: str) -> str:
    """Remove the auto-managed redirect block from custom config."""
    lines = config.split("\n")
    out: list[str] = []
    inside_block = False
    for line in lines:
        if "# -- HostHive Redirects (auto-managed) --" in line:
            inside_block = True
            continue
        if "# -- End Redirects --" in line:
            inside_block = False
            continue
        if not inside_block:
            out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# GET /domains/{domain_id}/redirects -- list redirects
# --------------------------------------------------------------------------
@router.get(
    "/domains/{domain_id}/redirects",
    status_code=status.HTTP_200_OK,
)
async def list_redirects(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    result = await db.execute(
        select(Redirect)
        .where(Redirect.domain_id == domain.id)
        .order_by(Redirect.created_at.desc())
    )
    redirects = result.scalars().all()
    return {
        "items": [RedirectResponse.model_validate(r) for r in redirects],
        "total": len(redirects),
    }


# --------------------------------------------------------------------------
# POST /domains/{domain_id}/redirects -- create redirect
# --------------------------------------------------------------------------
@router.post(
    "/domains/{domain_id}/redirects",
    response_model=RedirectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_redirect(
    domain_id: uuid.UUID,
    body: RedirectCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    if body.redirect_type not in VALID_REDIRECT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid redirect type. Must be one of {sorted(VALID_REDIRECT_TYPES)}.",
        )

    redirect = Redirect(
        domain_id=domain.id,
        source_path=body.source_path,
        destination_url=body.destination_url,
        redirect_type=body.redirect_type,
        is_regex=body.is_regex,
        is_active=body.is_active,
    )
    db.add(redirect)
    await db.flush()

    # Regenerate nginx config
    warnings = await _regenerate_nginx_for_domain(domain, db)

    _log(db, request, current_user.id, "redirects.create", f"Created redirect {body.source_path} -> {body.destination_url} for {domain.domain_name}")

    resp = RedirectResponse.model_validate(redirect)
    if warnings:
        resp_dict = resp.model_dump()
        resp_dict["system_warnings"] = warnings
        return resp_dict
    return resp


# --------------------------------------------------------------------------
# PUT /domains/{domain_id}/redirects/{redirect_id} -- update redirect
# --------------------------------------------------------------------------
@router.put(
    "/domains/{domain_id}/redirects/{redirect_id}",
    response_model=RedirectResponse,
    status_code=status.HTTP_200_OK,
)
async def update_redirect(
    domain_id: uuid.UUID,
    redirect_id: uuid.UUID,
    body: RedirectUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    result = await db.execute(
        select(Redirect).where(Redirect.id == redirect_id, Redirect.domain_id == domain.id)
    )
    redirect = result.scalar_one_or_none()
    if redirect is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redirect not found.")

    update_data = body.model_dump(exclude_unset=True)

    if "redirect_type" in update_data and update_data["redirect_type"] not in VALID_REDIRECT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid redirect type. Must be one of {sorted(VALID_REDIRECT_TYPES)}.",
        )

    for field, value in update_data.items():
        setattr(redirect, field, value)
    db.add(redirect)
    await db.flush()

    # Regenerate nginx config
    warnings = await _regenerate_nginx_for_domain(domain, db)

    _log(db, request, current_user.id, "redirects.update", f"Updated redirect {redirect.source_path} for {domain.domain_name}")

    resp = RedirectResponse.model_validate(redirect)
    if warnings:
        resp_dict = resp.model_dump()
        resp_dict["system_warnings"] = warnings
        return resp_dict
    return resp


# --------------------------------------------------------------------------
# DELETE /domains/{domain_id}/redirects/{redirect_id} -- delete redirect
# --------------------------------------------------------------------------
@router.delete(
    "/domains/{domain_id}/redirects/{redirect_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_redirect(
    domain_id: uuid.UUID,
    redirect_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)

    result = await db.execute(
        select(Redirect).where(Redirect.id == redirect_id, Redirect.domain_id == domain.id)
    )
    redirect = result.scalar_one_or_none()
    if redirect is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redirect not found.")

    _log(db, request, current_user.id, "redirects.delete", f"Deleted redirect {redirect.source_path} for {domain.domain_name}")
    await db.delete(redirect)
    await db.flush()

    # Regenerate nginx config
    await _regenerate_nginx_for_domain(domain, db)
