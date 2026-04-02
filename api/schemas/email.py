"""Email account schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class EmailAccountCreate(BaseModel):
    domain_id: uuid.UUID
    address: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    quota_mb: int = Field(default=1024, ge=1)


class EmailAccountResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_id: uuid.UUID
    address: str
    quota_mb: int
    is_active: bool

    model_config = {"from_attributes": True}


class AliasCreate(BaseModel):
    source: str = Field(..., min_length=3, max_length=255)
    destination: str = Field(..., min_length=3, max_length=255)
