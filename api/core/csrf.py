"""Double-submit cookie CSRF protection with Redis-backed token storage.

How it works:
1. A CSRF token is generated and stored in Redis with a 1-hour TTL.
2. The token is set as a cookie (``X-CSRF-Token``) on responses.
3. On mutating requests (POST/PUT/PATCH/DELETE), the middleware compares
   the cookie value against a matching ``X-CSRF-Token`` request header.
4. Requests that use Bearer-token authentication or hit exempt paths
   (e.g. ``/api/v1/auth/login``) are not subject to CSRF checks.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Optional, Set

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("novapanel.csrf")

_TOKEN_TTL = 3600  # 1 hour
_REDIS_PREFIX = "novapanel:csrf:"
_COOKIE_NAME = "X-CSRF-Token"
_HEADER_NAME = "X-CSRF-Token"

# Paths that are exempt from CSRF validation
_EXEMPT_PATHS: Set[str] = {
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/health",
}


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


async def generate_csrf_token(redis: Any) -> str:
    """Create a new CSRF token, store it in Redis with a 1-hour TTL, and return it."""
    token = secrets.token_urlsafe(32)
    await redis.set(f"{_REDIS_PREFIX}{token}", "1", ex=_TOKEN_TTL)
    return token


async def validate_csrf_token(
    redis: Any,
    cookie_token: Optional[str],
    header_token: Optional[str],
) -> bool:
    """Validate that the cookie and header tokens match and exist in Redis.

    Returns ``True`` if the tokens are valid, ``False`` otherwise.
    """
    if not cookie_token or not header_token:
        return False

    if not secrets.compare_digest(cookie_token, header_token):
        return False

    # Verify the token exists in Redis (not expired / not forged)
    exists = await redis.exists(f"{_REDIS_PREFIX}{cookie_token}")
    return bool(exists)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF middleware.

    Constructor requires an async Redis client instance.
    """

    def __init__(self, app: Any, redis: Any) -> None:
        super().__init__(app)
        self._redis = redis

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip non-mutating methods
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # Skip exempt paths
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # Skip requests authenticated with Bearer tokens (API usage)
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return await call_next(request)

        # Validate double-submit cookie
        cookie_token = request.cookies.get(_COOKIE_NAME)
        header_token = request.headers.get(_HEADER_NAME)

        is_valid = await validate_csrf_token(
            self._redis, cookie_token, header_token
        )

        if not is_valid:
            logger.warning(
                "CSRF validation failed for %s %s from %s",
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                {"detail": "CSRF token missing or invalid."},
                status_code=403,
            )

        response = await call_next(request)

        # Rotate the token after each successful mutating request
        new_token = await generate_csrf_token(self._redis)
        response.set_cookie(
            key=_COOKIE_NAME,
            value=new_token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=_TOKEN_TTL,
            path="/",
        )

        return response
