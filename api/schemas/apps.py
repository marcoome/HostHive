"""App deployment schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AppDeployRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)
    runtime: str = Field(..., pattern=r"^(nodejs|python)$", description="'nodejs' or 'python'")
    path: str = Field(..., min_length=1, max_length=512)
    port: int = Field(..., ge=1024, le=65535)
    version: str = Field(default="", description="Runtime version (e.g. '20' for Node, '3.11' for Python)")


class AppStatusResponse(BaseModel):
    domain: str
    runtime: str = ""
    status: str = "unknown"
    sub_state: Optional[str] = None
    pid: int = 0
    port: Optional[int] = None
    path: Optional[str] = None
    started_at: Optional[str] = None
    memory_bytes: Optional[int] = None
    memory_mb: Optional[float] = None


class AppLogsResponse(BaseModel):
    domain: str
    logs: dict[str, str] = {}


class AppListEntry(BaseModel):
    domain: str
    runtime: str = ""
    port: Optional[int] = None
    status: str = "unknown"
    path: Optional[str] = None
    deployed_at: Optional[str] = None


class AppEnvUpdate(BaseModel):
    env_vars: dict[str, str] = Field(
        ...,
        min_length=1,
        description="Dictionary of environment variables to set",
    )


class AppStopStartResponse(BaseModel):
    domain: str
    action: str
    success: bool = True


class AppModel(BaseModel):
    """Database model schema."""
    id: uuid.UUID
    user_id: uuid.UUID
    domain: str
    runtime: str
    port: int
    path: str
    status: str = "stopped"
    version: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
