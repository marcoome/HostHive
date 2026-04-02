"""Authentication, password hashing, JWT management, brute-force protection."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain[:72])


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain[:72], hashed)


# ---------------------------------------------------------------------------
# JWT creation
# ---------------------------------------------------------------------------


def _build_token(
    data: dict[str, Any],
    expires_delta: timedelta,
    token_type: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **data,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    user_id: uuid.UUID,
    role: str,
    password_changed_at: Optional[datetime] = None,
) -> str:
    data: dict[str, Any] = {"sub": str(user_id), "role": role}
    if password_changed_at is not None:
        data["pwd_ts"] = int(password_changed_at.timestamp())
    return _build_token(
        data,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _build_token(
        {"sub": str(user_id)},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(token: str, *, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a JWT.  Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Expected {expected_type} token.",
        )
    return payload


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Any:  # returns User model instance
    """Resolve the current authenticated user from the Authorization header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    payload = verify_token(credentials.credentials, expected_type="access")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject.",
        )

    # Lazy import to avoid circular dependency
    from api.models.users import User

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    # Invalidate tokens issued before the last password change
    pwd_ts = payload.get("pwd_ts")
    if user.password_changed_at is not None:
        expected_ts = int(user.password_changed_at.timestamp())
        if pwd_ts is None or pwd_ts < expected_ts:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalidated by password change.",
            )

    return user


def require_role(*roles: str):
    """Dependency factory: require the current user to have one of the given roles."""

    async def _check(
        current_user: Any = Depends(get_current_user),
    ) -> Any:
        if current_user.role.value not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return current_user

    return _check


# ---------------------------------------------------------------------------
# Brute-force protection (Redis-backed)
# ---------------------------------------------------------------------------

_LOGIN_PREFIX = "hosthive:login_fail:"
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 15 * 60  # 15 minutes


async def check_brute_force(redis: Any, ip: str) -> None:
    """Raise 429 if the IP has exceeded the failure threshold."""
    key = f"{_LOGIN_PREFIX}{ip}"
    raw = await redis.get(key)
    if raw is not None and int(raw) >= _MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )


async def record_login_failure(redis: Any, ip: str) -> None:
    """Increment the failure counter for the IP."""
    key = f"{_LOGIN_PREFIX}{ip}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, _LOCKOUT_SECONDS)
    await pipe.execute()


async def clear_login_failures(redis: Any, ip: str) -> None:
    """Reset the counter after a successful login."""
    await redis.delete(f"{_LOGIN_PREFIX}{ip}")
