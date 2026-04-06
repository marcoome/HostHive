"""Pydantic v2 schemas for multi-server clustering."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ClusterNode schemas
# ---------------------------------------------------------------------------


class ClusterNodeCreate(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=1, max_length=45)
    port: int = Field(default=8443, ge=1, le=65535)
    api_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(..., min_length=1)
    role: str = Field(default="slave", pattern=r"^(master|slave)$")
    node_type: str = Field(default="all", pattern=r"^(web|mail|db|all)$")
    cpu_cores: int = Field(default=0, ge=0)
    ram_mb: int = Field(default=0, ge=0)
    disk_gb: int = Field(default=0, ge=0)


class ClusterNodeUpdate(BaseModel):
    hostname: Optional[str] = Field(None, min_length=1, max_length=255)
    ip_address: Optional[str] = Field(None, min_length=1, max_length=45)
    port: Optional[int] = Field(None, ge=1, le=65535)
    api_url: Optional[str] = Field(None, min_length=1, max_length=512)
    api_key: Optional[str] = Field(None, min_length=1)
    role: Optional[str] = Field(None, pattern=r"^(master|slave)$")
    node_type: Optional[str] = Field(None, pattern=r"^(web|mail|db|all)$")
    is_active: Optional[bool] = None
    cpu_cores: Optional[int] = Field(None, ge=0)
    ram_mb: Optional[int] = Field(None, ge=0)
    disk_gb: Optional[int] = Field(None, ge=0)


class ClusterNodeResponse(BaseModel):
    id: uuid.UUID
    hostname: str
    ip_address: str
    port: int
    api_url: str
    role: str
    node_type: str
    is_active: bool
    cpu_cores: int
    ram_mb: int
    disk_gb: int
    current_load: float
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    last_heartbeat: Optional[datetime] = None
    failed_checks: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ClusterNodeHealthResponse(BaseModel):
    id: uuid.UUID
    hostname: str
    ip_address: str
    is_active: bool
    role: str
    node_type: str
    reachable: bool
    latency_ms: Optional[float] = None
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    current_load: float
    last_heartbeat: Optional[datetime] = None
    failed_checks: int
    assignment_count: int


# ---------------------------------------------------------------------------
# Cluster overview
# ---------------------------------------------------------------------------


class ClusterOverviewResponse(BaseModel):
    total_nodes: int
    active_nodes: int
    inactive_nodes: int
    total_cpu_cores: int
    total_ram_mb: int
    total_disk_gb: int
    avg_cpu_usage: float
    avg_ram_usage: float
    avg_disk_usage: float
    avg_load: float
    total_assignments: int
    web_nodes: int
    mail_nodes: int
    db_nodes: int
    nodes: List[ClusterNodeResponse] = []


# ---------------------------------------------------------------------------
# Resource migration
# ---------------------------------------------------------------------------


class ClusterMigrateRequest(BaseModel):
    resource_type: str = Field(..., pattern=r"^(domain|mailbox|database)$")
    resource_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID


class ClusterMigrateResponse(BaseModel):
    status: str
    detail: str
    resource_type: str
    resource_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID


# ---------------------------------------------------------------------------
# Assignment schemas
# ---------------------------------------------------------------------------


class ClusterAssignmentResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    is_primary: bool
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


class ClusterBalanceResponse(BaseModel):
    status: str
    detail: str
    migrations_performed: int
