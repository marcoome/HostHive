"""Activity / audit log model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None,
    )
    action: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(Text, default=None)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), default=None)
    created_at: Mapped[datetime] = mapped_column(
        default=_utcnow, server_default=func.now(),
    )
