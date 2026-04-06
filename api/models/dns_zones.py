"""DNS zone model."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class DnsZone(Base):
    __tablename__ = "dns_zones"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    domain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("domains.id", ondelete="SET NULL"), index=True, nullable=True,
    )
    zone_name: Mapped[str] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Cloudflare integration
    cloudflare_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cloudflare_config: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )  # Encrypted JSON: {"api_key": ..., "email": ..., "zone_id": ...}

    # DNSSEC
    dnssec_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dnssec_algorithm: Mapped[str] = mapped_column(
        String(64), default="ECDSAP256SHA256",
    )
    ds_record: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )  # DS record for parent zone delegation
