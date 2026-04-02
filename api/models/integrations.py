"""Integration, webhook log, API key, and status incident models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class IntegrationName(str, enum.Enum):
    CLOUDFLARE = "cloudflare"
    S3 = "s3"
    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
    WHMCS = "whmcs"
    STRIPE = "stripe"
    GRAFANA = "grafana"
    WIREGUARD = "wireguard"


class WebhookDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ApiKeyScope(str, enum.Enum):
    READ_ONLY = "read_only"
    FULL_ACCESS = "full_access"
    CUSTOM = "custom"


class IncidentSeverity(str, enum.Enum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    MONITORING = "monitoring"
    RESOLVED = "resolved"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Integration(TimestampedBase):
    """Stores integration configurations per admin."""

    __tablename__ = "integrations"

    name: Mapped[IntegrationName] = mapped_column(
        Enum(IntegrationName, name="integration_name", native_enum=True),
        unique=True,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[Optional[str]] = mapped_column(
        Text, default=None,
        comment="Fernet-encrypted JSON blob containing API keys and settings.",
    )


class WebhookLog(TimestampedBase):
    """Logs incoming and outgoing webhook calls."""

    __tablename__ = "webhook_logs"

    integration_name: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[WebhookDirection] = mapped_column(
        Enum(WebhookDirection, name="webhook_direction", native_enum=True),
    )
    url: Mapped[str] = mapped_column(String(2048))
    payload_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    status_code: Mapped[Optional[int]] = mapped_column(default=None)
    response_body: Mapped[Optional[str]] = mapped_column(Text, default=None)


class ApiKey(TimestampedBase):
    """User API keys for automation."""

    __tablename__ = "api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(128))
    key_hash: Mapped[str] = mapped_column(String(255))
    key_prefix: Mapped[str] = mapped_column(
        String(8), comment="First 8 characters of the key, for display purposes.",
    )
    scope: Mapped[ApiKeyScope] = mapped_column(
        Enum(ApiKeyScope, name="api_key_scope", native_enum=True),
        default=ApiKeyScope.READ_ONLY,
    )
    custom_permissions: Mapped[Optional[str]] = mapped_column(
        Text, default=None,
        comment="JSON array of permission strings when scope is 'custom'.",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StatusIncident(TimestampedBase):
    """Public status page incidents."""

    __tablename__ = "status_incidents"

    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity", native_enum=True),
        default=IncidentSeverity.MINOR,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status", native_enum=True),
        default=IncidentStatus.INVESTIGATING,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(default=None)
