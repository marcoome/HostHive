"""Docker container model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class DockerContainer(Base):
    __tablename__ = "docker_containers"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    container_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
        comment="Docker container ID (short hash)",
    )
    name: Mapped[str] = mapped_column(String(128), index=True)
    image: Mapped[str] = mapped_column(String(512))
    ports_json: Mapped[Optional[str]] = mapped_column(
        Text, default=None,
        comment="JSON-encoded port mappings {host_port: container_port}",
    )
    env_json: Mapped[Optional[str]] = mapped_column(
        Text, default=None,
        comment="JSON-encoded environment variables",
    )
    volumes_json: Mapped[Optional[str]] = mapped_column(
        Text, default=None,
        comment="JSON-encoded volume mappings",
    )
    status: Mapped[str] = mapped_column(
        String(32), default="created",
        comment="Container status: created, running, stopped, removing",
    )
    domain: Mapped[Optional[str]] = mapped_column(
        String(255), default=None,
        comment="Domain for nginx reverse proxy (if applicable)",
    )
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=func.now(),
    )
