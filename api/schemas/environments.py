"""Pydantic schemas for user Docker environments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class EnvironmentCreate(BaseModel):
    """Request body for creating a user environment."""
    webserver: str = Field(default="nginx", description="Web server: nginx, apache, openlitespeed, caddy, varnish")
    db_version: str = Field(default="mariadb11", description="DB version: mysql8, mysql9, mariadb11, percona8")
    php_versions: List[str] = Field(default=["8.2"], description="PHP versions to install")
    redis_enabled: bool = False
    redis_memory_mb: int = Field(default=64, ge=16, le=2048)
    memcached_enabled: bool = False
    memcached_memory_mb: int = Field(default=64, ge=16, le=2048)


class WebserverSwitch(BaseModel):
    """Request body for switching the web server."""
    webserver: str = Field(..., description="Target web server: nginx, apache, openlitespeed, caddy, varnish")


class DbSwitch(BaseModel):
    """Request body for switching the database version."""
    db_version: str = Field(..., description="Target DB version: mysql8, mysql9, mariadb11, percona8")


class PhpVersionAdd(BaseModel):
    """Request body for adding a PHP version."""
    version: str = Field(..., description="PHP version: 7.4, 8.0, 8.1, 8.2, 8.3")


class PhpVersionRemove(BaseModel):
    """Request body for removing a PHP version."""
    version: str = Field(..., description="PHP version to remove")


class CacheToggle(BaseModel):
    """Request body for enabling/disabling Redis or Memcached."""
    enable: bool
    memory_mb: int = Field(default=64, ge=16, le=2048)


class ResourceUpdate(BaseModel):
    """Request body for updating resource limits."""
    cpu_cores: float = Field(..., gt=0, le=32, description="CPU cores (Docker --cpus)")
    ram_mb: int = Field(..., ge=128, le=65536, description="RAM in MB (Docker --memory)")
    io_bandwidth_mbps: int = Field(default=100, ge=1, le=10000, description="I/O bandwidth MB/s")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class EnvironmentResponse(BaseModel):
    """Full environment details."""
    id: uuid.UUID
    user_id: uuid.UUID
    docker_network: str
    webserver: str
    db_version: str
    php_versions: List[str]
    redis_enabled: bool
    memcached_enabled: bool
    container_ids: Dict[str, Any]
    cpu_limit: float
    memory_limit_mb: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnvironmentListResponse(BaseModel):
    """Paginated list of environments."""
    items: List[EnvironmentResponse]
    total: int


class ContainerInfo(BaseModel):
    """Single container status info."""
    container_id: str
    name: str
    image: str
    status: str
    state: str = ""
    ports: str = ""


class ContainerListResponse(BaseModel):
    """List of containers for a user."""
    username: str
    containers: List[Dict[str, Any]]
    total: int


class ResourceUsageResponse(BaseModel):
    """Resource usage across all user containers."""
    username: str
    total_cpu_percent: float
    containers: List[Dict[str, Any]]
    container_count: int


class OperationResponse(BaseModel):
    """Generic response for environment operations."""
    ok: bool = True
    detail: str = ""
    data: Optional[Dict[str, Any]] = None
