"""Pydantic schemas for integrations, API keys, webhooks, and status incidents."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from api.models.integrations import (
    ApiKeyScope,
    IncidentSeverity,
    IncidentStatus,
    IntegrationName,
    WebhookDirection,
)


# ═══════════════════════════════════════════════════════════════════════════
# Integration provider configs
# ═══════════════════════════════════════════════════════════════════════════


class CloudflareConfig(BaseModel):
    api_key: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    zone_id: str = Field(..., min_length=1)


class S3Config(BaseModel):
    endpoint: str = Field(..., min_length=1, description="S3-compatible endpoint URL")
    bucket: str = Field(..., min_length=1)
    access_key: str = Field(..., min_length=1)
    secret_key: str = Field(..., min_length=1)
    region: str = Field(default="us-east-1")


class TelegramConfig(BaseModel):
    bot_token: str = Field(..., min_length=1)
    chat_id: str = Field(..., min_length=1)


class SlackConfig(BaseModel):
    webhook_url: str = Field(..., min_length=1)


class DiscordConfig(BaseModel):
    webhook_url: str = Field(..., min_length=1)


class WHMCSConfig(BaseModel):
    api_url: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    allowed_ips: List[str] = Field(default_factory=list)


class StripeConfig(BaseModel):
    secret_key: str = Field(..., min_length=1)
    webhook_secret: str = Field(..., min_length=1)
    currency: str = Field(default="usd", max_length=3)


class GrafanaConfig(BaseModel):
    enabled: bool = Field(default=True)


class WireguardConfig(BaseModel):
    endpoint: str = Field(..., min_length=1, description="Public IP or hostname")
    listen_port: int = Field(default=51820, ge=1, le=65535)
    address_range: str = Field(
        default="10.0.0.0/24",
        description="CIDR range for WireGuard peers",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Integration CRUD schemas
# ═══════════════════════════════════════════════════════════════════════════


class IntegrationConfig(BaseModel):
    """Payload sent when creating or fully replacing an integration."""

    name: IntegrationName
    is_enabled: bool = True
    config: dict = Field(
        ..., description="Provider-specific config (e.g. CloudflareConfig fields)."
    )


class IntegrationUpdate(BaseModel):
    """Partial update — all fields optional."""

    is_enabled: Optional[bool] = None
    config: Optional[dict] = None


class IntegrationResponse(BaseModel):
    id: uuid.UUID
    name: IntegrationName
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# API Key schemas
# ═══════════════════════════════════════════════════════════════════════════


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scope: ApiKeyScope = ApiKeyScope.READ_ONLY
    custom_permissions: Optional[List[str]] = None
    expires_at: Optional[datetime] = None


class ApiKeyResponse(BaseModel):
    """Response returned after creation or listing.

    The full raw key is ONLY included in the ``key`` field immediately after
    creation (and is ``None`` on subsequent reads).
    """

    id: uuid.UUID
    name: str
    key_prefix: str
    scope: ApiKeyScope
    custom_permissions: Optional[List[str]] = None
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    key: Optional[str] = Field(
        default=None,
        description="Full API key — only returned once at creation time.",
    )

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Webhook Log schemas
# ═══════════════════════════════════════════════════════════════════════════


class WebhookLogResponse(BaseModel):
    id: uuid.UUID
    integration_name: str
    direction: WebhookDirection
    url: str
    payload_json: Optional[str] = None
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════════
# Status Incident schemas
# ═══════════════════════════════════════════════════════════════════════════


class StatusIncidentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    severity: IncidentSeverity = IncidentSeverity.MINOR
    status: IncidentStatus = IncidentStatus.INVESTIGATING


class StatusIncidentResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    severity: IncidentSeverity
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
