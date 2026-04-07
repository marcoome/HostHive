"""Users router -- /api/v1/users (admin only).

System-user lifecycle (useradd / userdel / usermod / passwd) is performed
directly via subprocess on the local host -- this router does NOT proxy to
the privileged agent on port 7080. Blocking subprocess calls are dispatched
to the default executor via ``asyncio.get_running_loop().run_in_executor``
so the FastAPI event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.database import get_db
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.databases import Database
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.ftp_accounts import FtpAccount
from api.models.packages import Package, PackageType
from api.models.users import User, UserRole
from api.schemas.databases import DatabaseResponse
from api.schemas.domains import DomainResponse
from api.schemas.users import UserCreate, UserListResponse, UserResponse, UserUpdate

logger = logging.getLogger(__name__)

router = APIRouter()

_admin = require_role("admin")


# --------------------------------------------------------------------------
# Subprocess helpers (no agent -- run locally, off the event loop)
# --------------------------------------------------------------------------

def _run_cmd_sync(
    argv: list[str],
    *,
    input_text: Optional[str] = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Blocking subprocess.run wrapper. Always invoked from a thread."""
    return subprocess.run(  # noqa: S603 -- argv is constructed, never shell=True
        argv,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


async def _run_cmd(
    argv: list[str],
    *,
    input_text: Optional[str] = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a system command in the default thread executor.

    The whole point of this router refactor: every privileged user-management
    operation goes through this helper instead of being proxied to the agent.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_cmd_sync(argv, input_text=input_text, timeout=timeout),
    )


def _which(binary: str) -> Optional[str]:
    return shutil.which(binary)


async def _system_user_exists(username: str) -> bool:
    """Return True if the given system account exists in /etc/passwd."""
    proc = await _run_cmd(["id", "-u", username], timeout=5)
    return proc.returncode == 0


async def _useradd(username: str, password: str) -> None:
    """Create a Linux account with /home/<user> and set its password.

    Idempotent: if the account already exists we still (re)set the password.
    """
    if not _which("useradd"):
        # Dev environments (macOS, containers without shadow-utils) -- skip
        # silently so the API row is still created.
        logger.warning(
            "useradd not available on this host; skipping system account "
            "creation for user %s",
            username,
        )
        return

    if not await _system_user_exists(username):
        proc = await _run_cmd(
            [
                "useradd",
                "-m",
                "-d", f"/home/{username}",
                "-s", "/usr/sbin/nologin",
                username,
            ],
            timeout=30,
        )
        if proc.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"useradd failed: {proc.stderr.strip() or proc.stdout.strip()}",
            )

    # Set the password via chpasswd (reads "user:pass" on stdin)
    if _which("chpasswd"):
        proc = await _run_cmd(
            ["chpasswd"],
            input_text=f"{username}:{password}\n",
            timeout=15,
        )
        if proc.returncode != 0:
            logger.warning(
                "chpasswd failed for %s: %s",
                username,
                proc.stderr.strip() or proc.stdout.strip(),
            )
    elif _which("passwd"):
        # Fallback: passwd --stdin (RHEL-family) or interactive form.
        proc = await _run_cmd(
            ["passwd", "--stdin", username],
            input_text=f"{password}\n",
            timeout=15,
        )
        if proc.returncode != 0:
            logger.warning(
                "passwd failed for %s: %s",
                username,
                proc.stderr.strip() or proc.stdout.strip(),
            )


async def _userdel(username: str) -> None:
    """Remove a Linux account along with its home directory and mail spool.

    Best-effort: failures are logged but not raised so the DB row is always
    cleaned up alongside the system user.
    """
    if not _which("userdel"):
        logger.warning(
            "userdel not available on this host; skipping system account "
            "removal for user %s",
            username,
        )
        return

    if not await _system_user_exists(username):
        return

    proc = await _run_cmd(
        ["userdel", "-r", "-f", username],
        timeout=60,
    )
    if proc.returncode != 0:
        logger.warning(
            "userdel failed for %s: %s",
            username,
            proc.stderr.strip() or proc.stdout.strip(),
        )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _get_user_or_404(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> User:
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.package), selectinload(User.environment))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=client_ip,
    ))


# --------------------------------------------------------------------------
# Package <-> role compatibility
# --------------------------------------------------------------------------

def _expected_package_type(role: UserRole) -> Optional[PackageType]:
    """Return which PackageType is allowed for the given role.

    - reseller -> reseller-type package required
    - user     -> user-type package required
    - admin    -> no package needed; None means "no constraint"
    """
    if role == UserRole.RESELLER:
        return PackageType.RESELLER
    if role == UserRole.USER:
        return PackageType.USER
    return None


async def _resolve_and_validate_package(
    db: AsyncSession,
    package_id: Optional[uuid.UUID],
    role: UserRole,
) -> Optional[Package]:
    """Look up the package and ensure its type matches the user role.

    - For ``reseller`` and ``user`` roles a package_id is REQUIRED.
    - For ``admin`` the package_id is optional and unconstrained.
    - Raises HTTP 400 / 404 on mismatch.
    """
    expected = _expected_package_type(role)

    if expected is None:
        # admin: optional, no constraint
        if package_id is None:
            return None
        result = await db.execute(select(Package).where(Package.id == package_id))
        return result.scalar_one_or_none()

    if package_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A {expected.value}-type package is required when creating "
                f"a {role.value} account."
            ),
        )

    result = await db.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Package not found.",
        )

    if pkg.package_type != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Package '{pkg.name}' is a {pkg.package_type.value}-type package "
                f"and cannot be assigned to a {role.value} account "
                f"(expected {expected.value}-type)."
            ),
        )
    return pkg


# --------------------------------------------------------------------------
# GET / -- list users (paginated, filterable)
# --------------------------------------------------------------------------
@router.get("", response_model=UserListResponse, status_code=status.HTTP_200_OK)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    is_suspended: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    query = select(User).options(selectinload(User.package), selectinload(User.environment))
    count_query = select(func.count()).select_from(User)

    if role is not None:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)
    if is_suspended is not None:
        query = query.where(User.is_suspended == is_suspended)
        count_query = count_query.where(User.is_suspended == is_suspended)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(query.order_by(User.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in results],
        total=total,
        page=(skip // limit) + 1,
        per_page=limit,
    )


# --------------------------------------------------------------------------
# POST / -- create user
# --------------------------------------------------------------------------
@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # Check uniqueness
    exists = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )

    # Validate package_type matches role and resolve the package row.
    pkg = await _resolve_and_validate_package(db, body.package_id, body.role)

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        package_id=body.package_id,
    )
    db.add(user)
    await db.flush()

    # If this is a reseller, materialize / sync ResellerLimit from the
    # reseller-type package's allocation fields.
    if body.role == UserRole.RESELLER and pkg is not None:
        from api.routers.packages import sync_reseller_limit_from_package
        await sync_reseller_limit_from_package(db, user.id, pkg)

    # Create the matching Linux account locally (no agent proxy)
    await _useradd(body.username, body.password)

    # Create user home directory structure (useradd already made /home/<user>)
    import os
    home_dir = f"/home/{body.username}"
    for subdir in ["", "web", "logs", "tmp", "backups"]:
        dirpath = os.path.join(home_dir, subdir)
        try:
            os.makedirs(dirpath, mode=0o755, exist_ok=True)
        except OSError:
            pass

    # Apply shell settings from the assigned package
    if pkg is not None:
        from api.routers.packages import _apply_shell_for_user
        await _apply_shell_for_user(body.username, pkg.shell_access, pkg.shell_type)

    _log(
        db,
        request,
        admin.id,
        "users.create",
        f"Created {body.role.value} {body.username}"
        + (f" on package {pkg.name}" if pkg else ""),
    )
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# GET /{id} -- user detail
# --------------------------------------------------------------------------
@router.get("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    return UserResponse.model_validate(await _get_user_or_404(user_id, db))


# --------------------------------------------------------------------------
# GET /{id}/domains -- list domains owned by this user
# --------------------------------------------------------------------------
@router.get("/{user_id}/domains", status_code=status.HTTP_200_OK)
async def list_user_domains(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    await _get_user_or_404(user_id, db)

    count_query = select(func.count()).select_from(Domain).where(Domain.user_id == user_id)
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(Domain)
        .where(Domain.user_id == user_id)
        .order_by(Domain.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    results = (await db.execute(query)).scalars().all()

    return {
        "items": [DomainResponse.model_validate(d) for d in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# GET /{id}/databases -- list databases owned by this user
# --------------------------------------------------------------------------
@router.get("/{user_id}/databases", status_code=status.HTTP_200_OK)
async def list_user_databases(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    await _get_user_or_404(user_id, db)

    count_query = select(func.count()).select_from(Database).where(Database.user_id == user_id)
    total = (await db.execute(count_query)).scalar() or 0

    query = (
        select(Database)
        .where(Database.user_id == user_id)
        .order_by(Database.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    results = (await db.execute(query)).scalars().all()

    return {
        "items": [DatabaseResponse.model_validate(d) for d in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# PUT /{id} -- update user
# --------------------------------------------------------------------------
@router.put("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.update", f"Updated user {user.username}: {list(update_data.keys())}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete user + all resources
# --------------------------------------------------------------------------
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)

    # Snapshot related resource counts purely for the audit log -- the
    # actual on-disk cleanup happens via `userdel -r` which removes the
    # entire /home/<user> tree (web roots, mail dirs, ftp roots, etc.).
    domain_count = (await db.execute(
        select(func.count()).select_from(Domain).where(Domain.user_id == user_id)
    )).scalar() or 0
    db_count = (await db.execute(
        select(func.count()).select_from(Database).where(Database.user_id == user_id)
    )).scalar() or 0
    email_count = (await db.execute(
        select(func.count()).select_from(EmailAccount).where(EmailAccount.user_id == user_id)
    )).scalar() or 0
    ftp_count = (await db.execute(
        select(func.count()).select_from(FtpAccount).where(FtpAccount.user_id == user_id)
    )).scalar() or 0

    # Remove the Linux account + home directory locally (no agent proxy)
    await _userdel(user.username)

    _log(
        db,
        request,
        admin.id,
        "users.delete",
        (
            f"Deleted user {user.username} "
            f"(domains={domain_count}, databases={db_count}, "
            f"emails={email_count}, ftp={ftp_count})"
        ),
    )

    await db.delete(user)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/suspend
# --------------------------------------------------------------------------
@router.post("/{user_id}/suspend", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def suspend_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    user.is_suspended = True
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.suspend", f"Suspended user {user.username}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# POST /{id}/unsuspend
# --------------------------------------------------------------------------
@router.post("/{user_id}/unsuspend", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def unsuspend_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)
    user.is_suspended = False
    db.add(user)
    await db.flush()

    _log(db, request, admin.id, "users.unsuspend", f"Unsuspended user {user.username}")
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------
# GET /{id}/stats -- disk, bandwidth, resource usage
# --------------------------------------------------------------------------
@router.get("/{user_id}/stats", status_code=status.HTTP_200_OK)
async def user_stats(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = await _get_user_or_404(user_id, db)

    domain_count = (await db.execute(
        select(func.count()).select_from(Domain).where(Domain.user_id == user_id)
    )).scalar() or 0
    db_count = (await db.execute(
        select(func.count()).select_from(Database).where(Database.user_id == user_id)
    )).scalar() or 0
    email_count = (await db.execute(
        select(func.count()).select_from(EmailAccount).where(EmailAccount.user_id == user_id)
    )).scalar() or 0
    ftp_count = (await db.execute(
        select(func.count()).select_from(FtpAccount).where(FtpAccount.user_id == user_id)
    )).scalar() or 0

    return {
        "user_id": str(user_id),
        "username": user.username,
        "domains": domain_count,
        "databases": db_count,
        "email_accounts": email_count,
        "ftp_accounts": ftp_count,
        "package": {
            "name": user.package.name if user.package else None,
            "disk_quota_mb": user.package.disk_quota_mb if user.package else None,
            "bandwidth_gb": user.package.bandwidth_gb if user.package else None,
        },
    }
