"""App deployment model -- tracks deployed Node.js / Python applications."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class App(TimestampedBase):
    __tablename__ = "apps"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    runtime: Mapped[str] = mapped_column(String(20))  # "nodejs" or "python"
    port: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="stopped")
    version: Mapped[str] = mapped_column(String(20), default="")
