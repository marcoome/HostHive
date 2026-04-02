"""Pydantic schemas for Docker container management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ContainerDeploy(BaseModel):
    image: str = Field(..., min_length=1, max_length=512, description="Docker image (e.g. nginx:latest)")
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    ports: Optional[Dict[str, str]] = Field(
        default=None,
        description="Port mappings: {host_port: container_port}",
    )
    env: Optional[Dict[str, str]] = Field(
        default=None,
        description="Environment variables",
    )
    volumes: Optional[Dict[str, str]] = Field(
        default=None,
        description="Volume mounts: {host_path: container_path}",
    )
    domain: Optional[str] = Field(
        default=None,
        description="Domain for reverse proxy (optional)",
    )


class ComposeDeploy(BaseModel):
    compose_yaml: str = Field(..., min_length=1, description="docker-compose.yml content")
    project_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class ComposeValidate(BaseModel):
    compose_yaml: str = Field(..., min_length=1, description="docker-compose.yml content to validate")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ContainerResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    container_id: str
    name: str
    image: str
    ports_json: Optional[str] = None
    env_json: Optional[str] = None
    volumes_json: Optional[str] = None
    status: str
    domain: Optional[str] = None
    ssl_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContainerStatsResponse(BaseModel):
    container_id: str
    cpu_percent: Optional[str] = None
    memory_usage: Optional[str] = None
    memory_limit: Optional[str] = None
    memory_percent: Optional[str] = None
    network_io: Optional[str] = None
    block_io: Optional[str] = None


class ContainerLogsResponse(BaseModel):
    container_id: str
    logs: str


class ContainerActionResponse(BaseModel):
    container_id: str
    action: str
    success: bool


class ComposeValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
