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
