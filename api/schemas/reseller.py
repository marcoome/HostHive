"""Pydantic schemas for the reseller system module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from api.models.users import UserRole


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------

class ResellerBrandingCreate(BaseModel):
    logo_url: Optional[str] = Field(None, max_length=512)
    primary_color: str = Field("#4f46e5", pattern=r"^#[0-9a-fA-F]{6}$", max_length=7)
    panel_title: str = Field("HostHive", max_length=128)
    custom_domain: Optional[str] = Field(None, max_length=255)
    hide_hosthive_branding: bool = False
    custom_css: Optional[str] = Field(None, max_length=10000)


class ResellerBrandingUpdate(BaseModel):
    logo_url: Optional[str] = Field(None, max_length=512)
    primary_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$", max_length=7)
    panel_title: Optional[str] = Field(None, max_length=128)
    custom_domain: Optional[str] = Field(None, max_length=255)
    hide_hosthive_branding: Optional[bool] = None
    custom_css: Optional[str] = Field(None, max_length=10000)


class ResellerBrandingResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    logo_url: Optional[str] = None
    primary_color: str
    panel_title: str
    custom_domain: Optional[str] = None
    hide_hosthive_branding: bool
    custom_css: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

class ResellerLimitResponse(BaseModel):
    id: uuid.UUID
    reseller_id: uuid.UUID
    max_users: int
    max_total_disk_mb: int
    max_total_bandwidth_gb: int
    used_users: int
    used_disk_mb: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Reseller user management
# ---------------------------------------------------------------------------

class ResellerUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    package_id: Optional[uuid.UUID] = None


class ResellerUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    package_id: Optional[uuid.UUID] = None


class ResellerUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: UserRole
    is_active: bool
    is_suspended: bool
    package_id: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResellerUserListResponse(BaseModel):
    items: List[ResellerUserResponse]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

class ResellerStatsResponse(BaseModel):
    total_users: int
    active_users: int
    suspended_users: int
    total_domains: int
    total_databases: int
    total_email_accounts: int
    used_disk_mb: int
    max_disk_mb: int
    used_users: int
    max_users: int
    max_bandwidth_gb: int
