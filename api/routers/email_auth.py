"""Email authentication router -- /api/v1/email/auth.

Manages DKIM, SPF, and DMARC configuration for domains.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.core.security import get_current_user
from api.models.users import User
from api.schemas.email_auth import (
    DKIMSetupResponse,
    EmailAuthStatus,
    EmailDNSRecords,
    EmailVerifyResponse,
)

router = APIRouter()


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# --------------------------------------------------------------------------
# GET /{domain}/status -- SPF/DKIM/DMARC status
# --------------------------------------------------------------------------


@router.get("/{domain}/status", response_model=EmailAuthStatus)
async def email_auth_status(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.get(f"/mail/auth/status/{domain}")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to check status"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# POST /{domain}/setup-dkim -- generate DKIM keys
# --------------------------------------------------------------------------


@router.post("/{domain}/setup-dkim", response_model=DKIMSetupResponse)
async def setup_dkim(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.post("/mail/auth/dkim/setup", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "DKIM setup failed"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /{domain}/dns-records -- required DNS records for email auth
# --------------------------------------------------------------------------


@router.get("/{domain}/dns-records", response_model=EmailDNSRecords)
async def email_dns_records(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.get(f"/mail/auth/dns-records/{domain}")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to get DNS records"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# POST /{domain}/verify -- check all email auth records
# --------------------------------------------------------------------------


@router.post("/{domain}/verify", response_model=EmailVerifyResponse)
async def verify_email_auth(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.post("/mail/auth/verify", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Verification failed"))
    return resp.get("data", resp)
