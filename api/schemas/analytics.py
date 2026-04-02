"""Pydantic schemas for visitor analytics (GoAccess)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReportGenerate(BaseModel):
    """Request body for generating/regenerating a report."""
    period: str = Field(default="daily", description="Report period: daily, weekly, monthly, 7d, 30d, etc.")


class ReportResponse(BaseModel):
    """Response for a generated report."""
    domain: str
    period: str
    report_path: str
    report_url: str


class VisitorStatsResponse(BaseModel):
    """Parsed visitor statistics."""
    domain: str
    period: str
    total_requests: int = 0
    unique_visitors: int = 0
    bandwidth_bytes: int = 0
    failed_requests: int = 0
    generation_time: int = 0
    log_size: int = 0


class RealtimeVisitorsResponse(BaseModel):
    """Real-time visitor count."""
    domain: str
    active_visitors: int = 0
    hits_last_5min: int = 0


class PageEntry(BaseModel):
    path: str
    hits: int = 0
    visitors: int = 0
    bandwidth: int = 0


class TopPagesResponse(BaseModel):
    """Top pages by visits."""
    domain: str
    top_pages: List[PageEntry]
    total: int


class CountryEntry(BaseModel):
    country: str
    hits: int = 0
    visitors: int = 0


class TopCountriesResponse(BaseModel):
    """Top countries by visitors."""
    domain: str
    top_countries: List[CountryEntry]
    total: int
