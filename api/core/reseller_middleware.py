"""Reseller branding, bandwidth & API rate-limit middleware.

Inspects incoming requests for a custom domain header or Host header.
If the domain belongs to a reseller, injects branding metadata into the
response headers so the frontend can theme itself accordingly.

Also checks bandwidth limits for reseller sub-users: if the reseller's
bandwidth allocation is exhausted, API requests from their sub-users
receive a 429 response.

Per-reseller API rate limiting uses Redis sorted sets for a sliding-window
algorithm.  Each reseller has minute-level and hour-level windows.
Sub-users share the reseller's rate-limit pool.
"""

from __future__ import annotations

import json
import logging
import time
import uuid as _uuid
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.core.database import async_session_factory

logger = logging.getLogger("hosthive.reseller_middleware")

# Window durations in seconds
_MINUTE = 60
_HOUR = 3600


class ResellerBrandingMiddleware(BaseHTTPMiddleware):
    """Check if request originates from a reseller custom domain and inject branding.

    Also enforces bandwidth limits and per-reseller API rate limits for
    reseller sub-users.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Determine the domain from either X-Forwarded-Host, the custom header,
        # or the standard Host header.
        domain = (
            request.headers.get("x-reseller-domain")
            or request.headers.get("x-forwarded-host")
            or request.headers.get("host")
        )

        branding_json: Optional[str] = None

        if domain:
            # Strip port if present
            domain = domain.split(":")[0].lower().strip()
            branding_json = await self._lookup_branding(domain)

        # Check bandwidth limits for authenticated reseller sub-users
        bandwidth_blocked = await self._check_bandwidth_limit(request)
        if bandwidth_blocked:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Reseller bandwidth limit exceeded. Please contact your provider.",
                },
            )

        # ── Per-reseller API rate limiting ────────────────────────────────
        rate_limit_result = await self._check_rate_limit(request)
        if rate_limit_result is not None:
            blocked, headers = rate_limit_result
            if blocked:
                resp = JSONResponse(
                    status_code=429,
                    content={
                        "detail": "API rate limit exceeded. Please slow down.",
                    },
                )
                for k, v in headers.items():
                    resp.headers[k] = v
                return resp

        response = await call_next(request)

        if branding_json is not None:
            response.headers["X-Reseller-Branding"] = branding_json

        # Attach rate-limit headers to successful responses
        if rate_limit_result is not None:
            _, headers = rate_limit_result
            for k, v in headers.items():
                response.headers[k] = v

        return response

    # ------------------------------------------------------------------
    # DB lookup (lightweight, cached in production via Redis)
    # ------------------------------------------------------------------

    @staticmethod
    async def _lookup_branding(domain: str) -> Optional[str]:
        """Query the reseller_branding table for a matching custom domain.

        Returns a compact JSON string with branding fields, or None.
        """
        from api.models.reseller import ResellerBranding
        from sqlalchemy import select

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(ResellerBranding).where(
                        ResellerBranding.custom_domain == domain
                    )
                )
                branding = result.scalar_one_or_none()

                if branding is None:
                    return None

                return json.dumps({
                    "reseller_id": str(branding.user_id),
                    "logo_url": branding.logo_url,
                    "primary_color": branding.primary_color,
                    "panel_title": branding.panel_title,
                    "hide_hosthive_branding": branding.hide_hosthive_branding,
                    "custom_css": branding.custom_css,
                }, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to look up reseller branding for %s: %s", domain, exc)
            return None

    # ------------------------------------------------------------------
    # Bandwidth limit check
    # ------------------------------------------------------------------

    @staticmethod
    async def _check_bandwidth_limit(request: Request) -> bool:
        """Check if the current user belongs to a reseller whose bandwidth is exceeded.

        Returns True if the request should be blocked (429).
        Only checks API requests (skips static assets, auth, health).
        """
        path = request.url.path

        # Only check API endpoints, skip auth/health/static
        if not path.startswith("/api/"):
            return False
        if any(seg in path for seg in ("/auth/", "/health", "/docs", "/openapi")):
            return False

        # Try to extract user from the authorization header without raising
        try:
            from api.core.security import get_current_user_optional
        except ImportError:
            # Fallback: decode JWT manually
            return await ResellerBrandingMiddleware._check_bandwidth_from_token(request)

        return await ResellerBrandingMiddleware._check_bandwidth_from_token(request)

    @staticmethod
    async def _check_bandwidth_from_token(request: Request) -> bool:
        """Decode the JWT, find the user's reseller, and check bandwidth."""
        from jose import jwt, JWTError
        from sqlalchemy import select

        from api.core.config import settings
        from api.models.reseller import ResellerLimit
        from api.models.users import User

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return False

        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("sub")
            if not user_id:
                return False
        except (JWTError, Exception):
            return False

        try:
            async with async_session_factory() as session:
                # Look up the user
                result = await session.execute(
                    select(User.created_by).where(User.id == user_id)
                )
                row = result.first()
                if row is None or row[0] is None:
                    # Not a sub-user (admin/standalone) -- no reseller limit
                    return False

                reseller_id = row[0]

                # Look up reseller limits
                lim_result = await session.execute(
                    select(ResellerLimit).where(
                        ResellerLimit.reseller_id == reseller_id
                    )
                )
                limits = lim_result.scalar_one_or_none()
                if limits is None:
                    return False

                # Check if bandwidth exceeded
                if (
                    limits.max_total_bandwidth_gb > 0
                    and limits.used_bandwidth_gb >= limits.max_total_bandwidth_gb
                ):
                    logger.warning(
                        "Blocking request from user %s: reseller %s bandwidth exceeded "
                        "(%.2f / %d GB)",
                        user_id, reseller_id,
                        limits.used_bandwidth_gb, limits.max_total_bandwidth_gb,
                    )
                    return True

                return False
        except Exception as exc:
            logger.debug("Bandwidth check error (non-fatal): %s", exc)
            return False

    # ------------------------------------------------------------------
    # Per-reseller API rate limiting (Redis sliding window)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_reseller_from_token(request: Request) -> Optional[Tuple[str, Optional[str]]]:
        """Extract (user_id, role) from the JWT without DB lookup.

        Returns None when there is no valid bearer token.
        """
        from jose import jwt, JWTError
        from api.core.config import settings

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("sub")
            role = payload.get("role")
            if not user_id:
                return None
            return (user_id, role)
        except (JWTError, Exception):
            return None

    @staticmethod
    async def _resolve_reseller_id(request: Request) -> Optional[Tuple[str, "ResellerLimit"]]:
        """Determine the reseller_id for the current request and return their limits.

        For resellers: the reseller_id is the user's own id.
        For sub-users: the reseller_id is user.created_by.
        For admins / standalone users: returns None (no reseller rate limit).

        Returns (reseller_id_str, ResellerLimit) or None.
        """
        from sqlalchemy import select
        from api.models.reseller import ResellerLimit
        from api.models.users import User

        token_info = ResellerBrandingMiddleware._resolve_reseller_from_token(request)
        if token_info is None:
            return None

        user_id, role = token_info

        # Admins are exempt from reseller rate limits
        if role == "admin":
            return None

        try:
            async with async_session_factory() as session:
                if role == "reseller":
                    # The reseller themselves -- rate limit key is their own id
                    reseller_id = user_id
                else:
                    # Regular user -- check if they belong to a reseller
                    result = await session.execute(
                        select(User.created_by).where(User.id == user_id)
                    )
                    row = result.first()
                    if row is None or row[0] is None:
                        return None
                    reseller_id = str(row[0])

                lim_result = await session.execute(
                    select(ResellerLimit).where(
                        ResellerLimit.reseller_id == _uuid.UUID(reseller_id)
                    )
                )
                limits = lim_result.scalar_one_or_none()
                if limits is None:
                    return None

                return (reseller_id, limits)
        except Exception as exc:
            logger.debug("Rate-limit reseller resolution error (non-fatal): %s", exc)
            return None

    @staticmethod
    async def _sliding_window_check(
        redis_client,
        key: str,
        window_seconds: int,
        max_requests: int,
    ) -> Tuple[int, int, float]:
        """Perform a sliding-window rate-limit check using a Redis sorted set.

        Args:
            redis_client: async Redis client
            key: the sorted-set key
            window_seconds: size of the sliding window
            max_requests: maximum allowed requests in that window

        Returns:
            (current_count, remaining, reset_timestamp)
        """
        now = time.time()
        window_start = now - window_seconds

        pipe = redis_client.pipeline()
        # Add the current request with its timestamp as score and a unique member
        member = f"{now}:{_uuid.uuid4().hex[:8]}"
        pipe.zadd(key, {member: now})
        # Remove entries outside the sliding window
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Count entries in the current window
        pipe.zcard(key)
        # Set TTL so the key auto-expires if no requests come
        pipe.expire(key, window_seconds + 10)
        results = await pipe.execute()

        current_count = results[2]
        remaining = max(0, max_requests - current_count)
        reset_ts = now + window_seconds

        return (current_count, remaining, reset_ts)

    @staticmethod
    async def _check_rate_limit(
        request: Request,
    ) -> Optional[Tuple[bool, dict]]:
        """Check per-reseller API rate limits.

        Returns None if rate limiting does not apply (no reseller context).
        Returns (is_blocked, headers_dict) otherwise.
        """
        path = request.url.path

        # Only check API endpoints, skip auth/health/static/docs
        if not path.startswith("/api/"):
            return None
        if any(seg in path for seg in ("/auth/", "/health", "/docs", "/openapi")):
            return None

        info = await ResellerBrandingMiddleware._resolve_reseller_id(request)
        if info is None:
            return None

        reseller_id, limits = info
        limit_per_minute = limits.api_rate_limit_per_minute
        limit_per_hour = limits.api_rate_limit_per_hour

        # Get Redis from app state
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is None:
            logger.debug("Redis not available for rate limiting, skipping.")
            return None

        minute_key = f"ratelimit:reseller:{reseller_id}:minute"
        hour_key = f"ratelimit:reseller:{reseller_id}:hour"

        try:
            min_count, min_remaining, min_reset = (
                await ResellerBrandingMiddleware._sliding_window_check(
                    redis_client, minute_key, _MINUTE, limit_per_minute,
                )
            )
            hr_count, hr_remaining, hr_reset = (
                await ResellerBrandingMiddleware._sliding_window_check(
                    redis_client, hour_key, _HOUR, limit_per_hour,
                )
            )
        except Exception as exc:
            logger.debug("Rate-limit Redis error (non-fatal, allowing request): %s", exc)
            return None

        # Determine which limit is the bottleneck for response headers
        if min_remaining <= hr_remaining:
            effective_limit = limit_per_minute
            effective_remaining = min_remaining
            effective_reset = min_reset
        else:
            effective_limit = limit_per_hour
            effective_remaining = hr_remaining
            effective_reset = hr_reset

        headers = {
            "X-RateLimit-Limit": str(effective_limit),
            "X-RateLimit-Remaining": str(effective_remaining),
            "X-RateLimit-Reset": str(int(effective_reset)),
        }

        # Check if either window is exceeded
        is_blocked = min_count > limit_per_minute or hr_count > limit_per_hour
        if is_blocked:
            # Retry-After: seconds until the tighter window resets
            retry_after = int(min_reset - time.time()) if min_count > limit_per_minute else int(hr_reset - time.time())
            retry_after = max(1, retry_after)
            headers["Retry-After"] = str(retry_after)
            logger.warning(
                "Rate limit exceeded for reseller %s: minute=%d/%d, hour=%d/%d",
                reseller_id, min_count, limit_per_minute, hr_count, limit_per_hour,
            )

        return (is_blocked, headers)
