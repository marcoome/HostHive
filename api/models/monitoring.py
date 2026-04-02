"""Smart monitoring models -- health checks, incidents, bandwidth, anomalies."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.core.database import Base


class HealthStatus(str, enum.Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


class AnomalySeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HealthCheck(Base):
    """Individual health-check result for a monitored service."""

    __tablename__ = "health_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    service_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus, name="health_status", native_enum=True),
    )
    response_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    checked_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(), index=True,
    )


class MonitoringIncident(Base):
    """Tracks service outages and auto-restart attempts."""

    __tablename__ = "monitoring_incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    service_name: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(),
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    auto_restarted: Mapped[bool] = mapped_column(Boolean, default=False)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)


class DomainBandwidth(Base):
    """Daily bandwidth aggregation per domain (parsed from nginx logs)."""

    __tablename__ = "domain_bandwidth"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), index=True,
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    bytes_in: Mapped[int] = mapped_column(Integer, default=0)
    bytes_out: Mapped[int] = mapped_column(Integer, default=0)
    requests_count: Mapped[int] = mapped_column(Integer, default=0)


class AnomalyAlert(Base):
    """Statistical anomaly detected in server metrics."""

    __tablename__ = "anomaly_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    metric_name: Mapped[str] = mapped_column(String(64), index=True)
    current_value: Mapped[float] = mapped_column(Float)
    baseline_mean: Mapped[float] = mapped_column(Float)
    baseline_stddev: Mapped[float] = mapped_column(Float)
    severity: Mapped[AnomalySeverity] = mapped_column(
        Enum(AnomalySeverity, name="anomaly_severity", native_enum=True),
    )
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(), index=True,
    )
