"""Two-Factor Authentication (TOTP) router -- mounted under /api/v1/auth/2fa."""

from __future__ import annotations

import base64
import io
import secrets
import uuid
from typing import List

import bcrypt
import pyotp
import qrcode  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.config import settings
from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    verify_token,
)
from api.models.activity_log import ActivityLog
from api.models.users import User
from api.schemas.totp import (
    TOTP2FABackupLoginRequest,
    TOTP2FALoginRequest,
    TOTPBackupVerifyRequest,
    TOTPDisableRequest,
    TOTPSetupResponse,
    TOTPStatusResponse,
    TOTPVerifyRequest,
    TOTPVerifyResponse,
)
from api.schemas.auth import LoginResponse
from api.schemas.users import UserResponse

router = APIRouter()

_REFRESH_PREFIX = "hosthive:refresh:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_backup_codes(count: int = 10) -> List[str]:
    """Generate *count* random 8-character alphanumeric backup codes."""
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return ["".join(secrets.choice(alphabet) for _ in range(8)) for _ in range(count)]


def _hash_backup_code(code: str) -> str:
    return bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()


def _verify_backup_code(code: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode(), hashed.encode())
    except Exception:
        return False


def _make_qr_base64(uri: str) -> str:
    """Generate a base64-encoded PNG QR code for the given URI."""
    img = qrcode.make(uri, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _build_full_login_response(
    user: User,
    redis_ref: tuple,  # (redis, client_ip)
) -> dict:
    """Build the access + refresh token pair for a fully authenticated user."""
    access_token = create_access_token(
        user.id, user.role.value, user.password_changed_at,
    )
    refresh_token = create_refresh_token(user.id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": UserResponse.model_validate(user),
    }


async def _store_refresh_token(redis, user_id: uuid.UUID, refresh_token: str) -> None:
    refresh_key = f"{_REFRESH_PREFIX}{user_id}:{refresh_token[-16:]}"
    await redis.set(refresh_key, "1", ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)


async def _resolve_pending_user(
    pending_token: str, db: AsyncSession,
) -> User:
    """Decode a 2fa_pending token and load the corresponding user."""
    payload = verify_token(pending_token, expected_type="2fa_pending")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA pending token.",
        )
    result = await db.execute(
        select(User)
        .where(User.id == uuid.UUID(user_id))
        .options(selectinload(User.package), selectinload(User.environment))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled for this account.",
        )
    return user


# ---------------------------------------------------------------------------
# GET /status  -- check if 2FA is enabled
# ---------------------------------------------------------------------------
@router.get("/status", response_model=TOTPStatusResponse)
async def get_2fa_status(current_user: User = Depends(get_current_user)):
    return TOTPStatusResponse(
        enabled=current_user.totp_enabled,
        method="totp" if current_user.totp_enabled else None,
    )


# ---------------------------------------------------------------------------
# POST /setup  -- generate TOTP secret, QR, and backup codes
# ---------------------------------------------------------------------------
@router.post("/setup", response_model=TOTPSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled. Disable it first to reconfigure.",
        )

    # Generate a new TOTP secret
    secret = pyotp.random_base32()

    # Encrypt the secret before storing
    encrypted_secret = encrypt_value(secret, settings.SECRET_KEY)
    current_user.totp_secret = encrypted_secret

    # Generate backup codes
    plain_codes = _generate_backup_codes(10)
    hashed_codes = [_hash_backup_code(c) for c in plain_codes]
    current_user.totp_backup_codes = hashed_codes

    db.add(current_user)
    await db.flush()

    # Build provisioning URI
    totp = pyotp.TOTP(secret)
    issuer = "NovaPanel"
    uri = totp.provisioning_uri(name=current_user.email, issuer_name=issuer)
    qr_b64 = _make_qr_base64(uri)

    return TOTPSetupResponse(
        secret=secret,
        otpauth_uri=uri,
        qr_code_base64=qr_b64,
        backup_codes=plain_codes,
    )


# ---------------------------------------------------------------------------
# POST /verify  -- confirm setup by verifying a code (enables 2FA)
# ---------------------------------------------------------------------------
@router.post("/verify", response_model=TOTPVerifyResponse)
async def verify_2fa(
    body: TOTPVerifyRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled.",
        )
    if current_user.totp_secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup has not been initiated. Call /setup first.",
        )

    # Decrypt stored secret
    secret = decrypt_value(current_user.totp_secret, settings.SECRET_KEY)
    totp = pyotp.TOTP(secret)

    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )

    current_user.totp_enabled = True
    db.add(current_user)

    # Activity log
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=current_user.id,
        action="auth.2fa_enabled",
        details="Two-factor authentication enabled",
        ip_address=client_ip,
    ))

    return TOTPVerifyResponse(verified=True)


# ---------------------------------------------------------------------------
# POST /disable  -- disable 2FA (requires current TOTP code)
# ---------------------------------------------------------------------------
@router.post("/disable", status_code=status.HTTP_200_OK)
async def disable_2fa(
    body: TOTPDisableRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled.",
        )

    secret = decrypt_value(current_user.totp_secret, settings.SECRET_KEY)
    totp = pyotp.TOTP(secret)

    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )

    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.totp_backup_codes = None
    db.add(current_user)

    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=current_user.id,
        action="auth.2fa_disabled",
        details="Two-factor authentication disabled",
        ip_address=client_ip,
    ))

    return {"detail": "2FA has been disabled."}


# ---------------------------------------------------------------------------
# POST /login  -- complete login with TOTP code (after password auth)
# ---------------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
async def login_2fa(
    body: TOTP2FALoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_pending_user(body.pending_token, db)

    secret = decrypt_value(user.totp_secret, settings.SECRET_KEY)
    totp = pyotp.TOTP(secret)

    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code.",
        )

    redis = request.app.state.redis
    client_ip = request.client.host if request.client else "unknown"

    access_token = create_access_token(
        user.id, user.role.value, user.password_changed_at,
    )
    refresh_token = create_refresh_token(user.id)
    await _store_refresh_token(redis, user.id, refresh_token)

    db.add(ActivityLog(
        user_id=user.id,
        action="auth.login",
        details=f"Login (2FA) from {client_ip}",
        ip_address=client_ip,
    ))

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# POST /backup-verify  -- complete login with a backup code
# ---------------------------------------------------------------------------
@router.post("/backup-verify", response_model=LoginResponse)
async def login_2fa_backup(
    body: TOTP2FABackupLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_pending_user(body.pending_token, db)

    if not user.totp_backup_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No backup codes available.",
        )

    # Find and consume the matching backup code
    matched_idx = None
    for idx, hashed in enumerate(user.totp_backup_codes):
        if _verify_backup_code(body.backup_code.lower(), hashed):
            matched_idx = idx
            break

    if matched_idx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid backup code.",
        )

    # Remove the used code (one-time use)
    remaining = list(user.totp_backup_codes)
    remaining.pop(matched_idx)
    user.totp_backup_codes = remaining
    db.add(user)

    redis = request.app.state.redis
    client_ip = request.client.host if request.client else "unknown"

    access_token = create_access_token(
        user.id, user.role.value, user.password_changed_at,
    )
    refresh_token = create_refresh_token(user.id)
    await _store_refresh_token(redis, user.id, refresh_token)

    db.add(ActivityLog(
        user_id=user.id,
        action="auth.login",
        details=f"Login (2FA backup code) from {client_ip}",
        ip_address=client_ip,
    ))

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )
