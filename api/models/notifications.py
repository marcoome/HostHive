"""User notification model."""

from __future__ import annotations

import enum
import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class NotificationLevel(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Notification(TimestampedBase):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    message: Mapped[str] = mapped_column(Text)
    level: Mapped[NotificationLevel] = mapped_column(
        Enum(NotificationLevel, name="notification_level", native_enum=True),
        default=NotificationLevel.INFO,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    link: Mapped[Optional[str]] = mapped_column(String(512), default=None)
