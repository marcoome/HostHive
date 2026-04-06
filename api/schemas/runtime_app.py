"""Runtime app schemas for Node.js / Python application manager."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RuntimeAppCreate(BaseModel):
    domain_id: uuid.UUID
    app_type: str = Field(..., pattern=r"^(node|python)$", description="'node' or 'python'")
    app_name: str = Field(default="", max_length=255)
    app_root: str = Field(..., min_length=1, max_length=512)
    entry_point: str = Field(default="app.js", max_length=255)
    runtime_version: str = Field(default="20", max_length=20)
    port: int = Field(..., ge=1024, le=65535)
    env_vars: Optional[dict[str, str]] = None
    startup_command: Optional[str] = None


class RuntimeAppUpdate(BaseModel):
    app_name: Optional[str] = Field(default=None, max_length=255)
    app_root: Optional[str] = Field(default=None, min_length=1, max_length=512)
    entry_point: Optional[str] = Field(default=None, max_length=255)
    runtime_version: Optional[str] = Field(default=None, max_length=20)
    port: Optional[int] = Field(default=None, ge=1024, le=65535)
    env_vars: Optional[dict[str, str]] = None
    startup_command: Optional[str] = None


class RuntimeAppResponse(BaseModel):
    id: uuid.UUID
    domain_id: uuid.UUID
    user_id: uuid.UUID
    app_type: str
    app_name: str
    app_root: str
    entry_point: str
    runtime_version: str
    port: int
    env_vars: Optional[dict[str, str]] = None
    startup_command: Optional[str] = None
    is_running: bool
    pid: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Populated by the router from the domain join
    domain_name: Optional[str] = None

    model_config = {"from_attributes": True}


class RuntimeVersionsResponse(BaseModel):
    node: list[str]
    python: list[str]
