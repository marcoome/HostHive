"""Shared base model with common columns for all domain tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


def _utcnow() -> datetime:
    """Return timezone-aware UTC now (avoids deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


class TimestampedBase(Base):
    """Abstract base providing id, created_at, and updated_at."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    created_at: Mapped[datetime] = mapped_column(
        default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=_utcnow,
        server_default=func.now(),
        onupdate=func.now(),
    )
