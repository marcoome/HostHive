"""Git deployment schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GitDeployCreate(BaseModel):
    repo_url: str = Field(..., min_length=5, max_length=1024, description="SSH or HTTPS repository URL")
    branch: str = Field(default="main", max_length=255)
    auto_deploy: bool = Field(default=True, description="Automatically deploy on webhook push events")
    build_command: Optional[str] = Field(default=None, max_length=2048, description="Build command (e.g. npm install && npm run build)")
    post_deploy_hook: Optional[str] = Field(default=None, max_length=2048, description="Post-deploy command (e.g. php artisan cache:clear)")


class GitDeployUpdate(BaseModel):
    repo_url: Optional[str] = Field(default=None, min_length=5, max_length=1024)
    branch: Optional[str] = Field(default=None, max_length=255)
    auto_deploy: Optional[bool] = None
    build_command: Optional[str] = Field(default=None, max_length=2048)
    post_deploy_hook: Optional[str] = Field(default=None, max_length=2048)


class GitDeployResponse(BaseModel):
    id: uuid.UUID
    domain_id: uuid.UUID
    repo_url: str
    branch: str
    deploy_key_public: Optional[str] = None
    auto_deploy: bool
    build_command: Optional[str] = None
    post_deploy_hook: Optional[str] = None
    webhook_secret: Optional[str] = None
    webhook_url: Optional[str] = None
    last_deploy_at: Optional[datetime] = None
    last_deploy_status: Optional[str] = None
    last_commit_hash: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeployLogEntry(BaseModel):
    id: uuid.UUID
    deployment_id: uuid.UUID
    commit_hash: Optional[str] = None
    status: str
    trigger: str
    output: Optional[str] = None
    duration_seconds: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeployTriggerRequest(BaseModel):
    """Optional body for manual deploy trigger."""
    build_command: Optional[str] = Field(default=None, max_length=2048, description="Override build command for this deploy")
