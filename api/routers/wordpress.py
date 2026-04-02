"""WordPress router -- /api/v1/wordpress.

Manage WordPress installations: detect, inspect, update, clone, migrate, and
run security checks.  All heavy operations are delegated to the agent's
wordpress_executor.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.users import User
from api.schemas.wordpress import (
    WPBackupResult,
    WPCloneRequest,
    WPCloneResult,
    WPInstallInfo,
    WPSearchReplaceRequest,
    WPSearchReplaceResult,
    WPSecurityReport,
    WPSiteInfo,
    WPUpdateResult,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _resolve_wp_path(domain: str, current_user: User) -> str:
    """Resolve the WordPress path for a domain.

    Tries common document root patterns under /home/<username>/.
    """
    username = current_user.username
    candidates = [
        f"/home/{username}/web/{domain}/public_html",
        f"/home/{username}/{domain}/public_html",
        f"/home/{username}/web/{domain}",
    ]

    for path in candidates:
        wp_config = os.path.join(path, "wp-config.php")
        if os.path.isfile(wp_config):
            return path

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"WordPress installation not found for domain {domain}",
    )


def _check_domain_access(domain: str, current_user: User) -> None:
    """Ensure the user has access to this domain (basic path-based check)."""
    if _is_admin(current_user):
        return
    # Non-admin users can only access their own home directories
    username = current_user.username
    allowed_prefix = f"/home/{username}/"
    path = _resolve_wp_path(domain, current_user)
    resolved = os.path.realpath(path)
    if not resolved.startswith(allowed_prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )


# ---------------------------------------------------------------------------
# GET / — list detected WordPress installations
# ---------------------------------------------------------------------------

@router.get("/", status_code=status.HTTP_200_OK)
async def list_wordpress_installs(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    from agent.executors import wordpress_executor

    try:
        installs = wordpress_executor.detect_wordpress_installs()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to detect WordPress installs: {exc}",
        )

    # Filter to current user's installs unless admin
    if not _is_admin(current_user):
        installs = [
            i for i in installs
            if i.get("owner") == current_user.username
        ]

    return {
        "items": [WPInstallInfo(**i) for i in installs],
        "total": len(installs),
    }


# ---------------------------------------------------------------------------
# GET /{domain}/info — WP version, plugins, theme, health
# ---------------------------------------------------------------------------

@router.get("/{domain}/info", response_model=WPSiteInfo)
async def wp_info(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor

    try:
        info = wordpress_executor.get_wp_info(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    return WPSiteInfo(**info)


# ---------------------------------------------------------------------------
# POST /{domain}/update-core — update WordPress core
# ---------------------------------------------------------------------------

@router.post("/{domain}/update-core", response_model=WPUpdateResult)
async def wp_update_core(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor

    try:
        result = wordpress_executor.update_wp_core(path)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    _log(db, request, current_user.id, "wordpress.update_core", f"Updated WordPress core for {domain}")
    return WPUpdateResult(**result)


# ---------------------------------------------------------------------------
# POST /{domain}/update-plugins — update all plugins
# ---------------------------------------------------------------------------

@router.post("/{domain}/update-plugins", response_model=WPUpdateResult)
async def wp_update_plugins(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor

    try:
        result = wordpress_executor.update_wp_plugins(path)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    _log(db, request, current_user.id, "wordpress.update_plugins", f"Updated plugins for {domain}")
    return WPUpdateResult(**result)


# ---------------------------------------------------------------------------
# POST /{domain}/backup — backup this WP install
# ---------------------------------------------------------------------------

@router.post("/{domain}/backup", response_model=WPBackupResult)
async def wp_backup(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor
    import subprocess
    import time

    # Create backup via tar + wp db export
    timestamp = int(time.time())
    backup_dir = f"/opt/hosthive/backups/wordpress"
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = f"{backup_dir}/{domain}_{timestamp}.tar.gz"

    # Export database
    db_dump = f"/tmp/wp_backup_{domain}_{timestamp}.sql"
    try:
        wordpress_executor._wp_cli(path, "db", "export", db_dump, timeout=300)
    except Exception:
        db_dump = None

    # Create tar archive
    tar_args = ["tar", "-czf", backup_file, "-C", os.path.dirname(path), os.path.basename(path)]
    if db_dump and os.path.isfile(db_dump):
        tar_args.extend(["-C", "/tmp", os.path.basename(db_dump)])

    r = subprocess.run(tar_args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Backup failed: {r.stderr}",
        )

    # Clean up temp dump
    if db_dump:
        try:
            os.unlink(db_dump)
        except OSError:
            pass

    size = os.path.getsize(backup_file) if os.path.isfile(backup_file) else 0

    _log(db, request, current_user.id, "wordpress.backup", f"Backed up WordPress for {domain}")
    return WPBackupResult(path=path, backup_file=backup_file, size_bytes=size)


# ---------------------------------------------------------------------------
# POST /{domain}/clone — clone to staging domain
# ---------------------------------------------------------------------------

@router.post("/{domain}/clone", response_model=WPCloneResult)
async def wp_clone(
    domain: str,
    body: WPCloneRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor

    try:
        result = wordpress_executor.clone_wordpress(path, body.target_domain)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _log(
        db, request, current_user.id,
        "wordpress.clone",
        f"Cloned WordPress {domain} -> {body.target_domain}",
    )
    return WPCloneResult(**result)


# ---------------------------------------------------------------------------
# POST /{domain}/search-replace — search & replace in DB
# ---------------------------------------------------------------------------

@router.post("/{domain}/search-replace", response_model=WPSearchReplaceResult)
async def wp_search_replace(
    domain: str,
    body: WPSearchReplaceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor

    try:
        result = wordpress_executor.search_replace(path, body.old_domain, body.new_domain)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _log(
        db, request, current_user.id,
        "wordpress.search_replace",
        f"Search-replace on {domain}: {body.old_domain} -> {body.new_domain}",
    )
    return WPSearchReplaceResult(**result)


# ---------------------------------------------------------------------------
# GET /{domain}/security-check — check for vulnerabilities
# ---------------------------------------------------------------------------

@router.get("/{domain}/security-check", response_model=WPSecurityReport)
async def wp_security_check(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    from agent.executors import wordpress_executor

    try:
        report = wordpress_executor.security_check(path)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    _log(db, request, current_user.id, "wordpress.security_check", f"Security check for {domain}")
    return WPSecurityReport(**report)
