"""Hosting package / plan model."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, Float, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import TimestampedBase

if TYPE_CHECKING:
    from api.models.users import User


class Package(TimestampedBase):
    __tablename__ = "packages"

    name: Mapped[str] = mapped_column(String(128), unique=True)
    disk_quota_mb: Mapped[int] = mapped_column(Integer, default=5120)
    bandwidth_gb: Mapped[int] = mapped_column(Integer, default=100)
    max_domains: Mapped[int] = mapped_column(Integer, default=5)
    max_databases: Mapped[int] = mapped_column(Integer, default=5)
    max_email_accounts: Mapped[int] = mapped_column(Integer, default=20)
    max_ftp_accounts: Mapped[int] = mapped_column(Integer, default=5)
    max_cron_jobs: Mapped[int] = mapped_column(Integer, default=5)
    price_monthly: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=Decimal("0.00"),
    )

    # Docker isolation resource limits
    cpu_cores: Mapped[float] = mapped_column(Float, default=1.0)  # Docker --cpus
    ram_mb: Mapped[int] = mapped_column(Integer, default=1024)  # Docker --memory
    io_bandwidth_mbps: Mapped[int] = mapped_column(Integer, default=100)
    iops_limit: Mapped[int] = mapped_column(Integer, default=1000)
    inodes_limit: Mapped[int] = mapped_column(Integer, default=500000)
    nproc_limit: Mapped[int] = mapped_column(Integer, default=100)
    default_webserver: Mapped[str] = mapped_column(String(32), default="nginx")
    default_db_version: Mapped[str] = mapped_column(String(32), default="mariadb11")
    redis_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    redis_memory_mb: Mapped[int] = mapped_column(Integer, default=64)
    memcached_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memcached_memory_mb: Mapped[int] = mapped_column(Integer, default=64)

    # Relationships
    # NOTE: Use "noload" to prevent circular eager loading.
    # Loading a User selectin-loads its Package; if Package also
    # selectin-loads all its Users, SQLAlchemy enters an async
    # greenlet loop that causes MissingGreenlet errors.
    # When you need package.users, query explicitly with selectinload.
    users: Mapped[List["User"]] = relationship(
        back_populates="package", lazy="noload",
    )
