"""Redirect schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RedirectCreate(BaseModel):
    source_path: str = Field(..., min_length=1, max_length=2048)
    destination_url: str = Field(..., min_length=1, max_length=2048)
    redirect_type: int = Field(default=301, description="HTTP redirect code: 301, 302, or 307")
    is_regex: bool = False
    is_active: bool = True


class RedirectUpdate(BaseModel):
    source_path: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    destination_url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    redirect_type: Optional[int] = Field(default=None, description="HTTP redirect code: 301, 302, or 307")
    is_regex: Optional[bool] = None
    is_active: Optional[bool] = None


class RedirectResponse(BaseModel):
    id: uuid.UUID
    domain_id: uuid.UUID
    source_path: str
    destination_url: str
    redirect_type: int
    is_regex: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
