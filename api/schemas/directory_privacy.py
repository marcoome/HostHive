"""Directory privacy schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DirectoryPrivacyCreate(BaseModel):
    path: str = Field(..., min_length=1, max_length=512, description="Path to protect, e.g. /admin")
    auth_name: str = Field(default="Restricted Area", max_length=255, description="Authentication realm name")


class DirectoryPrivacyUpdate(BaseModel):
    auth_name: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None


class DirectoryPrivacyUserInfo(BaseModel):
    username: str


class DirectoryPrivacyResponse(BaseModel):
    id: uuid.UUID
    domain_id: uuid.UUID
    path: str
    auth_name: str
    users: list[DirectoryPrivacyUserInfo] = []
    user_count: int = 0
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DirectoryUserAdd(BaseModel):
    username: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.\-]+$")
    password: str = Field(..., min_length=1, max_length=255)
