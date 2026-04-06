"""Directory Privacy router -- /api/v1/domains/{id}/directory-privacy.

Manages .htpasswd-based authentication for specific paths within a domain.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.directory_privacy import DirectoryPrivacy
from api.models.domains import Domain
from api.models.users import User
from api.schemas.directory_privacy import (
    DirectoryPrivacyCreate,
    DirectoryPrivacyResponse,
    DirectoryPrivacyUpdate,
    DirectoryPrivacyUserInfo,
    DirectoryUserAdd,
)
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


async def _get_dp_or_404(
    dp_id: uuid.UUID,
    domain_id: uuid.UUID,
    db: AsyncSession,
) -> DirectoryPrivacy:
    result = await db.execute(
        select(DirectoryPrivacy).where(
            DirectoryPrivacy.id == dp_id,
            DirectoryPrivacy.domain_id == domain_id,
        )
    )
    dp = result.scalar_one_or_none()
    if dp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Directory privacy rule not found.")
    return dp


def _parse_users(dp: DirectoryPrivacy) -> list[dict]:
    """Parse JSON users from the model."""
    try:
        return json.loads(dp.users or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def _to_response(dp: DirectoryPrivacy) -> DirectoryPrivacyResponse:
    users = _parse_users(dp)
    return DirectoryPrivacyResponse(
        id=dp.id,
        domain_id=dp.domain_id,
        path=dp.path,
        auth_name=dp.auth_name,
        users=[DirectoryPrivacyUserInfo(username=u["username"]) for u in users],
        user_count=len(users),
        is_active=dp.is_active,
        created_at=dp.created_at,
    )


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _normalize_path(path: str) -> str:
    """Normalize a directory path (must start with /)."""
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    # Remove trailing slash unless it's root
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return path


async def _sync_htpasswd_and_nginx(
    domain: Domain,
    db: AsyncSession,
) -> None:
    """Regenerate all .htpasswd files and nginx auth directives for the domain."""
    result = await db.execute(
        select(DirectoryPrivacy).where(DirectoryPrivacy.domain_id == domain.id)
    )
    rules = result.scalars().all()

    # Build list of active rules with their users
    active_rules = []
    for rule in rules:
        users = _parse_users(rule)
        if rule.is_active and users:
            active_rules.append({
                "path": rule.path,
                "auth_name": rule.auth_name,
                "users": users,
            })

    try:
        await nginx_service.sync_directory_privacy(
            domain=domain.domain_name,
            rules=active_rules,
            document_root=domain.document_root,
            php_version=domain.php_version,
            ssl_enabled=domain.ssl_enabled,
            cert_path=domain.ssl_cert_path,
            key_path=domain.ssl_key_path,
            template_name=domain.nginx_template or "default",
            custom_nginx_config=domain.custom_nginx_config,
            webserver=domain.webserver or "nginx",
            cache_enabled=domain.cache_enabled,
            cache_type=domain.cache_type,
            cache_ttl=domain.cache_ttl,
            cache_bypass_cookie=domain.cache_bypass_cookie,
        )
    except Exception:
        pass  # non-fatal; DB record is source of truth


# --------------------------------------------------------------------------
# GET /domains/{id}/directory-privacy -- list protected directories
# --------------------------------------------------------------------------
@router.get(
    "/domains/{domain_id}/directory-privacy",
    status_code=status.HTTP_200_OK,
)
async def list_directory_privacy(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    result = await db.execute(
        select(DirectoryPrivacy)
        .where(DirectoryPrivacy.domain_id == domain.id)
        .order_by(DirectoryPrivacy.created_at.desc())
    )
    rules = result.scalars().all()
    return {"items": [_to_response(r) for r in rules]}


# --------------------------------------------------------------------------
# POST /domains/{id}/directory-privacy -- protect a directory
# --------------------------------------------------------------------------
@router.post(
    "/domains/{domain_id}/directory-privacy",
    status_code=status.HTTP_201_CREATED,
)
async def create_directory_privacy(
    domain_id: uuid.UUID,
    body: DirectoryPrivacyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    normalized_path = _normalize_path(body.path)

    # Check if path is already protected
    existing = await db.execute(
        select(DirectoryPrivacy).where(
            DirectoryPrivacy.domain_id == domain.id,
            DirectoryPrivacy.path == normalized_path,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Path '{normalized_path}' is already protected.",
        )

    dp = DirectoryPrivacy(
        domain_id=domain.id,
        path=normalized_path,
        auth_name=body.auth_name,
        users="[]",
        is_active=True,
    )
    db.add(dp)
    await db.flush()

    _log(db, request, current_user.id, "directory_privacy.create",
         f"Protected directory {normalized_path} on {domain.domain_name}")

    return _to_response(dp)


# --------------------------------------------------------------------------
# PUT /domains/{id}/directory-privacy/{dp_id} -- update settings
# --------------------------------------------------------------------------
@router.put(
    "/domains/{domain_id}/directory-privacy/{dp_id}",
    status_code=status.HTTP_200_OK,
)
async def update_directory_privacy(
    domain_id: uuid.UUID,
    dp_id: uuid.UUID,
    body: DirectoryPrivacyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    dp = await _get_dp_or_404(dp_id, domain.id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(dp, field, value)
    db.add(dp)
    await db.flush()

    # Regenerate nginx config with updated rules
    await _sync_htpasswd_and_nginx(domain, db)

    _log(db, request, current_user.id, "directory_privacy.update",
         f"Updated directory privacy for {dp.path} on {domain.domain_name}")

    return _to_response(dp)


# --------------------------------------------------------------------------
# DELETE /domains/{id}/directory-privacy/{dp_id} -- remove protection
# --------------------------------------------------------------------------
@router.delete(
    "/domains/{domain_id}/directory-privacy/{dp_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_directory_privacy(
    domain_id: uuid.UUID,
    dp_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    dp = await _get_dp_or_404(dp_id, domain.id, db)

    path = dp.path
    await db.delete(dp)
    await db.flush()

    # Clean up htpasswd file and regenerate nginx config
    try:
        await nginx_service.remove_htpasswd_file(domain.domain_name, path)
    except Exception:
        pass
    await _sync_htpasswd_and_nginx(domain, db)

    _log(db, request, current_user.id, "directory_privacy.delete",
         f"Removed directory privacy for {path} on {domain.domain_name}")


# --------------------------------------------------------------------------
# POST /domains/{id}/directory-privacy/{dp_id}/users -- add user
# --------------------------------------------------------------------------
@router.post(
    "/domains/{domain_id}/directory-privacy/{dp_id}/users",
    status_code=status.HTTP_201_CREATED,
)
async def add_directory_user(
    domain_id: uuid.UUID,
    dp_id: uuid.UUID,
    body: DirectoryUserAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    dp = await _get_dp_or_404(dp_id, domain.id, db)

    users = _parse_users(dp)

    # Check for duplicate username
    for u in users:
        if u["username"] == body.username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User '{body.username}' already exists in this directory.",
            )

    # Generate password hash using apr1 (Apache MD5)
    password_hash = nginx_service.generate_htpasswd_hash(body.password)

    users.append({
        "username": body.username,
        "password_hash": password_hash,
    })
    dp.users = json.dumps(users)
    db.add(dp)
    await db.flush()

    # Regenerate htpasswd and nginx config
    await _sync_htpasswd_and_nginx(domain, db)

    _log(db, request, current_user.id, "directory_privacy.add_user",
         f"Added user '{body.username}' to {dp.path} on {domain.domain_name}")

    return _to_response(dp)


# --------------------------------------------------------------------------
# DELETE /domains/{id}/directory-privacy/{dp_id}/users/{username} -- remove user
# --------------------------------------------------------------------------
@router.delete(
    "/domains/{domain_id}/directory-privacy/{dp_id}/users/{username}",
    status_code=status.HTTP_200_OK,
)
async def remove_directory_user(
    domain_id: uuid.UUID,
    dp_id: uuid.UUID,
    username: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    domain = await _get_domain_or_404(domain_id, db, current_user)
    dp = await _get_dp_or_404(dp_id, domain.id, db)

    users = _parse_users(dp)
    new_users = [u for u in users if u["username"] != username]

    if len(new_users) == len(users):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )

    dp.users = json.dumps(new_users)
    db.add(dp)
    await db.flush()

    # Regenerate htpasswd and nginx config
    await _sync_htpasswd_and_nginx(domain, db)

    _log(db, request, current_user.id, "directory_privacy.remove_user",
         f"Removed user '{username}' from {dp.path} on {domain.domain_name}")

    return _to_response(dp)
