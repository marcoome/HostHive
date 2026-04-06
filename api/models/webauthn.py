"""WebAuthn / FIDO2 credential model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import TimestampedBase


class WebAuthnCredential(TimestampedBase):
    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, unique=True, index=True,
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    device_name: Mapped[Optional[str]] = mapped_column(
        String(128), default=None,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship back to user
    user = relationship("User", lazy="selectin")
