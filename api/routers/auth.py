"""Authentication router -- /api/v1/auth."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import (
    check_brute_force,
    clear_login_failures,
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    record_login_failure,
    verify_password,
    verify_token,
)
from api.core.config import settings
from api.models.users import User
from api.models.activity_log import ActivityLog
from api.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
)
from api.schemas.users import UserResponse

router = APIRouter()

_REFRESH_PREFIX = "hosthive:refresh:"


# --------------------------------------------------------------------------
# POST /login
# --------------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    redis = request.app.state.redis
    client_ip = request.client.host if request.client else "unknown"

    await check_brute_force(redis, client_ip)

    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        await record_login_failure(redis, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    if not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or suspended.",
        )

    await clear_login_failures(redis, client_ip)

    access_token = create_access_token(
        user.id, user.role.value, user.password_changed_at,
    )
    refresh_token = create_refresh_token(user.id)

    # Store refresh token in Redis so we can invalidate it later
    refresh_key = f"{_REFRESH_PREFIX}{user.id}:{refresh_token[-16:]}"
    await redis.set(
        refresh_key,
        "1",
        ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    # Activity log
    db.add(ActivityLog(
        user_id=user.id,
        action="auth.login",
        details=f"Login from {client_ip}",
        ip_address=client_ip,
    ))

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


# --------------------------------------------------------------------------
# POST /refresh
# --------------------------------------------------------------------------
@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh_token(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(body.refresh_token, expected_type="refresh")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )

    redis = request.app.state.redis
    refresh_key = f"{_REFRESH_PREFIX}{user_id}:{body.refresh_token[-16:]}"
    valid = await redis.get(refresh_key)
    if valid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked.",
        )

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    # Invalidate old refresh token
    await redis.delete(refresh_key)

    new_access = create_access_token(
        user.id, user.role.value, user.password_changed_at,
    )
    new_refresh = create_refresh_token(user.id)

    new_key = f"{_REFRESH_PREFIX}{user.id}:{new_refresh[-16:]}"
    await redis.set(
        new_key,
        "1",
        ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# --------------------------------------------------------------------------
# POST /logout
# --------------------------------------------------------------------------
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    redis = request.app.state.redis
    refresh_key = f"{_REFRESH_PREFIX}{current_user.id}:{body.refresh_token[-16:]}"
    await redis.delete(refresh_key)


# --------------------------------------------------------------------------
# POST /forgot-password
# --------------------------------------------------------------------------
@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a new random password and store it. In production, email it."""
    import secrets
    import logging

    logger = logging.getLogger("hosthive.auth")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is not None:
        new_password = secrets.token_urlsafe(12)
        user.password_hash = hash_password(new_password)
        db.add(user)
        logger.info("Password reset for user=%s email=%s new_password=%s", user.username, user.email, new_password)
        # TODO: Send email with new_password via notification service

    # Always return 200 to prevent email enumeration
    return {"detail": "If an account exists with that email, a password reset has been initiated."}


# --------------------------------------------------------------------------
# POST /change-password
# --------------------------------------------------------------------------
@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.password_hash = hash_password(body.new_password)
    current_user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(current_user)

    # Invalidate ALL refresh tokens for this user
    redis = request.app.state.redis
    pattern = f"{_REFRESH_PREFIX}{current_user.id}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=200)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break

    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=current_user.id,
        action="auth.change_password",
        details="Password changed",
        ip_address=client_ip,
    ))

    return {"detail": "Password changed successfully."}


# --------------------------------------------------------------------------
# GET /me
# --------------------------------------------------------------------------
@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
