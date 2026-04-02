"""SSL certificate model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class CertProvider(str, enum.Enum):
    LETS_ENCRYPT = "letsencrypt"
    CUSTOM = "custom"
    SELF_SIGNED = "self_signed"


class SSLCertificate(TimestampedBase):
    __tablename__ = "ssl_certificates"

    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True,
    )
    domain_name: Mapped[str] = mapped_column(String(255), index=True)
    provider: Mapped[CertProvider] = mapped_column(
        Enum(CertProvider, name="cert_provider", native_enum=True),
        default=CertProvider.LETS_ENCRYPT,
    )
    cert_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    key_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    expires_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    last_renewed_at: Mapped[Optional[datetime]] = mapped_column(default=None)
