"""API keys router -- /api/v1/api-keys."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password
from api.models.activity_log import ActivityLog
from api.models.integrations import ApiKey, ApiKeyScope
from api.models.users import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=client_ip,
    ))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scope: ApiKeyScope = ApiKeyScope.READ_ONLY
    custom_permissions: Optional[list[str]] = None
    expires_at: Optional[datetime] = None


class ApiKeyCreateResponse(BaseModel):
    """Returned ONLY on creation -- includes the full key."""
    id: uuid.UUID
    name: str
    key: str  # full key, shown once
    key_prefix: str
    scope: ApiKeyScope
    expires_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scope: ApiKeyScope
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyUsageResponse(BaseModel):
    id: uuid.UUID
    last_used_at: datetime | None = None
    usage_count: int = 0


# ---------------------------------------------------------------------------
# GET / -- list user's API keys (prefix only)
# ---------------------------------------------------------------------------
@router.get("/", status_code=status.HTTP_200_OK)
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApiKeyResponse]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [ApiKeyResponse.model_validate(k) for k in keys]


# ---------------------------------------------------------------------------
# POST / -- generate new API key (returns full key ONCE)
# ---------------------------------------------------------------------------
@router.post("/", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Limit per user
    count = (
        await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.user_id == current_user.id, ApiKey.is_active.is_(True))
        )
    ).scalar() or 0
    if count >= 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum of 20 active API keys reached.",
        )

    # Generate key
    raw_key = "hh_" + secrets.token_urlsafe(48)
    key_prefix = raw_key[:8]

    # Store bcrypt hash
    key_hash = hash_password(raw_key)

    import json as _json
    custom_perms_json = (
        _json.dumps(body.custom_permissions) if body.custom_permissions else None
    )

    api_key = ApiKey(
        user_id=current_user.id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scope=body.scope,
        custom_permissions=custom_perms_json,
        expires_at=body.expires_at,
        is_active=True,
    )
    db.add(api_key)
    await db.flush()

    _log(db, request, current_user.id, "api_keys.create", f"Created API key '{body.name}'")

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,
        key_prefix=key_prefix,
        scope=api_key.scope,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


# ---------------------------------------------------------------------------
# DELETE /{id} -- revoke API key
# ---------------------------------------------------------------------------
@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    api_key.is_active = False
    db.add(api_key)
    await db.flush()

    _log(db, request, current_user.id, "api_keys.revoke", f"Revoked API key '{api_key.name}'")


# ---------------------------------------------------------------------------
# GET /{id}/usage -- last used timestamp, usage count
# ---------------------------------------------------------------------------
@router.get("/{key_id}/usage", response_model=ApiKeyUsageResponse, status_code=status.HTTP_200_OK)
async def api_key_usage(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    # Count audit log entries where the action starts with the key prefix pattern
    # In practice, a dedicated usage counter column or Redis counter would be better.
    # For now we approximate with activity log entries from this user.
    usage_count = (
        await db.execute(
            select(func.count())
            .select_from(ActivityLog)
            .where(ActivityLog.user_id == current_user.id)
        )
    ).scalar() or 0

    return ApiKeyUsageResponse(
        id=api_key.id,
        last_used_at=api_key.last_used_at,
        usage_count=usage_count,
    )
