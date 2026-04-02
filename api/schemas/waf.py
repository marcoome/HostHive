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
