"""DNS cluster node model for multi-server zone transfers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class DnsClusterNode(Base):
    __tablename__ = "dns_cluster_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    hostname: Mapped[str] = mapped_column(String(255), unique=True)
    ip_address: Mapped[str] = mapped_column(String(45))  # IPv4 or IPv6
    port: Mapped[int] = mapped_column(Integer, default=53)
    api_url: Mapped[str] = mapped_column(String(512))  # e.g. https://ns2.example.com:8443/api/v1
    api_key: Mapped[str] = mapped_column(Text)  # Encrypted via encrypt_value()
    role: Mapped[str] = mapped_column(
        String(10), default="slave",
    )  # "master" or "slave"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
