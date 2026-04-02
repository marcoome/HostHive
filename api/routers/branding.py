"""Branding router -- /api/v1/branding."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.branding import BrandingConfig, get_branding, reload_branding
from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

router = APIRouter()

_admin = require_role("admin")

# Writable branding config path
_BRANDING_PATHS = [
    Path("/opt/hosthive/config/branding.json"),
    Path(__file__).resolve().parent.parent.parent / "config" / "branding.json",
]


def _get_writable_path() -> Path:
    """Return the first writable branding config path."""
    for p in _BRANDING_PATHS:
        if p.exists():
            return p
    # Default to the production path; create parent if needed
    return _BRANDING_PATHS[0]


# --------------------------------------------------------------------------
# GET / -- return branding config (public, no auth)
# --------------------------------------------------------------------------
@router.get("/", status_code=status.HTTP_200_OK)
async def get_branding_config():
    branding = get_branding()
    return branding.model_dump()


# --------------------------------------------------------------------------
# PUT / -- update branding (admin only)
# --------------------------------------------------------------------------
@router.put("/", status_code=status.HTTP_200_OK)
async def update_branding(
    body: BrandingConfig,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    target = _get_writable_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(body.model_dump(), f, indent=2, ensure_ascii=False)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write branding config: {exc}",
        )

    # Reload cached branding
    reload_branding()

    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=admin.id,
        action="branding.update",
        details="Updated branding configuration",
        ip_address=client_ip,
    ))

    return body.model_dump()
