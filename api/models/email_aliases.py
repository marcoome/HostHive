"""Email alias model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class EmailAlias(Base):
    __tablename__ = "email_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    source: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    destination: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=func.now(),
    )
