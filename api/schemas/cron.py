"""Cron job schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CronJobCreate(BaseModel):
    schedule: str = Field(..., min_length=9, max_length=128)  # e.g. "*/5 * * * *"
    command: str = Field(..., min_length=1, max_length=4096)


class CronJobUpdate(BaseModel):
    schedule: Optional[str] = Field(default=None, min_length=9, max_length=128)
    command: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    is_active: Optional[bool] = None


class CronJobResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    schedule: str
    command: str
    is_active: bool
    last_run: Optional[datetime] = None

    model_config = {"from_attributes": True}
