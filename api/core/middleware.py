"""Security middleware stack for the HostHive API.

Provides:
- SecurityHeadersMiddleware  — inject hardening headers on every response
- AuditLogMiddleware         — log all mutating requests to the activity_log table
- IPWhitelistMiddleware      — restrict agent endpoints to localhost
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from fastapi.responses import JSONResponse

from api.core.database import async_session_factory
from api.models.activity_log import ActivityLog

logger = logging.getLogger("hosthive.middleware")

# ---------------------------------------------------------------------------
# Paths that are excluded from audit logging
# ---------------------------------------------------------------------------
_AUDIT_SKIP_PATHS: set[str] = {
    "/api/v1/health",
    "/api/v1/docs",
    "/api/v1/openapi.json",
}


# ═══════════════════════════════════════════════════════════════════════════
# Security Headers
# ═══════════════════════════════════════════════════════════════════════════


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every HTTP response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid.uuid4().hex
        # Stash on request state so downstream code can reference it
        request.state.request_id = request_id

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # No-store for API responses (not static assets)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        return response


# ═══════════════════════════════════════════════════════════════════════════
# Audit Log
# ═══════════════════════════════════════════════════════════════════════════


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Persist a record in the activity_log table for every POST/PUT/DELETE."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        # Only log mutating methods
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return response

        # Skip health checks and docs
        if request.url.path in _AUDIT_SKIP_PATHS:
            return response

        # Best-effort logging — never break the request on audit failure
        try:
            user_id = self._extract_user_id(request)
            ip_address = request.client.host if request.client else None

            action = f"{request.method} {request.url.path}"

            async with async_session_factory() as session:
                entry = ActivityLog(
                    user_id=user_id,
                    action=action,
                    details=None,
                    ip_address=ip_address,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                session.add(entry)
                await session.commit()
        except Exception:
            logger.exception("Failed to write audit log entry")

        return response

    @staticmethod
    def _extract_user_id(request: Request):
        """Try to pull the user_id from request state (set by auth dependency)."""
        user = getattr(request.state, "current_user", None)
        if user is not None:
            return getattr(user, "id", None)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# IP Whitelist (agent endpoints — localhost only)
# ═══════════════════════════════════════════════════════════════════════════

_LOCALHOST_ADDRS: set[str] = {"127.0.0.1", "::1", "localhost"}


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Block non-localhost requests to the agent endpoints.

    This middleware is intended for the agent FastAPI app, which must only
    accept connections from the local machine.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        client_host = request.client.host if request.client else None
        if client_host not in _LOCALHOST_ADDRS:
            logger.warning(
                "Blocked non-localhost request from %s to %s",
                client_host,
                request.url.path,
            )
            return JSONResponse(
                {"detail": "Access denied — localhost only."},
                status_code=403,
            )
        return await call_next(request)
