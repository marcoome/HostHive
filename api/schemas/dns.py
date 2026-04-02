"""DNS schemas."""

from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field


class DnsZoneCreate(BaseModel):
    domain_id: uuid.UUID
    zone_name: str = Field(..., min_length=1, max_length=255)


class DnsZoneResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_id: uuid.UUID
    zone_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class DnsRecordCreate(BaseModel):
    zone_id: uuid.UUID
    record_type: str = Field(..., pattern=r"^(A|AAAA|CNAME|MX|TXT|NS|SRV|CAA|PTR)$")
    name: str = Field(..., min_length=1, max_length=255)
    value: str = Field(..., min_length=1, max_length=1024)
    ttl: int = Field(default=3600, ge=60, le=604800)
    priority: Optional[int] = Field(default=None, ge=0, le=65535)


class DnsRecordResponse(BaseModel):
    id: uuid.UUID
    zone_id: uuid.UUID
    record_type: str
    name: str
    value: str
    ttl: int
    priority: Optional[int] = None

    model_config = {"from_attributes": True}


class DnsZoneDetailResponse(DnsZoneResponse):
    records: List[DnsRecordResponse] = []
