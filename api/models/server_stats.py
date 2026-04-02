"""Server statistics model for time-series metrics."""

from __future__ import annotations

from sqlalchemy import Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import TimestampedBase


class ServerStat(TimestampedBase):
    __tablename__ = "server_stats"

    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_used_mb: Mapped[int] = mapped_column(Integer, default=0)
    memory_total_mb: Mapped[int] = mapped_column(Integer, default=0)
    disk_percent: Mapped[float] = mapped_column(Float, default=0.0)
    disk_used_gb: Mapped[float] = mapped_column(Float, default=0.0)
    disk_total_gb: Mapped[float] = mapped_column(Float, default=0.0)
    load_avg_1: Mapped[float] = mapped_column(Float, default=0.0)
    load_avg_5: Mapped[float] = mapped_column(Float, default=0.0)
    load_avg_15: Mapped[float] = mapped_column(Float, default=0.0)
    network_rx_bytes: Mapped[int] = mapped_column(Integer, default=0)
    network_tx_bytes: Mapped[int] = mapped_column(Integer, default=0)
    active_connections: Mapped[int] = mapped_column(Integer, default=0)
