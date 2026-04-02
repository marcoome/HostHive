"""User Docker environment model — tracks each user's isolated container stack."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import TimestampedBase

if TYPE_CHECKING:
    from api.models.users import User


class UserEnvironment(TimestampedBase):
    __tablename__ = "user_environments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    docker_network: Mapped[str] = mapped_column(String(128))
    webserver: Mapped[str] = mapped_column(
        String(32), default="nginx",
    )  # nginx / apache / openlitespeed / caddy / varnish
    db_version: Mapped[str] = mapped_column(
        String(32), default="mariadb11",
    )  # mysql8 / mysql9 / mariadb11 / percona8
    php_versions: Mapped[Any] = mapped_column(
        JSON, default=lambda: ["8.2"],
    )  # e.g. ["8.1", "8.2"]
    redis_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memcached_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    container_ids: Mapped[Any] = mapped_column(
        JSON, default=dict,
    )  # {"web": "abc123", "db": "def456", "php82": "...", ...}
    cpu_limit: Mapped[float] = mapped_column(Float, default=1.0)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=1024)
    status: Mapped[str] = mapped_column(
        String(32), default="creating",
    )  # active / suspended / creating / error / destroyed

    # Relationships
    user: Mapped["User"] = relationship(
        back_populates="environment", lazy="selectin",
    )
