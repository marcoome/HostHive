"""Backup model."""

from __future__ import annotations

import enum
import uuid
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import TimestampedBase


class BackupType(str, enum.Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    FILES_ONLY = "files_only"
    DB_ONLY = "db_only"


class BackupStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Backup(TimestampedBase):
    __tablename__ = "backups"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    backup_type: Mapped[BackupType] = mapped_column(
        Enum(BackupType, name="backup_type", native_enum=True),
        default=BackupType.FULL,
    )
    status: Mapped[BackupStatus] = mapped_column(
        Enum(BackupStatus, name="backup_status", native_enum=True),
        default=BackupStatus.PENDING,
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, default=None)
    error_message: Mapped[Optional[str]] = mapped_column(String(1024), default=None)
    remote_key: Mapped[Optional[str]] = mapped_column(
        String(512), default=None,
        comment="S3 object key when backup has been uploaded to remote storage.",
    )
    auto_backup: Mapped[bool] = mapped_column(Boolean, default=False)

    # Incremental backup chain
    parent_backup_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("backups.id", ondelete="SET NULL"), nullable=True, default=None,
    )
    backup_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=None)

    parent_backup: Mapped[Optional["Backup"]] = relationship(
        "Backup", remote_side="Backup.id", lazy="selectin",
    )
