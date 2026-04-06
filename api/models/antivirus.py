"""Antivirus scan and quarantine models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import TimestampedBase


class ScanStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanResult(TimestampedBase):
    __tablename__ = "antivirus_scans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    scan_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", native_enum=True),
        default=ScanStatus.PENDING,
    )
    files_scanned: Mapped[int] = mapped_column(Integer, default=0)
    infected_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_files: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=None)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, default=None)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, default=None)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)

    quarantine_entries: Mapped[list["QuarantineEntry"]] = relationship(
        "QuarantineEntry", back_populates="scan", lazy="selectin",
    )


class QuarantineEntry(TimestampedBase):
    __tablename__ = "antivirus_quarantine"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("antivirus_scans.id", ondelete="CASCADE"), index=True,
    )
    original_path: Mapped[str] = mapped_column(String(1024))
    quarantine_path: Mapped[str] = mapped_column(String(1024))
    threat_name: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, default=None)
    restored: Mapped[bool] = mapped_column(default=False)
    deleted: Mapped[bool] = mapped_column(default=False)

    scan: Mapped["ScanResult"] = relationship(
        "ScanResult", back_populates="quarantine_entries", lazy="selectin",
    )
