"""DNS record model."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class DnsRecord(Base):
    __tablename__ = "dns_records"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dns_zones.id", ondelete="CASCADE"), index=True,
    )
    record_type: Mapped[str] = mapped_column(String(16))  # A, AAAA, CNAME, MX, TXT, ...
    name: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(String(1024))
    ttl: Mapped[int] = mapped_column(Integer, default=3600)
    priority: Mapped[Optional[int]] = mapped_column(Integer, default=None)
