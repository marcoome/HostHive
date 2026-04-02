"""Reseller branding middleware.

Inspects incoming requests for a custom domain header or Host header.
If the domain belongs to a reseller, injects branding metadata into the
response headers so the frontend can theme itself accordingly.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from api.core.database import async_session_factory

logger = logging.getLogger("hosthive.reseller_middleware")


class ResellerBrandingMiddleware(BaseHTTPMiddleware):
    """Check if request originates from a reseller custom domain and inject branding."""

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
