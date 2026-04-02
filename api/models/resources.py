"""Resource limit model -- per-user CPU, memory, and I/O limits."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class ResourceLimit(TimestampedBase):
    __tablename__ = "resource_limits"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    cpu_percent: Mapped[int] = mapped_column(Integer, default=100)
    memory_mb: Mapped[int] = mapped_column(Integer, default=1024)
    io_weight: Mapped[int] = mapped_column(Integer, default=100)
