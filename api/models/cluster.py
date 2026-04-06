"""Cluster node and resource assignment models for multi-server clustering.

Supports web, mail, and database service clustering with heartbeat
monitoring, automatic failover, and resource load-balancing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.database import Base


class ClusterNode(Base):
    """A server node participating in the cluster."""

    __tablename__ = "cluster_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    hostname: Mapped[str] = mapped_column(String(255), unique=True)
    ip_address: Mapped[str] = mapped_column(String(45))  # IPv4 or IPv6
    port: Mapped[int] = mapped_column(Integer, default=8443)
    api_url: Mapped[str] = mapped_column(
        String(512),
    )  # e.g. https://node2.example.com:8443/api/v1
    api_key: Mapped[str] = mapped_column(Text)  # Encrypted via encrypt_value()
    role: Mapped[str] = mapped_column(
        String(10), default="slave",
    )  # "master" or "slave"
    node_type: Mapped[str] = mapped_column(
        String(10), default="all",
    )  # "web", "mail", "db", or "all"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Hardware / capacity
    cpu_cores: Mapped[int] = mapped_column(Integer, default=0)
    ram_mb: Mapped[int] = mapped_column(Integer, default=0)
    disk_gb: Mapped[int] = mapped_column(Integer, default=0)

    # Runtime metrics (updated by heartbeat)
    current_load: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_usage: Mapped[float] = mapped_column(Float, default=0.0)
    ram_usage: Mapped[float] = mapped_column(Float, default=0.0)
    disk_usage: Mapped[float] = mapped_column(Float, default=0.0)

    # Health tracking
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    failed_checks: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    # Relationships
    assignments: Mapped[list["ClusterAssignment"]] = relationship(
        back_populates="node", cascade="all, delete-orphan",
    )


class ClusterAssignment(Base):
    """Tracks which resource is assigned to which cluster node."""

    __tablename__ = "cluster_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cluster_nodes.id", ondelete="CASCADE"), index=True,
    )
    resource_type: Mapped[str] = mapped_column(
        String(20),
    )  # "domain", "mailbox", "database"
    resource_id: Mapped[uuid.UUID] = mapped_column(index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    # Relationships
    node: Mapped["ClusterNode"] = relationship(back_populates="assignments")
