"""Database (MySQL / PostgreSQL) account model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

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
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), server_default=func.now(),
    )
