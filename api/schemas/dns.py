"""DNS schemas."""

from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class DnsZoneCreate(BaseModel):
    domain_id: Optional[uuid.UUID] = None
    zone_name: str = Field(default="", min_length=0, max_length=255)

    @model_validator(mode="before")
    @classmethod
    def accept_frontend_field_names(cls, data):
        """Accept ``name`` as alias for ``zone_name`` and ``domain`` as alias
        for ``domain_id``.  The frontend sends ``{name, primary_ip}``."""
        if isinstance(data, dict):
            if "name" in data and "zone_name" not in data:
                data["zone_name"] = data.pop("name")
            if "domain" in data and "domain_id" not in data:
                data["domain_id"] = data.pop("domain")
        return data


class DnsZoneResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_id: Optional[uuid.UUID] = None
    zone_name: str
    is_active: bool
    cloudflare_enabled: bool = False
    dnssec_enabled: bool = False

    model_config = {"from_attributes": True}


class DnsRecordCreate(BaseModel):
    zone_id: Optional[uuid.UUID] = None  # Optional: comes from URL path parameter
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


class DnsRecordUpdate(BaseModel):
    record_type: Optional[str] = Field(default=None, pattern=r"^(A|AAAA|CNAME|MX|TXT|NS|SRV|CAA|PTR)$")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    value: Optional[str] = Field(default=None, min_length=1, max_length=1024)
    ttl: Optional[int] = Field(default=None, ge=60, le=604800)
    priority: Optional[int] = Field(default=None, ge=0, le=65535)


class DnsZoneDetailResponse(DnsZoneResponse):
    records: List[DnsRecordResponse] = []
    cloudflare_enabled: bool = False
    dnssec_enabled: bool = False
    dnssec_algorithm: str = "ECDSAP256SHA256"
    ds_record: Optional[str] = None


# ---------------------------------------------------------------------------
# Cloudflare integration schemas
# ---------------------------------------------------------------------------

class CloudflareEnableRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    cf_zone_id: str = Field(..., min_length=1)


class CloudflareStatusResponse(BaseModel):
    enabled: bool
    cf_zone_id: Optional[str] = None
    email: Optional[str] = None


class CloudflareProxyToggle(BaseModel):
    proxied: bool = True


# ---------------------------------------------------------------------------
# DNSSEC schemas
# ---------------------------------------------------------------------------

class DnssecEnableRequest(BaseModel):
    algorithm: str = Field(
        default="ECDSAP256SHA256",
        pattern=r"^(ECDSAP256SHA256|ECDSAP384SHA384|RSASHA256|RSASHA512)$",
        description="DNSSEC signing algorithm",
    )


class DnssecStatusResponse(BaseModel):
    enabled: bool = False
    algorithm: Optional[str] = None
    ds_record: Optional[str] = None


# ---------------------------------------------------------------------------
# DNS Cluster schemas
# ---------------------------------------------------------------------------

class DnsClusterNodeCreate(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=1, max_length=45)
    port: int = Field(default=53, ge=1, le=65535)
    api_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(..., min_length=1)
    role: str = Field(default="slave", pattern=r"^(master|slave)$")


class DnsClusterNodeResponse(BaseModel):
    id: uuid.UUID
    hostname: str
    ip_address: str
    port: int
    api_url: str
    role: str
    is_active: bool
    last_sync_at: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class DnsClusterStatusResponse(BaseModel):
    nodes: List[DnsClusterNodeResponse] = []
    total_zones: int = 0
    last_full_sync: Optional[str] = None
