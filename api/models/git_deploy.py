"""Git deployment model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class GitDeployment(Base):
    __tablename__ = "git_deployments"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), unique=True, index=True,
    )
    repo_url: Mapped[str] = mapped_column(String(1024))
    branch: Mapped[str] = mapped_column(String(255), default="main")
    deploy_key_public: Mapped[Optional[str]] = mapped_column(Text, default=None)
    deploy_key_private: Mapped[Optional[str]] = mapped_column(Text, default=None)  # Fernet-encrypted
    auto_deploy: Mapped[bool] = mapped_column(Boolean, default=True)
    build_command: Mapped[Optional[str]] = mapped_column(String(2048), default=None)
    post_deploy_hook: Mapped[Optional[str]] = mapped_column(String(2048), default=None)
    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    last_deploy_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    last_deploy_status: Mapped[Optional[str]] = mapped_column(String(32), default=None)  # success | failed | deploying
    last_commit_hash: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )


class DeployLog(Base):
    __tablename__ = "deploy_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("git_deployments.id", ondelete="CASCADE"), index=True,
    )
    commit_hash: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(32))  # success | failed | deploying
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual | webhook | api
    output: Mapped[Optional[str]] = mapped_column(Text, default=None)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )
