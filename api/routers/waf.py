"""WAF (Web Application Firewall) router -- /api/v1/waf."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.users import User
from api.schemas.waf import (
    WAFLogResponse,
    WAFModeUpdate,
    WAFRuleCreate,
    WAFRulesListResponse,
    WAFStatsResponse,
    WAFStatusResponse,
)

router = APIRouter()


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# --------------------------------------------------------------------------
# GET /status -- WAF status for all domains
# --------------------------------------------------------------------------


@router.get("/status", response_model=list[WAFStatusResponse])
async def waf_status_all(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get("/waf/status")
    return resp.get("data", [])


# --------------------------------------------------------------------------
# POST /{domain}/enable -- enable WAF
# --------------------------------------------------------------------------


@router.post("/{domain}/enable", response_model=WAFStatusResponse)
async def waf_enable(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.post("/waf/enable", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "WAF enable failed"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# POST /{domain}/disable -- disable WAF
# --------------------------------------------------------------------------


@router.post("/{domain}/disable", response_model=WAFStatusResponse)
async def waf_disable(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.post("/waf/disable", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "WAF disable failed"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /{domain}/rules -- list rules
# --------------------------------------------------------------------------


@router.get("/{domain}/rules", response_model=WAFRulesListResponse)
async def waf_list_rules(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/waf/rules/{domain}")
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# POST /{domain}/rules -- add custom rule
# --------------------------------------------------------------------------


@router.post("/{domain}/rules")
async def waf_add_rule(
    domain: str,
    body: WAFRuleCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.post(f"/waf/rules/{domain}", json={"domain": domain, "rule": body.rule})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to add rule"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# DELETE /{domain}/rules/{rule_id} -- delete rule
# --------------------------------------------------------------------------


@router.delete("/{domain}/rules/{rule_id}")
async def waf_delete_rule(
    domain: str,
    rule_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.delete(f"/waf/rules/{domain}/{rule_id}")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to delete rule"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /{domain}/log -- blocked requests log
# --------------------------------------------------------------------------


@router.get("/{domain}/log", response_model=WAFLogResponse)
async def waf_log(
    domain: str,
    lines: int = 100,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/waf/log/{domain}", params={"lines": lines})
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# PUT /{domain}/mode -- set detect/block mode
# --------------------------------------------------------------------------


@router.put("/{domain}/mode")
async def waf_set_mode(
    domain: str,
    body: WAFModeUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.put(f"/waf/mode/{domain}", json={"domain": domain, "mode": body.mode})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to set mode"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /stats -- total blocked requests, top attack types, top IPs
# --------------------------------------------------------------------------


@router.get("/stats", response_model=WAFStatsResponse)
async def waf_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get("/waf/stats")
    return resp.get("data", resp)
