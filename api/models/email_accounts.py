"""Email account model."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True,
    )
    address: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, default=None)
    quota_mb: Mapped[int] = mapped_column(Integer, default=1024)
    quota_used_mb: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_emails_per_hour: Mapped[int] = mapped_column(Integer, default=200)

    # Autoresponder fields
    autoresponder_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    autoresponder_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    autoresponder_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    autoresponder_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)
    autoresponder_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None)

    # Spam filter fields
    spam_filter_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    spam_threshold: Mapped[float] = mapped_column(Float, default=5.0)
    spam_action: Mapped[str] = mapped_column(String(20), default="move")
    spam_whitelist: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    spam_blacklist: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
