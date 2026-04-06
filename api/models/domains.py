"""Domain model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    webserver: Mapped[str] = mapped_column(String(16), default="nginx")  # nginx | apache | nginx_apache
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_cert_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    ssl_key_path: Mapped[Optional[str]] = mapped_column(String(512), default=None)
    nginx_template: Mapped[Optional[str]] = mapped_column(String(64), default="default")
    custom_nginx_config: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cache_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cache_type: Mapped[str] = mapped_column(String(16), default="fastcgi")  # fastcgi | proxy | none
    cache_ttl: Mapped[int] = mapped_column(Integer, default=3600)  # seconds
    cache_bypass_cookie: Mapped[str] = mapped_column(String(255), default="wordpress_logged_in")
    catch_all_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    hotlink_protection: Mapped[bool] = mapped_column(Boolean, default=False)
    hotlink_allowed_domains: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    hotlink_extensions: Mapped[str] = mapped_column(String(512), default="jpg,jpeg,png,gif,webp,svg,mp4,mp3")
    hotlink_redirect_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, default=None)
    custom_error_pages: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)  # {404: "/custom_404.html", 500: "/custom_500.html", ...}

    # Subdomain support: null parent_domain_id means top-level domain
    parent_domain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True, nullable=True, default=None,
    )
    is_subdomain: Mapped[bool] = mapped_column(Boolean, default=False)

    # Self-referential relationship
    subdomains: Mapped[list["Domain"]] = relationship(
        "Domain",
        back_populates="parent_domain",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys=[parent_domain_id],
    )
    parent_domain: Mapped[Optional["Domain"]] = relationship(
        "Domain",
        back_populates="subdomains",
        remote_side="Domain.id",
        foreign_keys=[parent_domain_id],
        lazy="selectin",
    )

    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )
