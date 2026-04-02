"""AI module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class AiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    context: dict[str, Any] = Field(default_factory=dict)
    conversation_id: Optional[uuid.UUID] = None


class AiChatResponse(BaseModel):
    response: str
    conversation_id: uuid.UUID
    tokens_used: int


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class AiMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tokens_used: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AiConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AiConversationDetail(BaseModel):
    id: uuid.UUID
    title: str
    messages: list[AiMessageResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

class AiInsightResponse(BaseModel):
    id: uuid.UUID
    severity: str
    issue_type: str
    description: str
    recommendation: str
    auto_fix_available: bool
    auto_fix_action: Optional[str] = None
    is_resolved: bool
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class AiSettingsResponse(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    auto_fix_enabled: bool
    log_analysis_interval: str
    max_tokens_per_request: int
    is_enabled: bool
    has_api_key: bool = False  # never expose actual key


class AiSettingsUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None  # plain text — will be encrypted before storage
    base_url: Optional[str] = None
    auto_fix_enabled: Optional[bool] = None
    log_analysis_interval: Optional[str] = Field(
        default=None, pattern=r"^(1h|6h|12h|daily|disabled)$",
    )
    max_tokens_per_request: Optional[int] = Field(default=None, ge=100, le=8000)
    is_enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Nginx optimization
# ---------------------------------------------------------------------------

class AiNginxOptimizeRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)


class AiNginxOptimizeResponse(BaseModel):
    domain: str
    current_config: str
    proposed_config: str
    diff: str
    explanation: str


class AiNginxApplyRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)
    proposed_config: str


# ---------------------------------------------------------------------------
# Security scan
# ---------------------------------------------------------------------------

class AiSecurityIssue(BaseModel):
    category: str
    severity: str
    description: str
    recommendation: str


class AiSecurityScanResponse(BaseModel):
    score: int = Field(..., ge=0, le=100)
    issues: list[AiSecurityIssue]
    scan_time: datetime


# ---------------------------------------------------------------------------
# App installer
# ---------------------------------------------------------------------------

class AiAppInstallRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)
    app_name: str = Field(..., min_length=1, max_length=64)


class AiAppInstallResponse(BaseModel):
    domain: str
    app_name: str
    url: str
    credentials: dict[str, str]
    ssl_configured: bool
    cron_configured: bool


# ---------------------------------------------------------------------------
# Usage / Stats
# ---------------------------------------------------------------------------

class AiUsageResponse(BaseModel):
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    by_model: list[dict[str, Any]]
    period_days: int
