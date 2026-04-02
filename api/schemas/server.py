"""Server / service / firewall schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ServerStatsResponse(BaseModel):
    id: uuid.UUID
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    net_in_bytes: int
    net_out_bytes: int
    recorded_at: datetime

    model_config = {"from_attributes": True}


class ServiceStatus(BaseModel):
    name: str
    is_running: bool
    uptime_seconds: Optional[int] = None
    memory_mb: Optional[float] = None


class FirewallRule(BaseModel):
    action: str = Field(..., pattern=r"^(allow|deny|reject)$")
    protocol: str = Field(default="tcp", pattern=r"^(tcp|udp|any)$")
    port: Optional[str] = Field(default=None, max_length=32)
    source: str = Field(default="any", max_length=64)
    comment: Optional[str] = Field(default=None, max_length=255)
