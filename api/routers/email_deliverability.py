"""Email deliverability router -- /api/v1/email/deliverability.

Runs comprehensive deliverability tests and returns cached reports.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.core.security import get_current_user
from api.models.users import User
from api.schemas.email_deliverability import (
    DeliverabilityReport,
    DeliverabilityTestRequest,
)
from api.services.email_deliverability import run_deliverability_test

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# --------------------------------------------------------------------------
# POST /test -- run a comprehensive deliverability test
# --------------------------------------------------------------------------


@router.post("/test", response_model=DeliverabilityReport)
async def deliverability_test(
    body: DeliverabilityTestRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Run a comprehensive email deliverability test for a domain.

    Checks SPF, DKIM, DMARC, MX, PTR, blacklists, TLS, and HELO.
    Results are cached in Redis for 1 hour.
    """
    redis = getattr(request.app.state, "redis", None)

    try:
        report = await run_deliverability_test(body.domain, redis=redis)
    except Exception as exc:
        logger.error("Deliverability test failed for %s: %s", body.domain, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deliverability test failed: {exc}",
        )

    return report


# --------------------------------------------------------------------------
# GET /report/{domain} -- get latest cached report
# --------------------------------------------------------------------------


@router.get("/report/{domain}", response_model=DeliverabilityReport)
async def deliverability_report(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Get the latest deliverability test report for a domain.

    Returns the cached report if available, otherwise runs a fresh test.
    """
    redis = getattr(request.app.state, "redis", None)

    try:
        report = await run_deliverability_test(domain, redis=redis)
    except Exception as exc:
        logger.error("Deliverability report failed for %s: %s", domain, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve deliverability report: {exc}",
        )

    return report
