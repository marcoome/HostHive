"""Reseller system models -- branding and resource limits."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class ResellerBranding(TimestampedBase):
    """Per-reseller white-label branding configuration."""

    __tablename__ = "reseller_branding"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
    )
    logo_url: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    primary_color: Mapped[str] = mapped_column(String(7), default="#4f46e5")
    panel_title: Mapped[str] = mapped_column(String(128), default="HostHive")
    custom_domain: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, default=None, index=True,
    )
    hide_hosthive_branding: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_css: Mapped[Optional[str]] = mapped_column(Text, default=None)


class ResellerLimit(TimestampedBase):
    """Resource quota overrides for a reseller's sub-user pool."""

    __tablename__ = "reseller_limits"

    reseller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
    )
    max_users: Mapped[int] = mapped_column(Integer, default=10)
    max_total_disk_mb: Mapped[int] = mapped_column(Integer, default=51200)
    max_total_bandwidth_gb: Mapped[int] = mapped_column(Integer, default=1000)
    used_users: Mapped[int] = mapped_column(Integer, default=0)
    used_disk_mb: Mapped[int] = mapped_column(Integer, default=0)
    used_bandwidth_gb: Mapped[float] = mapped_column(Float, default=0.0)

    # API rate-limiting quotas
    api_rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=100)
    api_rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=3000)
    api_burst_limit: Mapped[int] = mapped_column(Integer, default=20)
