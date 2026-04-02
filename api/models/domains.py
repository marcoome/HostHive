"""Domain model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    domain_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    document_root: Mapped[str] = mapped_column(String(512))
    php_version: Mapped[str] = mapped_column(String(8), default="8.2")
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_cert_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    ssl_key_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    nginx_template: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default=func.now(),
    )
