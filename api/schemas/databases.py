"""Database schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from api.models.databases import DbType


class DatabaseCreate(BaseModel):
    db_name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_]+$")
    db_user: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_]+$")
    db_password: str = Field(..., min_length=8, max_length=128)
    db_type: DbType = DbType.MYSQL


class DatabaseResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    db_name: str
    db_user: str
    db_type: DbType
    created_at: datetime

    model_config = {"from_attributes": True}
