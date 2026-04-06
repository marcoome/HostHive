"""RuntimeApp model -- Node.js and Python application manager."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class RuntimeApp(TimestampedBase):
    __tablename__ = "runtime_apps"

    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    app_type: Mapped[str] = mapped_column(String(10))  # "node" or "python"
    app_name: Mapped[str] = mapped_column(String(255), default="")
    app_root: Mapped[str] = mapped_column(String(512))
    entry_point: Mapped[str] = mapped_column(String(255), default="app.js")
    runtime_version: Mapped[str] = mapped_column(String(20), default="20")  # e.g. "20" for Node, "3.11" for Python
    port: Mapped[int] = mapped_column(Integer)
    env_vars: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)
    startup_command: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
