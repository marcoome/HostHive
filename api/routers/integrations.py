"""Integrations router -- /api/v1/integrations (admin only)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.integrations import Integration, IntegrationName
from api.models.users import User

logger = logging.getLogger("hosthive.integrations")

router = APIRouter()

_admin = require_role("admin")

# ---------------------------------------------------------------------------
# Encryption helpers (Fernet, keyed from SECRET_KEY)
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {"api_key", "api_secret", "token", "secret", "password", "webhook_secret"}


def _fernet():
    """Return a Fernet instance derived from the application SECRET_KEY."""
    import base64
    import hashlib
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def _encrypt_config(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def _decrypt_config(cipher_text: str) -> dict[str, Any]:
    return json.loads(_fernet().decrypt(cipher_text.encode()).decode())


def _mask_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with sensitive values masked."""
    masked = {}
    for k, v in data.items():
        if k.lower() in _SENSITIVE_KEYS and isinstance(v, str) and len(v) > 4:
            masked[k] = v[:4] + "*" * (len(v) - 4)
        else:
            masked[k] = v
    return masked


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

class IntegrationResponse(BaseModel):
    name: str
    is_enabled: bool
    has_config: bool

    model_config = {"from_attributes": True}


class IntegrationDetailResponse(BaseModel):
    name: str
    is_enabled: bool
    config: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class IntegrationConfigUpdate(BaseModel):
    config: dict[str, Any]


class ToggleRequest(BaseModel):
    enabled: bool


# ---------------------------------------------------------------------------
# GET / -- list all integrations with status
# ---------------------------------------------------------------------------
@router.get("/", status_code=status.HTTP_200_OK)
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
) -> list[IntegrationResponse]:
    result = await db.execute(select(Integration).order_by(Integration.name))
    integrations = result.scalars().all()
    return [
        IntegrationResponse(
            name=i.name.value,
            is_enabled=i.is_enabled,
            has_config=i.config_json is not None,
        )
        for i in integrations
    ]


# ---------------------------------------------------------------------------
# GET /{name} -- get integration config (masked sensitive fields)
# ---------------------------------------------------------------------------
@router.get("/{name}", response_model=IntegrationDetailResponse, status_code=status.HTTP_200_OK)
async def get_integration(
    name: IntegrationName,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    result = await db.execute(
        select(Integration).where(Integration.name == name)
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")

    config = None
    if integration.config_json:
        try:
            config = _mask_sensitive(_decrypt_config(integration.config_json))
        except Exception:
            config = {"_error": "Failed to decrypt configuration."}

    return IntegrationDetailResponse(
        name=integration.name.value,
        is_enabled=integration.is_enabled,
        config=config,
    )


# ---------------------------------------------------------------------------
# PUT /{name} -- update integration config (encrypt before saving)
# ---------------------------------------------------------------------------
@router.put("/{name}", response_model=IntegrationDetailResponse, status_code=status.HTTP_200_OK)
async def update_integration(
    name: IntegrationName,
    body: IntegrationConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    result = await db.execute(
        select(Integration).where(Integration.name == name)
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        # Auto-create integration row if it doesn't exist
        integration = Integration(name=name, is_enabled=False)
        db.add(integration)
        await db.flush()

    integration.config_json = _encrypt_config(body.config)
    db.add(integration)
    await db.flush()

    _log(db, request, admin.id, "integrations.update", f"Updated config for {name.value}")

    return IntegrationDetailResponse(
        name=integration.name.value,
        is_enabled=integration.is_enabled,
        config=_mask_sensitive(body.config),
    )


# ---------------------------------------------------------------------------
# POST /{name}/test -- test connection for integration
# ---------------------------------------------------------------------------
@router.post("/{name}/test", status_code=status.HTTP_200_OK)
async def test_integration(
    name: IntegrationName,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    result = await db.execute(
        select(Integration).where(Integration.name == name)
    )
    integration = result.scalar_one_or_none()
    if integration is None or integration.config_json is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integration not configured.",
        )

    try:
        config = _decrypt_config(integration.config_json)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt integration config.",
        )

    test_result: dict[str, Any] = {"integration": name.value, "success": False}

    try:
        if name == IntegrationName.CLOUDFLARE:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.cloudflare.com/client/v4/zones",
                    headers={"Authorization": f"Bearer {config.get('api_key', '')}"},
                    timeout=10,
                )
                data = resp.json()
                test_result["success"] = data.get("success", False)
                test_result["zones"] = len(data.get("result", []))

        elif name == IntegrationName.S3:
            import httpx
            # Minimal S3 list-buckets via signed request would require boto3;
            # fall back to a connectivity test.
            endpoint = config.get("endpoint", "https://s3.amazonaws.com")
            async with httpx.AsyncClient() as client:
                resp = await client.get(endpoint, timeout=10)
                test_result["success"] = resp.status_code < 500
                test_result["detail"] = "Endpoint reachable."

        elif name == IntegrationName.TELEGRAM:
            import httpx
            bot_token = config.get("token", "")
            chat_id = config.get("chat_id", "")
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": "HostHive test message"},
                    timeout=10,
                )
                data = resp.json()
                test_result["success"] = data.get("ok", False)

        else:
            test_result["detail"] = f"No test implemented for {name.value}."
            test_result["success"] = True  # config exists, consider a pass

    except Exception as exc:
        test_result["error"] = str(exc)

    _log(db, request, admin.id, "integrations.test", f"Tested {name.value}: success={test_result['success']}")
    return test_result


# ---------------------------------------------------------------------------
# POST /{name}/toggle -- enable/disable integration
# ---------------------------------------------------------------------------
@router.post("/{name}/toggle", response_model=IntegrationDetailResponse, status_code=status.HTTP_200_OK)
async def toggle_integration(
    name: IntegrationName,
    body: ToggleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    result = await db.execute(
        select(Integration).where(Integration.name == name)
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")

    integration.is_enabled = body.enabled
    db.add(integration)
    await db.flush()

    state = "enabled" if body.enabled else "disabled"
    _log(db, request, admin.id, "integrations.toggle", f"{state.capitalize()} {name.value}")

    return IntegrationDetailResponse(
        name=integration.name.value,
        is_enabled=integration.is_enabled,
        config=None,
    )
