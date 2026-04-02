"""Analytics router -- /api/v1/analytics

GoAccess-powered visitor analytics: reports, stats, real-time visitors,
top pages, top countries.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.core.security import get_current_user, require_role
from api.models.users import User
from api.schemas.analytics import (
    RealtimeVisitorsResponse,
    ReportGenerate,
    ReportResponse,
    TopCountriesResponse,
    TopPagesResponse,
    VisitorStatsResponse,
)

router = APIRouter()

_admin_or_reseller = require_role("admin", "reseller")


def _get_agent(request: Request):
    return request.app.state.agent


# ---------------------------------------------------------------------------
# GET /{domain}/report -- get or generate GoAccess report
# ---------------------------------------------------------------------------

@router.get("/{domain}/report", response_model=ReportResponse)
async def get_report(
    domain: str,
    period: str = Query("daily", description="Report period"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    agent = _get_agent(request)
    result = await agent.post("/analytics/report", json={
        "domain": domain,
        "period": period,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Report generation failed"))

    data = result.get("data", {})
    return ReportResponse(
        domain=data.get("domain", domain),
        period=data.get("period", period),
        report_path=data.get("report_path", ""),
        report_url=data.get("report_url", ""),
    )


# ---------------------------------------------------------------------------
# GET /{domain}/stats -- parsed visitor stats (JSON)
# ---------------------------------------------------------------------------

@router.get("/{domain}/stats", response_model=VisitorStatsResponse)
async def get_stats(
    domain: str,
    period: str = Query("7d", description="Stats period"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    agent = _get_agent(request)
    result = await agent.post("/analytics/stats", json={
        "domain": domain,
        "period": period,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Stats generation failed"))

    data = result.get("data", {})
    return VisitorStatsResponse(**data)


# ---------------------------------------------------------------------------
# GET /{domain}/visitors -- real-time visitor count
# ---------------------------------------------------------------------------

@router.get("/{domain}/visitors", response_model=RealtimeVisitorsResponse)
async def get_visitors(
    domain: str,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    agent = _get_agent(request)
    result = await agent.post("/analytics/visitors", json={
        "domain": domain,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to get visitors"))

    data = result.get("data", {})
    return RealtimeVisitorsResponse(**data)


# ---------------------------------------------------------------------------
# GET /{domain}/top-pages -- top pages by visits
# ---------------------------------------------------------------------------

@router.get("/{domain}/top-pages", response_model=TopPagesResponse)
async def get_top_pages(
    domain: str,
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    agent = _get_agent(request)
    result = await agent.post("/analytics/top-pages", json={
        "domain": domain,
        "limit": limit,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to get top pages"))

    data = result.get("data", {})
    return TopPagesResponse(**data)


# ---------------------------------------------------------------------------
# GET /{domain}/top-countries -- top countries
# ---------------------------------------------------------------------------

@router.get("/{domain}/top-countries", response_model=TopCountriesResponse)
async def get_top_countries(
    domain: str,
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    agent = _get_agent(request)
    result = await agent.post("/analytics/top-countries", json={
        "domain": domain,
        "limit": limit,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to get top countries"))

    data = result.get("data", {})
    return TopCountriesResponse(**data)


# ---------------------------------------------------------------------------
# POST /{domain}/generate -- force regenerate report
# ---------------------------------------------------------------------------

@router.post("/{domain}/generate", response_model=ReportResponse)
async def generate_report(
    domain: str,
    body: ReportGenerate = None,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    period = body.period if body else "daily"

    agent = _get_agent(request)
    result = await agent.post("/analytics/report", json={
        "domain": domain,
        "period": period,
    })

    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Report generation failed"))

    data = result.get("data", {})
    return ReportResponse(
        domain=data.get("domain", domain),
        period=data.get("period", period),
        report_path=data.get("report_path", ""),
        report_url=data.get("report_url", ""),
    )
