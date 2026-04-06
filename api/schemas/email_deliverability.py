"""Email deliverability test schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    """Status of a single deliverability check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class DeliverabilityCheck(BaseModel):
    """Result of one deliverability check."""

    name: str = Field(description="Human-readable check name")
    status: CheckStatus
    details: str = Field(default="", description="Technical details of the result")
    recommendation: str = Field(default="", description="Fix recommendation when status is not pass")


class DeliverabilityTestRequest(BaseModel):
    """Request body for running a deliverability test."""

    domain: str = Field(..., min_length=1, max_length=255)


class DeliverabilityReport(BaseModel):
    """Full deliverability report for a domain."""

    domain: str
    score: int = Field(ge=0, le=100, description="Overall deliverability score 0-100")
    checks: list[DeliverabilityCheck] = []
    tested_at: datetime
    expected_records: Optional[dict[str, str]] = Field(
        default=None,
        description="Expected DNS records (SPF, DKIM, DMARC) for the domain",
    )
