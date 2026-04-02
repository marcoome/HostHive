"""MCP router -- /api/v1/mcp.

Stub endpoints for MCP (Model Context Protocol) status.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.core.security import get_current_user
from api.models.users import User

router = APIRouter()


@router.get("/status", status_code=status.HTTP_200_OK)
async def mcp_status(
    current_user: User = Depends(get_current_user),
):
    """Return MCP integration status."""
    return {
        "enabled": False,
        "connected": False,
        "servers": [],
        "message": "MCP integration is not configured.",
    }


@router.post("/token/regenerate", status_code=status.HTTP_200_OK)
async def regenerate_mcp_token(current_user: User = Depends(get_current_user)):
    import secrets
    token = secrets.token_urlsafe(32)
    return {"token": token, "detail": "MCP token regenerated."}


@router.get("/config", status_code=status.HTTP_200_OK)
async def get_mcp_config(current_user: User = Depends(get_current_user)):
    return {"enabled": False, "servers": [], "tools": []}
