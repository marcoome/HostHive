"""Domain schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DomainCreate(BaseModel):
    domain_name: str = Field(..., min_length=3, max_length=255)
    document_root: Optional[str] = None
    php_version: str = Field(default="8.2", pattern=r"^\d+\.\d+$")


class DomainUpdate(BaseModel):
    document_root: Optional[str] = None
    php_version: Optional[str] = Field(default=None, pattern=r"^\d+\.\d+$")
    ssl_enabled: Optional[bool] = None
    nginx_template: Optional[str] = None
    is_active: Optional[bool] = None


class DomainResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_name: str
    document_root: str
    php_version: str
    ssl_enabled: bool
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
