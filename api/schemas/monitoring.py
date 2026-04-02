"""Pydantic schemas for the smart monitoring module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from api.models.monitoring import AnomalySeverity, HealthStatus


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

class HealthCheckResponse(BaseModel):
    id: uuid.UUID
    service_name: str
    status: HealthStatus
    response_time_ms: float
    error_message: Optional[str] = None
    checked_at: datetime

    model_config = {"from_attributes": True}


class HealthCheckListResponse(BaseModel):
    items: List[HealthCheckResponse]
    total: int


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

class IncidentResponse(BaseModel):
    id: uuid.UUID
    service_name: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    auto_restarted: bool
    restart_count: int
    escalated: bool
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class IncidentListResponse(BaseModel):
    items: List[IncidentResponse]
    total: int


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------

class AnomalyAlertResponse(BaseModel):
    id: uuid.UUID
    metric_name: str
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    severity: AnomalySeverity
    is_acknowledged: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AnomalyListResponse(BaseModel):
    items: List[AnomalyAlertResponse]
    total: int


# ---------------------------------------------------------------------------
# Disk prediction
# ---------------------------------------------------------------------------

class DiskPredictionResponse(BaseModel):
    days_until_full: Optional[float] = Field(
        None, description="Estimated days until disk is 100% full, or null if stable/declining.",
    )
    current_usage_percent: float
    current_used_gb: float
    total_gb: float
    trend_gb_per_day: float = Field(
        description="Linear trend in GB/day (positive = growing).",
    )


# ---------------------------------------------------------------------------
# Bandwidth
# ---------------------------------------------------------------------------

class DomainBandwidthResponse(BaseModel):
    date: date
    bytes_in: int
    bytes_out: int
    requests_count: int

    model_config = {"from_attributes": True}


class BandwidthListResponse(BaseModel):
    domain: str
    items: List[DomainBandwidthResponse]
    total_bytes_in: int
    total_bytes_out: int
    total_requests: int


# ---------------------------------------------------------------------------
# Traffic heatmap
# ---------------------------------------------------------------------------

class TrafficHeatmapResponse(BaseModel):
    """7 rows (days, newest first) x 24 columns (hours) of request counts."""
    labels_days: List[str] = Field(description="Date labels for each row.")
    labels_hours: List[int] = Field(
        default=[i for i in range(24)],
        description="Hour labels 0-23.",
    )
    data: List[List[int]] = Field(description="data[day][hour] = request count.")


# ---------------------------------------------------------------------------
# Real-time dashboard
# ---------------------------------------------------------------------------

class RealtimeStatsResponse(BaseModel):
    cpu_percent: float
    cpu_per_core: List[float] = Field(default_factory=list, description="Per-core CPU usage percentages.")
    memory_percent: float
    memory_used: int = Field(0, description="Memory used in bytes.")
    memory_total: int = Field(0, description="Total memory in bytes.")
    # Legacy aliases kept for backward compat
    memory_used_mb: int = 0
    memory_total_mb: int = 0
    disk_percent: float
    disk_used: int = Field(0, description="Disk used in bytes.")
    disk_total: int = Field(0, description="Disk total in bytes.")
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    net_bytes_sent: int = 0
    net_bytes_recv: int = 0
    # Legacy aliases
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    load_1: float = 0.0
    load_5: float = 0.0
    load_15: float = 0.0
    # Legacy aliases
    load_avg_1: float = 0.0
    load_avg_5: float = 0.0
    load_avg_15: float = 0.0
    uptime_seconds: float = 0.0
    processes: int = 0
    connections: int = 0
    active_connections: int = 0
