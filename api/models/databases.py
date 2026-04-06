"""Database (MySQL / PostgreSQL) account model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.database import Base


class DbType(str, enum.Enum):
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"


class Database(Base):
    __tablename__ = "databases"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    db_name: Mapped[str] = mapped_column(String(128), unique=True)
    db_user: Mapped[str] = mapped_column(String(128))
    db_password_encrypted: Mapped[str] = mapped_column(String(512))
    db_type: Mapped[DbType] = mapped_column(
        Enum(DbType, name="db_type", native_enum=True),
        default=DbType.MYSQL,
    )
    remote_access: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
    )
    allowed_hosts: Mapped[Optional[str]] = mapped_column(
        Text, default='["localhost"]', server_default='["localhost"]',
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )

    # Relationship to additional database users
    extra_users: Mapped[list["DatabaseUser"]] = relationship(
        "DatabaseUser", back_populates="database", cascade="all, delete-orphan",
    )


class DatabaseUser(Base):
    """Additional users (beyond the primary owner) for a database."""
    __tablename__ = "database_users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    database_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("databases.id", ondelete="CASCADE"), index=True,
    )
    username: Mapped[str] = mapped_column(String(128))
    password_encrypted: Mapped[str] = mapped_column(String(512))
    permissions: Mapped[str] = mapped_column(
        String(256), default="ALL", server_default="ALL",
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )

    database: Mapped["Database"] = relationship("Database", back_populates="extra_users")
