"""AI router -- /api/v1/ai."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.ai_client import AIClient, SUPPORTED_MODELS, get_ai_client_from_settings
from api.core.config import settings
from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from pydantic import BaseModel, Field
from api.core.security import get_current_user, require_role
from api.models.activity_log import ActivityLog
from api.models.ai import (
    AiConversation,
    AiInsight,
    AiInsightSeverity,
    AiMessage,
    AiMessageRole,
    AiSettings,
    AiTokenUsage,
)
from api.models.users import User
from api.schemas.ai import (
    AiAppInstallRequest,
    AiAppInstallResponse,
    AiChatRequest,
    AiChatResponse,
    AiConversationDetail,
    AiConversationSummary,
    AiInsightResponse,
    AiNginxApplyRequest,
    AiNginxOptimizeRequest,
    AiNginxOptimizeResponse,
    AiSecurityScanResponse,
    AiSettingsResponse,
    AiSettingsUpdate,
    AiUsageResponse,
)

logger = logging.getLogger("hosthive.ai.router")

router = APIRouter()

_admin = require_role("admin")

_RATE_LIMIT_PREFIX = "hosthive:ai:ratelimit:"
_RATE_LIMIT_MAX = 20  # requests per minute
_RATE_LIMIT_WINDOW = 60  # seconds


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _check_ai_rate_limit(request: Request, user_id: uuid.UUID) -> None:
    """Enforce 20 requests/minute per user for AI endpoints."""
    redis = request.app.state.redis
    key = f"{_RATE_LIMIT_PREFIX}{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _RATE_LIMIT_WINDOW)
    if count > _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI rate limit exceeded. Max 20 requests per minute.",
        )


async def _get_ai_client(db: AsyncSession) -> AIClient:
    """Get configured AI client or raise 503."""
    client = await get_ai_client_from_settings(db)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI features are not enabled. Configure AI settings first.",
        )
    return client


def _build_system_prompt(context: dict[str, Any]) -> str:
    """Build a system prompt with server context. NEVER includes secrets."""
    parts = [
        "You are HostHive AI, an intelligent assistant for the HostHive hosting control panel.",
        "You help users manage their web hosting, domains, databases, email, SSL, and server configuration.",
        "Provide clear, actionable guidance. If you suggest commands, explain what they do.",
        "NEVER output passwords, API keys, private keys, or certificates.",
    ]

    if context.get("current_page"):
        parts.append(f"\nUser is currently viewing: {context['current_page']}")
    if context.get("domains"):
        parts.append(f"\nUser's domains: {', '.join(context['domains'][:20])}")
    if context.get("recent_errors"):
        parts.append(f"\nRecent server errors: {context['recent_errors'][:500]}")
    if context.get("server_stats"):
        stats = context["server_stats"]
        parts.append(
            f"\nServer stats — CPU: {stats.get('cpu', 'N/A')}%, "
            f"RAM: {stats.get('ram', 'N/A')}%, "
            f"Disk: {stats.get('disk', 'N/A')}%"
        )

    return "\n".join(parts)


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id, action=action, details=details, ip_address=client_ip,
    ))


# --------------------------------------------------------------------------
# POST /chat — AI chat with SSE streaming support
# --------------------------------------------------------------------------
@router.post("/chat", status_code=status.HTTP_200_OK)
async def ai_chat(
    body: AiChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _check_ai_rate_limit(request, current_user.id)
    ai_client = await _get_ai_client(db)

    # Get or create conversation
    conversation: AiConversation | None = None
    if body.conversation_id:
        result = await db.execute(
            select(AiConversation).where(
                AiConversation.id == body.conversation_id,
                AiConversation.user_id == current_user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found.",
            )
    else:
        # Create new conversation with title from first message
        title = body.message[:80] + ("..." if len(body.message) > 80 else "")
        conversation = AiConversation(
            user_id=current_user.id,
            title=title,
        )
        db.add(conversation)
        await db.flush()

    # Build messages history from conversation
    history: list[dict[str, str]] = []
    if conversation.messages:
        for msg in conversation.messages[-20:]:  # Last 20 messages for context
            history.append({"role": msg.role.value, "content": msg.content})

    # Add current user message
    history.append({"role": "user", "content": body.message})

    # Store user message
    user_msg = AiMessage(
        conversation_id=conversation.id,
        role=AiMessageRole.USER,
        content=body.message,
        tokens_used=AIClient.count_tokens(body.message),
    )
    db.add(user_msg)
    await db.flush()

    # Build system prompt
    system_prompt = _build_system_prompt(body.context)

    # Check if streaming requested (via Accept header)
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return _stream_response(
            ai_client, history, system_prompt, conversation, current_user, db, request,
        )

    # Non-streaming response
    try:
        ai_settings_row = (await db.execute(select(AiSettings).limit(1))).scalar_one_or_none()
        max_tokens = ai_settings_row.max_tokens_per_request if ai_settings_row else 2000

        response_text = await ai_client.chat(
            history, system_prompt, max_tokens=max_tokens,
        )
        assert isinstance(response_text, str)
    except Exception as exc:
        logger.error("AI chat failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {exc}",
        )

    tokens_used = AIClient.count_tokens(response_text)

    # Store assistant message
    assistant_msg = AiMessage(
        conversation_id=conversation.id,
        role=AiMessageRole.ASSISTANT,
        content=response_text,
        tokens_used=tokens_used,
    )
    db.add(assistant_msg)

    # Track token usage
    usage = AiTokenUsage(
        user_id=current_user.id,
        provider=ai_client.provider,
        model=ai_client.model,
        tokens_in=AIClient.count_tokens(body.message),
        tokens_out=tokens_used,
        cost_usd=ai_client.estimate_cost(
            AIClient.count_tokens(body.message), tokens_used,
        ),
    )
    db.add(usage)

    _log(db, request, current_user.id, "ai.chat", f"AI chat in conversation {conversation.id}")

    await db.commit()

    return AiChatResponse(
        response=response_text,
        conversation_id=conversation.id,
        tokens_used=tokens_used,
    )


def _stream_response(
    ai_client: AIClient,
    history: list[dict[str, str]],
    system_prompt: str,
    conversation: AiConversation,
    current_user: User,
    db: AsyncSession,
    request: Request,
):
    """Return a Server-Sent Events streaming response."""

    async def event_generator():
        full_response = ""
        try:
            stream = await ai_client.chat(history, system_prompt, stream=True)
            async for chunk in stream:
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"

            # Save assistant message and track usage after streaming completes
            tokens_used = AIClient.count_tokens(full_response)
            assistant_msg = AiMessage(
                conversation_id=conversation.id,
                role=AiMessageRole.ASSISTANT,
                content=full_response,
                tokens_used=tokens_used,
            )
            db.add(assistant_msg)

            usage = AiTokenUsage(
                user_id=current_user.id,
                provider=ai_client.provider,
                model=ai_client.model,
                tokens_in=AIClient.count_tokens(history[-1]["content"]) if history else 0,
                tokens_out=tokens_used,
                cost_usd=ai_client.estimate_cost(
                    AIClient.count_tokens(history[-1]["content"]) if history else 0,
                    tokens_used,
                ),
            )
            db.add(usage)

            _log(db, request, current_user.id, "ai.chat.stream", f"AI streamed chat in conversation {conversation.id}")
            await db.commit()

            yield f"data: {json.dumps({'done': True, 'conversation_id': str(conversation.id)})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------
# GET /conversations — list user's conversations
# --------------------------------------------------------------------------
@router.get("/conversations", status_code=status.HTTP_200_OK)
async def list_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(AiConversation)
        .where(AiConversation.user_id == current_user.id)
        .order_by(AiConversation.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    count_query = (
        select(func.count())
        .select_from(AiConversation)
        .where(AiConversation.user_id == current_user.id)
    )
    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query)).scalars().all()

    return {
        "items": [AiConversationSummary.model_validate(c) for c in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# GET /conversations/{id} — get conversation with messages
# --------------------------------------------------------------------------
@router.get("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AiConversation).where(
            AiConversation.id == conversation_id,
            AiConversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    return AiConversationDetail.model_validate(conversation)


# --------------------------------------------------------------------------
# DELETE /conversations/{id} — delete conversation
# --------------------------------------------------------------------------
@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AiConversation).where(
            AiConversation.id == conversation_id,
            AiConversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    _log(db, request, current_user.id, "ai.delete_conversation", f"Deleted conversation {conversation_id}")
    await db.delete(conversation)
    await db.flush()
    await db.commit()


# --------------------------------------------------------------------------
# GET /insights — list AI insights
# --------------------------------------------------------------------------
@router.get("/insights", status_code=status.HTTP_200_OK)
async def list_insights(
    severity: Optional[str] = Query(None, pattern="^(high|medium|low)$"),
    resolved: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(AiInsight)
    count_query = select(func.count()).select_from(AiInsight)

    if severity:
        query = query.where(AiInsight.severity == AiInsightSeverity(severity))
        count_query = count_query.where(AiInsight.severity == AiInsightSeverity(severity))
    if resolved is not None:
        query = query.where(AiInsight.is_resolved == resolved)
        count_query = count_query.where(AiInsight.is_resolved == resolved)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(
            query.order_by(AiInsight.created_at.desc()).offset(skip).limit(limit)
        )
    ).scalars().all()

    return {
        "items": [AiInsightResponse.model_validate(i) for i in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST /insights/{id}/resolve — mark insight as resolved
# --------------------------------------------------------------------------
@router.post("/insights/{insight_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_insight(
    insight_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(AiInsight).where(AiInsight.id == insight_id))
    insight = result.scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found.")

    insight.is_resolved = True
    insight.resolved_at = datetime.now(timezone.utc)
    db.add(insight)

    _log(db, request, current_user.id, "ai.resolve_insight", f"Resolved insight {insight_id}")
    return AiInsightResponse.model_validate(insight)


# --------------------------------------------------------------------------
# POST /insights/{id}/autofix — execute auto-fix
# --------------------------------------------------------------------------
@router.post("/insights/{insight_id}/autofix", status_code=status.HTTP_200_OK)
async def autofix_insight(
    insight_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    result = await db.execute(select(AiInsight).where(AiInsight.id == insight_id))
    insight = result.scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found.")

    if not insight.auto_fix_available or not insight.auto_fix_action:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No auto-fix available for this insight.",
        )

    agent = request.app.state.agent
    try:
        await agent._request("POST", "/exec", json_body={"command": insight.auto_fix_action})
        insight.is_resolved = True
        insight.resolved_at = datetime.now(timezone.utc)
        db.add(insight)
        _log(
            db, request, current_user.id, "ai.autofix",
            f"Auto-fixed insight {insight_id}: {insight.issue_type}",
        )
        return {"status": "fixed", "insight": AiInsightResponse.model_validate(insight)}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Auto-fix failed: {exc}",
        )


# --------------------------------------------------------------------------
# POST /nginx/optimize — analyze and optimize nginx config
# --------------------------------------------------------------------------
@router.post("/nginx/optimize", status_code=status.HTTP_200_OK)
async def nginx_optimize(
    body: AiNginxOptimizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _check_ai_rate_limit(request, current_user.id)
    ai_client = await _get_ai_client(db)

    from api.services.ai_nginx import optimize_nginx

    try:
        result = await optimize_nginx(
            domain=body.domain,
            agent_client=request.app.state.agent,
            ai_client=ai_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Nginx optimization failed: {exc}",
        )

    _log(
        db, request, current_user.id, "ai.nginx_optimize",
        f"Generated nginx optimization for {body.domain}",
    )

    return AiNginxOptimizeResponse(
        domain=body.domain,
        current_config=result["current_config"],
        proposed_config=result["proposed_config"],
        diff=result["diff"],
        explanation=result["explanation"],
    )


# --------------------------------------------------------------------------
# POST /nginx/apply — apply the optimization
# --------------------------------------------------------------------------
@router.post("/nginx/apply", status_code=status.HTTP_200_OK)
async def nginx_apply(
    body: AiNginxApplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    from api.services.ai_nginx import apply_nginx_config

    try:
        result = await apply_nginx_config(
            domain=body.domain,
            proposed_config=body.proposed_config,
            agent_client=request.app.state.agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _log(
        db, request, current_user.id, "ai.nginx_apply",
        f"Applied nginx optimization for {body.domain}",
    )
    return result


# --------------------------------------------------------------------------
# POST /security/scan — run security scan
# --------------------------------------------------------------------------
@router.post("/security/scan", status_code=status.HTTP_200_OK)
async def security_scan(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    await _check_ai_rate_limit(request, current_user.id)
    ai_client = await _get_ai_client(db)

    from api.services.ai_security import run_security_scan

    try:
        result = await run_security_scan(
            agent_client=request.app.state.agent,
            ai_client=ai_client,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Security scan failed: {exc}",
        )

    _log(db, request, current_user.id, "ai.security_scan", f"Security scan score: {result.get('score')}")

    return AiSecurityScanResponse(
        score=result["score"],
        issues=[
            {
                "category": i.get("category", "unknown"),
                "severity": i.get("severity", "low"),
                "description": i.get("description", ""),
                "recommendation": i.get("recommendation", ""),
            }
            for i in result.get("issues", [])
        ],
        scan_time=result.get("scan_time", datetime.now(timezone.utc).isoformat()),
    )


# --------------------------------------------------------------------------
# POST /install-app — one-click app installer
# --------------------------------------------------------------------------
@router.post("/install-app", status_code=status.HTTP_201_CREATED)
async def install_app_endpoint(
    body: AiAppInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _check_ai_rate_limit(request, current_user.id)

    from api.services.ai_installer import install_app

    try:
        result = await install_app(
            domain=body.domain,
            app_name=body.app_name,
            agent_client=request.app.state.agent,
            user=current_user.username,
            email=current_user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"App installation failed: {exc}",
        )

    _log(
        db, request, current_user.id, "ai.install_app",
        f"Installed {body.app_name} on {body.domain}",
    )

    return AiAppInstallResponse(
        domain=result["domain"],
        app_name=result["app_name"],
        url=result["url"],
        credentials=result["credentials"],
        ssl_configured=result["ssl_configured"],
        cron_configured=result["cron_configured"],
    )


# --------------------------------------------------------------------------
# GET /settings — get AI settings (admin only)
# --------------------------------------------------------------------------
@router.get("/settings", status_code=status.HTTP_200_OK)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(AiSettings).limit(1))
    ai_settings = result.scalar_one_or_none()

    if ai_settings is None:
        return AiSettingsResponse(
            provider="openai",
            model="gpt-4o",
            auto_fix_enabled=False,
            log_analysis_interval="6h",
            max_tokens_per_request=2000,
            is_enabled=False,
            has_api_key=False,
        )

    return AiSettingsResponse(
        provider=ai_settings.provider,
        model=ai_settings.model,
        base_url=ai_settings.base_url,
        auto_fix_enabled=ai_settings.auto_fix_enabled,
        log_analysis_interval=ai_settings.log_analysis_interval,
        max_tokens_per_request=ai_settings.max_tokens_per_request,
        is_enabled=ai_settings.is_enabled,
        has_api_key=bool(ai_settings.api_key_encrypted),
    )


# --------------------------------------------------------------------------
# PUT /settings — update AI settings (admin only)
# --------------------------------------------------------------------------
@router.put("/settings", status_code=status.HTTP_200_OK)
async def update_settings(
    body: AiSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(AiSettings).limit(1))
    ai_settings = result.scalar_one_or_none()

    if ai_settings is None:
        ai_settings = AiSettings()
        db.add(ai_settings)
        await db.flush()

    update_data = body.model_dump(exclude_unset=True)

    # Validate provider/model combo
    if "provider" in update_data or "model" in update_data:
        provider = update_data.get("provider", ai_settings.provider)
        model = update_data.get("model", ai_settings.model)
        if provider in SUPPORTED_MODELS and model not in SUPPORTED_MODELS[provider]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model}' not supported for provider '{provider}'. "
                       f"Supported: {SUPPORTED_MODELS[provider]}",
            )

    # Encrypt API key if provided
    if "api_key" in update_data:
        api_key = update_data.pop("api_key")
        if api_key:
            ai_settings.api_key_encrypted = encrypt_value(api_key, settings.SECRET_KEY)
        else:
            ai_settings.api_key_encrypted = None

    for field, value in update_data.items():
        if hasattr(ai_settings, field):
            setattr(ai_settings, field, value)

    db.add(ai_settings)

    _log(db, request, current_user.id, "ai.update_settings", "Updated AI settings")

    return AiSettingsResponse(
        provider=ai_settings.provider,
        model=ai_settings.model,
        base_url=ai_settings.base_url,
        auto_fix_enabled=ai_settings.auto_fix_enabled,
        log_analysis_interval=ai_settings.log_analysis_interval,
        max_tokens_per_request=ai_settings.max_tokens_per_request,
        is_enabled=ai_settings.is_enabled,
        has_api_key=bool(ai_settings.api_key_encrypted),
    )


# --------------------------------------------------------------------------
# GET /usage — token usage stats (admin only)
# --------------------------------------------------------------------------
@router.get("/usage", status_code=status.HTTP_200_OK)
async def get_usage(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    try:
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Totals
        totals = await db.execute(
            select(
                func.coalesce(func.sum(AiTokenUsage.tokens_in), 0),
                func.coalesce(func.sum(AiTokenUsage.tokens_out), 0),
                func.coalesce(func.sum(AiTokenUsage.cost_usd), 0.0),
            ).where(AiTokenUsage.created_at >= cutoff)
        )
        row = totals.one()

        # By model breakdown
        by_model_rows = await db.execute(
            select(
                AiTokenUsage.provider,
                AiTokenUsage.model,
                func.sum(AiTokenUsage.tokens_in).label("tokens_in"),
                func.sum(AiTokenUsage.tokens_out).label("tokens_out"),
                func.sum(AiTokenUsage.cost_usd).label("cost_usd"),
                func.count().label("requests"),
            )
            .where(AiTokenUsage.created_at >= cutoff)
            .group_by(AiTokenUsage.provider, AiTokenUsage.model)
        )

        by_model = [
            {
                "provider": r.provider,
                "model": r.model,
                "tokens_in": int(r.tokens_in or 0),
                "tokens_out": int(r.tokens_out or 0),
                "cost_usd": float(r.cost_usd or 0.0),
                "requests": int(r.requests or 0),
            }
            for r in by_model_rows.all()
        ]

        return AiUsageResponse(
            total_tokens_in=int(row[0]),
            total_tokens_out=int(row[1]),
            total_cost_usd=float(row[2]),
            by_model=by_model,
            period_days=days,
        )
    except Exception:
        return AiUsageResponse(
            total_tokens_in=0,
            total_tokens_out=0,
            total_cost_usd=0.0,
            by_model=[],
            period_days=days,
        )


# --------------------------------------------------------------------------
# POST /config -- save AI provider config to Redis
# --------------------------------------------------------------------------

class AiConfigRequest(BaseModel):
    provider: str = Field(..., pattern="^(openrouter|openai|anthropic)$")
    api_key: str = Field(..., min_length=1)
    default_model: Optional[str] = None


@router.post("/config", status_code=status.HTTP_200_OK)
async def save_ai_config(body: AiConfigRequest, request: Request, admin: User = Depends(_admin)):
    redis = request.app.state.redis
    await redis.hset("hosthive:ai:config", mapping={
        "provider": body.provider,
        "api_key": body.api_key,
        "default_model": body.default_model or "",
    })
    return {"detail": "AI configuration saved.", "provider": body.provider}


# --------------------------------------------------------------------------
# GET /models -- fetch available models for current provider
# --------------------------------------------------------------------------
@router.get("/models", status_code=status.HTTP_200_OK)
async def list_ai_models(request: Request, admin: User = Depends(_admin)):
    redis = request.app.state.redis
    config = await redis.hgetall("hosthive:ai:config")
    if not config or not config.get("api_key"):
        return {"models": [], "detail": "No AI provider configured."}

    provider = config.get("provider", "openai")
    models = []

    if provider == "openai":
        models = [
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
            {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
        ]
    elif provider == "anthropic":
        models = [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
            {"id": "claude-opus-4-20250514", "name": "Claude Opus 4"},
        ]
    elif provider == "openrouter":
        models = [
            {"id": "openai/gpt-4o", "name": "GPT-4o (OpenRouter)"},
            {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4 (OpenRouter)"},
            {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro (OpenRouter)"},
            {"id": "meta-llama/llama-3.1-405b", "name": "Llama 3.1 405B (OpenRouter)"},
        ]

    return {"models": models, "provider": provider}


# --------------------------------------------------------------------------
# POST /test-connection -- test AI provider connectivity
# --------------------------------------------------------------------------

class AiTestRequest(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4o"
    base_url: Optional[str] = None


@router.post("/test-connection", status_code=status.HTTP_200_OK)
async def test_ai_connection(
    body: AiTestRequest = AiTestRequest(),
    admin: User = Depends(_admin),
):
    """Test AI provider connection using credentials from the request body."""
    if not body.api_key:
        return {"status": "error", "message": "No API key provided."}

    try:
        import httpx
        if body.provider == "openai" or body.provider == "openrouter":
            base_url = body.base_url or (
                "https://openrouter.ai/api/v1" if body.provider == "openrouter"
                else "https://api.openai.com/v1"
            )
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {body.api_key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return {"status": "ok", "message": f"Connected to {body.provider}. Models available."}
                else:
                    return {"status": "error", "message": f"API returned {resp.status_code}: {resp.text[:200]}"}
        elif body.provider == "anthropic":
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": body.api_key, "anthropic-version": "2023-06-01"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connected to Anthropic. Models available."}
                else:
                    return {"status": "error", "message": f"API returned {resp.status_code}: {resp.text[:200]}"}
        elif body.provider == "ollama":
            base_url = body.base_url or "http://localhost:11434"
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base_url}/api/tags", timeout=10)
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connected to Ollama."}
                else:
                    return {"status": "error", "message": f"Ollama returned {resp.status_code}"}
        else:
            return {"status": "error", "message": f"Unknown provider: {body.provider}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
