"""FTP account schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class FtpAccountCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    home_dir: str = Field(..., min_length=1, max_length=512)


class FtpAccountResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    home_dir: str
    is_active: bool

    model_config = {"from_attributes": True}
