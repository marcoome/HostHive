"""User account model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import TimestampedBase


class BackupFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"

if TYPE_CHECKING:
    from api.models.packages import Package
    from api.models.user_environment import UserEnvironment


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    RESELLER = "reseller"
    USER = "user"


class User(TimestampedBase):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True),
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    package_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("packages.id", ondelete="SET NULL"),
        default=None,
    )
    # Two-Factor Authentication
    totp_secret: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_backup_codes: Mapped[Optional[list]] = mapped_column(JSON, default=None)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )

    # Locale / language preference
    locale: Mapped[Optional[str]] = mapped_column(String(10), default="en")

    # Backup preferences
    backup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_frequency: Mapped[Optional[str]] = mapped_column(
        String(16), default="daily",
    )
    backup_type: Mapped[Optional[str]] = mapped_column(
        String(16), default="full",
    )
    backup_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    backup_retention_count: Mapped[int] = mapped_column(Integer, default=5)
    last_backup_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    # Relationships
    package: Mapped[Optional["Package"]] = relationship(
        lazy="selectin",
        foreign_keys=[package_id],
        overlaps="users",
    )
    environment: Mapped[Optional["UserEnvironment"]] = relationship(
        back_populates="user", lazy="selectin", uselist=False,
    )
