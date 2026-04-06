"""Email account schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Optional

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
    quota_used_mb: float = 0.0
    is_active: bool
    max_emails_per_hour: int = 200
    autoresponder_enabled: bool = False

    model_config = {"from_attributes": True}


class AutoresponderUpdate(BaseModel):
    enabled: bool = True
    subject: Optional[str] = Field(None, max_length=255)
    body: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class AutoresponderResponse(BaseModel):
    enabled: bool
    subject: Optional[str] = None
    body: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PasswordChange(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class QuotaResponse(BaseModel):
    address: str
    quota_mb: int
    quota_used_mb: float
    usage_percent: float

    model_config = {"from_attributes": True}


class RateLimitUpdate(BaseModel):
    max_emails_per_hour: int = Field(..., ge=1, le=10000)


class RateLimitResponse(BaseModel):
    address: str
    max_emails_per_hour: int

    model_config = {"from_attributes": True}


class AliasCreate(BaseModel):
    source: str = Field(..., min_length=3, max_length=255)
    destination: Optional[str] = Field(None, max_length=2048, description="Single destination (legacy)")
    destinations: Optional[list[str]] = Field(None, description="List of destination addresses for multi-target forwarding")
    keep_local_copy: bool = Field(default=False, description="Keep a local copy when forwarding")

    def resolved_destinations(self) -> list[str]:
        """Return the final list of destination addresses."""
        if self.destinations:
            return [d.strip() for d in self.destinations if d.strip()]
        if self.destination:
            return [d.strip() for d in self.destination.split(",") if d.strip()]
        return []


class AliasResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    source: str
    destination: str
    destinations: list[str] = []
    keep_local_copy: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_alias(cls, alias) -> "AliasResponse":
        dest_str = alias.destination or ""
        dest_list = [d.strip() for d in dest_str.split(",") if d.strip()]
        return cls(
            id=alias.id,
            user_id=alias.user_id,
            source=alias.source,
            destination=dest_str,
            destinations=dest_list,
            keep_local_copy=getattr(alias, "keep_local_copy", False),
        )


class CatchAllSet(BaseModel):
    address: str = Field(..., min_length=3, max_length=255, description="Destination email for catch-all")


class CatchAllResponse(BaseModel):
    domain: str
    catch_all_address: str | None = None
    enabled: bool = False


# ------------------------------------------------------------------
# Sieve filter schemas
# ------------------------------------------------------------------

class SieveFilterRule(BaseModel):
    """A single Sieve filter rule for the visual rule builder."""
    field: str = Field(..., description="Header field: from, to, subject, cc")
    match_type: str = Field(default="contains", description="contains, matches, is, regex")
    value: str = Field(..., description="Value to match against")
    action: str = Field(..., description="Action: fileinto, redirect, discard, addflag")
    action_value: Optional[str] = Field(None, description="Action argument, e.g. folder name or forward address")


class SieveFilterGet(BaseModel):
    """Response for reading the current Sieve filter script."""
    script: str = ""
    rules: list[SieveFilterRule] = []
    active: bool = False


class SieveFilterPut(BaseModel):
    """Request body for saving a Sieve script."""
    script: Optional[str] = Field(None, description="Raw Sieve script (used in advanced mode)")
    rules: Optional[list[SieveFilterRule]] = Field(None, description="Visual rules to compile into Sieve")


class SieveTestRequest(BaseModel):
    """Request body for testing / validating a Sieve script."""
    script: str = Field(..., description="Raw Sieve script to validate")


class SieveTestResponse(BaseModel):
    valid: bool
    errors: Optional[str] = None


# ------------------------------------------------------------------
# Spam filter schemas
# ------------------------------------------------------------------

class SpamFilterUpdate(BaseModel):
    """Request body for updating per-user spam filter settings."""
    enabled: bool = True
    threshold: float = Field(default=5.0, ge=1.0, le=10.0, description="SpamAssassin score threshold (1=aggressive, 10=permissive)")
    action: str = Field(default="move", description="Action on spam: move, delete, or tag_only")
    whitelist: Optional[str] = Field(None, description="Newline-separated addresses that bypass spam filter")
    blacklist: Optional[str] = Field(None, description="Newline-separated addresses always marked as spam")


class SpamFilterResponse(BaseModel):
    """Response for spam filter settings."""
    enabled: bool = True
    threshold: float = 5.0
    action: str = "move"
    whitelist: Optional[str] = None
    blacklist: Optional[str] = None

    model_config = {"from_attributes": True}
