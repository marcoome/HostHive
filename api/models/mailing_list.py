"""Mailing list models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.database import Base


class MailingList(Base):
    __tablename__ = "mailing_lists"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(255), index=True)
    list_address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    owner_email: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_moderated: Mapped[bool] = mapped_column(Boolean, default=False)
    archive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_message_size_kb: Mapped[int] = mapped_column(Integer, default=10240)
    reply_to_list: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=func.now(),
    )

    members: Mapped[list["MailingListMember"]] = relationship(
        "MailingListMember", back_populates="mailing_list", cascade="all, delete-orphan",
    )


class MailingListMember(Base):
    __tablename__ = "mailing_list_members"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailing_lists.id", ondelete="CASCADE"), index=True,
    )
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=func.now(),
    )

    mailing_list: Mapped["MailingList"] = relationship(
        "MailingList", back_populates="members",
    )
