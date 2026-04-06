"""Directory privacy (.htpasswd) model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class DirectoryPrivacy(Base):
    __tablename__ = "directory_privacy"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True,
    )
    path: Mapped[str] = mapped_column(String(512))  # e.g. "/admin"
    auth_name: Mapped[str] = mapped_column(String(255), default="Restricted Area")
    users: Mapped[Optional[str]] = mapped_column(Text, default="[]")  # JSON list of {username, password_hash}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )
