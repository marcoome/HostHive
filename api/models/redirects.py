"""Redirect model -- URL redirects associated with a domain."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class Redirect(Base):
    __tablename__ = "redirects"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True,
    )
    source_path: Mapped[str] = mapped_column(String(2048))
    destination_url: Mapped[str] = mapped_column(String(2048))
    redirect_type: Mapped[int] = mapped_column(Integer, default=301)  # 301 / 302 / 307
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=func.now(),
    )
