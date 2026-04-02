"""Resource limit schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class UserLimitsUpdate(BaseModel):
    cpu_percent: int = Field(default=100, ge=1, le=10000, description="CPU limit as % of one core")
    memory_mb: int = Field(default=1024, ge=32, description="Memory limit in MB")
    io_weight: int = Field(default=100, ge=1, le=10000, description="I/O weight (1-10000)")


class UserLimitsResponse(BaseModel):
    username: str
    cpu_percent: int
    memory_mb: int
    io_weight: int


class UserUsageResponse(BaseModel):
    username: str
    cpu: Optional[dict[str, Any]] = None
    memory: Optional[dict[str, Any]] = None
    io: Optional[list[dict[str, Any]]] = None
    limits: Optional[dict[str, Any]] = None


class PHPFPMLimitsUpdate(BaseModel):
    max_children: int = Field(default=5, ge=1, le=1000)
    memory_limit: str = Field(default="256M", pattern=r"^\d+[MmGg]$")
    php_version: str = Field(default="8.2", pattern=r"^\d+\.\d+$")


class PHPFPMLimitsResponse(BaseModel):
    domain: str
    php_version: str
    pool_name: str
    max_children: int
    memory_limit: str
    config_path: str


class DomainUsageResponse(BaseModel):
    domain: str
    process_count: int = 0
    pids: list[str] = []
    memory_kb: int = 0
    memory_mb: float = 0.0


class ResourceOverviewEntry(BaseModel):
    username: str
    cpu_percent: int = 100
    memory_mb: int = 1024
    io_weight: int = 100


class ResourceLimitDB(BaseModel):
    """Schema for the database model."""
    id: uuid.UUID
    user_id: uuid.UUID
    cpu_percent: int
    memory_mb: int
    io_weight: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
