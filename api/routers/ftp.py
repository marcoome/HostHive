"""FTP accounts router -- /api/v1/ftp."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password
from api.models.activity_log import ActivityLog
from api.models.ftp_accounts import FtpAccount
from api.models.users import User
from api.schemas.ftp import FtpAccountCreate, FtpAccountResponse

router = APIRouter()
logger = logging.getLogger(__name__)

FTPD_PASSWD = "/etc/proftpd/ftpd.passwd"


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_ftp_or_404(
    ftp_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> FtpAccount:
    result = await db.execute(select(FtpAccount).where(FtpAccount.id == ftp_id))
    acct = result.scalar_one_or_none()
    if acct is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FTP account not found.")
    if not _is_admin(current_user) and acct.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return acct


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# Direct ProFTPD management (no agent)
# --------------------------------------------------------------------------

def _direct_create_ftp_user(username: str, password: str, home_dir: str) -> None:
    """Create an FTP user in /etc/proftpd/ftpd.passwd using ftpasswd."""
    result = subprocess.run(
        [
            "ftpasswd", "--passwd",
            "--name=" + username,
            "--uid=33",
            "--gid=33",
            "--home=" + home_dir,
            "--shell=/bin/false",
            "--file=" + FTPD_PASSWD,
            "--stdin",
        ],
        input=password,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ftpasswd create failed: {result.stderr.strip()}")
    # Ensure home dir exists
    subprocess.run(["mkdir", "-p", home_dir], capture_output=True, timeout=5)
    subprocess.run(["chown", "33:33", home_dir], capture_output=True, timeout=5)
    _reload_proftpd()


def _direct_delete_ftp_user(username: str) -> None:
    """Remove an FTP user from /etc/proftpd/ftpd.passwd."""
    try:
        with open(FTPD_PASSWD, "r") as f:
            lines = f.readlines()
        # Each line starts with username:
        pattern = re.compile(r"^" + re.escape(username) + r":")
        new_lines = [line for line in lines if not pattern.match(line)]
        if len(new_lines) == len(lines):
            logger.warning("FTP user %s not found in %s", username, FTPD_PASSWD)
        with open(FTPD_PASSWD, "w") as f:
            f.writelines(new_lines)
    except FileNotFoundError:
        logger.warning("%s does not exist, nothing to remove", FTPD_PASSWD)
    _reload_proftpd()


def _direct_update_ftp_password(username: str, password: str, home_dir: str) -> None:
    """Update the password for an existing FTP user (ftpasswd overwrites the entry)."""
    result = subprocess.run(
        [
            "ftpasswd", "--passwd",
            "--name=" + username,
            "--uid=33",
            "--gid=33",
            "--home=" + home_dir,
            "--shell=/bin/false",
            "--file=" + FTPD_PASSWD,
            "--change-password",
            "--stdin",
        ],
        input=password,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ftpasswd update failed: {result.stderr.strip()}")
    _reload_proftpd()


def _reload_proftpd() -> None:
    """Reload ProFTPD so it picks up password file changes."""
    result = subprocess.run(
        ["systemctl", "reload", "proftpd"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        # Reload failed, try restart as fallback
        subprocess.run(
            ["systemctl", "restart", "proftpd"],
            capture_output=True,
            text=True,
            timeout=15,
        )


# --------------------------------------------------------------------------
# GET / -- list FTP accounts
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_ftp_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(FtpAccount)
    count_query = select(func.count()).select_from(FtpAccount)
    if not _is_admin(current_user):
        query = query.where(FtpAccount.user_id == current_user.id)
        count_query = count_query.where(FtpAccount.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    return {
        "items": [FtpAccountResponse.model_validate(a) for a in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create FTP account
# --------------------------------------------------------------------------
@router.post("", response_model=FtpAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_ftp_account(
    body: FtpAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exists = await db.execute(select(FtpAccount).where(FtpAccount.username == body.username))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="FTP username already exists.")

    # Default home_dir if not provided
    if not body.home_dir:
        body.home_dir = f"/home/{current_user.username}/"

    # Sanitize home_dir: must be under /home/{username}/
    expected_prefix = f"/home/{current_user.username}/"
    if not _is_admin(current_user) and not body.home_dir.startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Home directory must be under {expected_prefix}",
        )

    # Save to DB first
    acct = FtpAccount(
        user_id=current_user.id,
        username=body.username,
        password_hash=hash_password(body.password),
        home_dir=body.home_dir,
    )
    db.add(acct)
    await db.flush()

    # Provision directly via ftpasswd/proftpd (no agent proxy)
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _direct_create_ftp_user, body.username, body.password, body.home_dir,
        )
    except Exception as exc:
        logger.error("Direct FTP user creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision FTP account: {exc}",
        )

    _log(db, request, current_user.id, "ftp.create", f"Created FTP account {body.username}")
    return FtpAccountResponse.model_validate(acct)


# ==========================================================================
# Alias routes for frontend compatibility (/accounts/...)
# IMPORTANT: These MUST be defined BEFORE /{ftp_id} to avoid FastAPI
# matching "accounts" as a UUID path parameter.
# ==========================================================================

@router.get("/accounts", status_code=status.HTTP_200_OK)
async def list_ftp_accounts_alias(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_ftp_accounts(skip=skip, limit=limit, db=db, current_user=current_user)


@router.post("/accounts", response_model=FtpAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_ftp_account_alias(
    body: FtpAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await create_ftp_account(body=body, request=request, db=db, current_user=current_user)


@router.get("/accounts/{ftp_id}", response_model=FtpAccountResponse, status_code=status.HTTP_200_OK)
async def get_ftp_account_alias(
    ftp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return FtpAccountResponse.model_validate(await _get_ftp_or_404(ftp_id, db, current_user))


@router.put("/accounts/{ftp_id}", response_model=FtpAccountResponse, status_code=status.HTTP_200_OK)
async def update_ftp_account_alias(
    ftp_id: uuid.UUID,
    is_active: bool = Query(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await update_ftp_account(
        ftp_id=ftp_id, is_active=is_active, request=request, db=db, current_user=current_user,
    )


@router.delete("/accounts/{ftp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ftp_account_alias(
    ftp_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await delete_ftp_account(ftp_id=ftp_id, request=request, db=db, current_user=current_user)


# --------------------------------------------------------------------------
# GET /{id} -- FTP account detail (MUST be after all static path routes)
# --------------------------------------------------------------------------
@router.get("/{ftp_id}", response_model=FtpAccountResponse, status_code=status.HTTP_200_OK)
async def get_ftp_account(
    ftp_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return FtpAccountResponse.model_validate(await _get_ftp_or_404(ftp_id, db, current_user))


# --------------------------------------------------------------------------
# PUT /{id} -- update FTP account
# --------------------------------------------------------------------------
@router.put("/{ftp_id}", response_model=FtpAccountResponse, status_code=status.HTTP_200_OK)
async def update_ftp_account(
    ftp_id: uuid.UUID,
    is_active: bool = Query(None),
    password: str = Query(None, min_length=8, max_length=128),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    acct = await _get_ftp_or_404(ftp_id, db, current_user)
    if is_active is not None:
        acct.is_active = is_active

    # Update password on the system if provided
    if password is not None:
        acct.password_hash = hash_password(password)
        # Update directly via ftpasswd (no agent proxy)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, _direct_update_ftp_password, acct.username, password, acct.home_dir,
            )
        except Exception as exc:
            logger.error("Direct FTP password update failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update FTP password: {exc}",
            )

    db.add(acct)
    await db.flush()

    _log(db, request, current_user.id, "ftp.update", f"Updated FTP account {acct.username}")
    return FtpAccountResponse.model_validate(acct)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete FTP account
# --------------------------------------------------------------------------
@router.delete("/{ftp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ftp_account(
    ftp_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    acct = await _get_ftp_or_404(ftp_id, db, current_user)

    # Delete directly from ftpd.passwd (no agent proxy)
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _direct_delete_ftp_user, acct.username)
    except Exception as exc:
        logger.error("Direct FTP user deletion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete FTP account from system: {exc}",
        )

    _log(db, request, current_user.id, "ftp.delete", f"Deleted FTP account {acct.username}")
    await db.delete(acct)
    await db.flush()
