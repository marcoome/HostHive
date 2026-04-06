"""Mailing list schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Optional

from pydantic import BaseModel, Field


class ListCreate(BaseModel):
    domain_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255, description="List name, e.g. 'announcements'")
    description: Optional[str] = Field(None, max_length=2048)
    owner_email: str = Field(..., min_length=3, max_length=255)
    is_moderated: bool = False
    archive_enabled: bool = True
    max_message_size_kb: int = Field(default=10240, ge=1, le=102400)
    reply_to_list: bool = False


class ListUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=2048)
    owner_email: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    is_moderated: Optional[bool] = None
    archive_enabled: Optional[bool] = None
    max_message_size_kb: Optional[int] = Field(None, ge=1, le=102400)
    reply_to_list: Optional[bool] = None


class MemberResponse(BaseModel):
    id: uuid.UUID
    list_id: uuid.UUID
    email: str
    name: Optional[str] = None
    is_admin: bool = False
    subscribed_at: datetime

    model_config = {"from_attributes": True}


class ListResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_id: uuid.UUID
    name: str
    list_address: str
    description: Optional[str] = None
    owner_email: str
    is_active: bool
    is_moderated: bool
    archive_enabled: bool
    max_message_size_kb: int
    reply_to_list: bool
    created_at: datetime
    member_count: int = 0
    members: list[MemberResponse] = []

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    emails: list[str] = Field(..., min_length=1, description="List of email addresses to subscribe")
    name: Optional[str] = Field(None, max_length=255, description="Display name (applied to all if bulk)")
    is_admin: bool = False


class ListSendMessage(BaseModel):
    subject: str = Field(..., min_length=1, max_length=998)
    body: str = Field(..., min_length=1)
    content_type: str = Field(default="text/plain", description="text/plain or text/html")
