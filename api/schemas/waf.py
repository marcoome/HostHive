"""WAF (Web Application Firewall) schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WAFStatusResponse(BaseModel):
    domain: str
    enabled: bool
    mode: str = Field(description="'detect' (log only) or 'block' (reject)")
    blocked_requests: int = 0
    enabled_at: Optional[str] = None
    disabled_at: Optional[str] = None


class WAFRuleCreate(BaseModel):
    rule: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Nginx WAF rule directive",
    )


class WAFRuleResponse(BaseModel):
    id: str
    type: str = Field(description="'default' or 'custom'")
    rule: str


class WAFRulesListResponse(BaseModel):
    domain: str
    rules: list[WAFRuleResponse] = []
    total: int = 0


class WAFModeUpdate(BaseModel):
    mode: str = Field(
        ...,
        pattern=r"^(detect|block)$",
        description="WAF mode: 'detect' or 'block'",
    )


class WAFLogEntry(BaseModel):
    raw: str


class WAFLogResponse(BaseModel):
    domain: str
    entries: list[str] = []
    total: int = 0


class WAFStatsResponse(BaseModel):
    total_blocked: int = 0
    top_attack_types: list[dict[str, int]] = []
    top_ips: list[dict[str, int]] = []
    domains_with_waf: int = 0


# ---------------------------------------------------------------------------
# Geo-blocking schemas
# ---------------------------------------------------------------------------


class GeoRule(BaseModel):
    country_code: str = Field(
        ...,
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code (e.g. CN, RU, KP)",
    )
    action: str = Field(
        ...,
        pattern=r"^(block|allow)$",
        description="Action to take: 'block' or 'allow'",
    )


class GeoRuleResponse(BaseModel):
    country_code: str
    action: str


class GeoRulesListResponse(BaseModel):
    mode: str = Field(description="'blacklist' or 'whitelist'")
    rules: list[GeoRuleResponse] = []
    total: int = 0


class GeoStatus(BaseModel):
    installed: bool = Field(description="Whether libnginx-mod-http-geoip2 is installed")
    db_exists: bool = Field(description="Whether the GeoLite2-Country.mmdb file exists")
    db_path: str = "/usr/share/GeoIP/GeoLite2-Country.mmdb"
    db_last_modified: Optional[str] = Field(
        None, description="Last modification time of the database file"
    )
    geoipupdate_installed: bool = Field(
        description="Whether geoipupdate binary is available"
    )
    enabled: bool = Field(description="Whether geo-blocking is currently active")


class GeoModeUpdate(BaseModel):
    mode: str = Field(
        ...,
        pattern=r"^(blacklist|whitelist)$",
        description="Geo-blocking mode: 'blacklist' (listed countries blocked) "
        "or 'whitelist' (only listed countries allowed)",
    )
