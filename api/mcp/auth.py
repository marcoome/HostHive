"""Bearer token verification for MCP server connections."""

from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.core.config import settings

log = logging.getLogger("novapanel.mcp")

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_mcp_token() -> str:
    """Derive the MCP token from the main secret key.

    In production the MCP_TOKEN should be set explicitly; here we derive a
    deterministic token so the system works out of the box.
    """
    token = getattr(settings, "MCP_TOKEN", None)
    if token:
        return token
    # Derive from SECRET_KEY so there is always a valid token
    return hmac.new(
        settings.SECRET_KEY.encode(),
        b"hosthive-mcp-token",
        "sha256",
    ).hexdigest()


async def verify_mcp_bearer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency that validates the MCP Bearer token.

    Returns the token string on success or raises 401.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing MCP bearer token.",
        )

    expected = _get_mcp_token()
    if not hmac.compare_digest(credentials.credentials, expected):
        log.warning("MCP auth failed: invalid bearer token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MCP bearer token.",
        )

    return credentials.credentials
