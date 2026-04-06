"""Reseller branding & bandwidth middleware.

Inspects incoming requests for a custom domain header or Host header.
If the domain belongs to a reseller, injects branding metadata into the
response headers so the frontend can theme itself accordingly.

Also checks bandwidth limits for reseller sub-users: if the reseller's
bandwidth allocation is exhausted, API requests from their sub-users
receive a 429 response.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.core.database import async_session_factory

logger = logging.getLogger("hosthive.reseller_middleware")


class ResellerBrandingMiddleware(BaseHTTPMiddleware):
    """Check if request originates from a reseller custom domain and inject branding.

    Also enforces bandwidth limits for reseller sub-users.
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

        response = await call_next(request)

        if branding_json is not None:
            response.headers["X-Reseller-Branding"] = branding_json

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
