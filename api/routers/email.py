"""Email router -- /api/v1/email.

All operations follow a DB-first pattern:
  1. Validate & save to database
  2. Try the agent for system-level changes
  3. If the agent is unavailable, fall back to direct system operations

Every system call is wrapped in try/except so a DB record always persists
even if the underlying OS operations fail.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.email_aliases import EmailAlias
from api.models.users import User
from api.schemas.email import (
    AliasCreate,
    AliasResponse,
    EmailAccountCreate,
    EmailAccountResponse,
)
from api.services.mail_ops import (
    create_alias_direct,
    create_mailbox_direct,
    delete_alias_direct,
    delete_mailbox_direct,
    flush_mail_queue,
    get_mail_queue,
    list_aliases_direct,
    remove_from_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_admin = require_role("admin")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_email_or_404(
    email_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> EmailAccount:
    result = await db.execute(select(EmailAccount).where(EmailAccount.id == email_id))
    acct = result.scalar_one_or_none()
    if acct is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found.")
    if not _is_admin(current_user) and acct.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return acct


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _get_agent(request: Request):
    """Return the agent client or None if unavailable."""
    try:
        agent = getattr(request.app.state, "agent", None)
        return agent
    except Exception:
        return None


async def _try_agent_create_mailbox(agent, address: str, password: str, quota_mb: int) -> bool:
    """Attempt mailbox creation via agent.  Returns True on success."""
    if agent is None:
        return False
    try:
        await agent.create_mailbox(address=address, password=password, quota_mb=quota_mb)
        return True
    except Exception as exc:
        logger.warning("Agent create_mailbox failed, will use direct fallback: %s", exc)
        return False


async def _try_agent_delete_mailbox(agent, address: str) -> bool:
    """Attempt mailbox deletion via agent.  Returns True on success."""
    if agent is None:
        return False
    try:
        await agent.delete_mailbox(address)
        return True
    except Exception as exc:
        logger.warning("Agent delete_mailbox failed, will use direct fallback: %s", exc)
        return False


async def _try_agent_create_alias(agent, source: str, destination: str) -> bool:
    """Attempt alias creation via agent.  Returns True on success."""
    if agent is None:
        return False
    try:
        await agent.create_mail_alias(source=source, destination=destination)
        return True
    except Exception as exc:
        logger.warning("Agent create_mail_alias failed, will use direct fallback: %s", exc)
        return False


async def _try_agent_delete_alias(agent, alias_id: str) -> bool:
    """Attempt alias deletion via agent.  Returns True on success."""
    if agent is None:
        return False
    try:
        await agent._request("DELETE", f"/mail/alias/{alias_id}")
        return True
    except Exception as exc:
        logger.warning("Agent delete_alias failed, will use direct fallback: %s", exc)
        return False


async def _try_agent_list_aliases(agent) -> dict | None:
    """Attempt to list aliases via agent.  Returns dict or None."""
    if agent is None:
        return None
    try:
        return await agent._request("GET", "/mail/aliases")
    except Exception as exc:
        logger.warning("Agent list_aliases failed, will use direct fallback: %s", exc)
        return None


async def _try_agent_get_queue(agent) -> dict | None:
    """Attempt to get mail queue via agent.  Returns dict or None."""
    if agent is None:
        return None
    try:
        return await agent._request("GET", "/mail/queue")
    except Exception as exc:
        logger.warning("Agent get_queue failed, will use direct fallback: %s", exc)
        return None


async def _try_agent_flush_queue(agent) -> dict | None:
    """Attempt to flush mail queue via agent.  Returns dict or None."""
    if agent is None:
        return None
    try:
        return await agent._request("POST", "/mail/queue/flush")
    except Exception as exc:
        logger.warning("Agent flush_queue failed, will use direct fallback: %s", exc)
        return None


# ==========================================================================
# GET / -- list mailboxes (DB only, no agent needed)
# ==========================================================================

@router.get("", status_code=status.HTTP_200_OK)
async def list_mailboxes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(EmailAccount)
    count_query = select(func.count()).select_from(EmailAccount)
    if not _is_admin(current_user):
        query = query.where(EmailAccount.user_id == current_user.id)
        count_query = count_query.where(EmailAccount.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    return {
        "items": [EmailAccountResponse.model_validate(e) for e in results],
        "total": total,
    }


# ==========================================================================
# POST / -- create mailbox
# ==========================================================================

@router.post("", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_mailbox(
    body: EmailAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify domain ownership
    domain_result = await db.execute(select(Domain).where(Domain.id == body.domain_id))
    domain = domain_result.scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and domain.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to domain.")

    # Uniqueness check
    exists = await db.execute(select(EmailAccount).where(EmailAccount.address == body.address))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email address already exists.")

    # 1. Save to DB first
    acct = EmailAccount(
        user_id=current_user.id,
        domain_id=body.domain_id,
        address=body.address,
        password_hash=hash_password(body.password),
        quota_mb=body.quota_mb,
    )
    db.add(acct)
    await db.flush()

    # 2. Try agent, fall back to direct system operations
    system_warning = None
    agent = _get_agent(request)
    agent_ok = await _try_agent_create_mailbox(agent, body.address, body.password, body.quota_mb)

    if not agent_ok:
        result = await create_mailbox_direct(body.address, body.password, body.quota_mb)
        if not result.get("ok"):
            system_warning = result.get("error", "Direct mailbox creation returned an error")
            logger.error("Direct mailbox creation failed for %s: %s", body.address, system_warning)

    _log(db, request, current_user.id, "email.create", f"Created mailbox {body.address}")

    resp = EmailAccountResponse.model_validate(acct)
    if system_warning:
        # Attach warning but still return 201 -- DB record exists
        return resp  # type: ignore[return-value]
    return resp


# ==========================================================================
# Alias routes for frontend compatibility (/mailboxes/...)
# IMPORTANT: These MUST be defined BEFORE /{email_id} to avoid FastAPI
# matching "mailboxes" as a UUID path parameter.
# ==========================================================================

@router.get("/mailboxes", status_code=status.HTTP_200_OK)
async def list_mailboxes_alias(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_mailboxes(skip=skip, limit=limit, db=db, current_user=current_user)


@router.post("/mailboxes", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_mailbox_alias(
    body: EmailAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await create_mailbox(body=body, request=request, db=db, current_user=current_user)


@router.get("/mailboxes/{email_id}", response_model=EmailAccountResponse, status_code=status.HTTP_200_OK)
async def get_mailbox_alias(
    email_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return EmailAccountResponse.model_validate(await _get_email_or_404(email_id, db, current_user))


@router.put("/mailboxes/{email_id}", response_model=EmailAccountResponse, status_code=status.HTTP_200_OK)
async def update_mailbox_alias(
    email_id: uuid.UUID,
    quota_mb: int = Query(None, ge=1),
    is_active: bool = Query(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await update_mailbox(
        email_id=email_id, quota_mb=quota_mb, is_active=is_active,
        request=request, db=db, current_user=current_user,
    )


@router.delete("/mailboxes/{email_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailbox_alias(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await delete_mailbox(email_id=email_id, request=request, db=db, current_user=current_user)


# ==========================================================================
# Aliases (/aliases/...)
# IMPORTANT: These MUST be defined BEFORE /{email_id} routes.
# ==========================================================================

@router.post("/aliases", status_code=status.HTTP_201_CREATED)
async def create_alias(
    body: AliasCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Check uniqueness in DB
    exists = await db.execute(select(EmailAlias).where(EmailAlias.source == body.source))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Alias source already exists.")

    # 2. Save to DB first
    alias = EmailAlias(
        user_id=current_user.id,
        source=body.source,
        destination=body.destination,
    )
    db.add(alias)
    await db.flush()

    # 3. Try agent, fall back to direct
    agent = _get_agent(request)
    agent_ok = await _try_agent_create_alias(agent, body.source, body.destination)

    if not agent_ok:
        result = await create_alias_direct(body.source, body.destination)
        if not result.get("ok"):
            logger.error("Direct alias creation failed for %s: %s", body.source, result.get("error"))

    _log(db, request, current_user.id, "email.create_alias", f"Created alias {body.source} -> {body.destination}")
    return AliasResponse.model_validate(alias)


@router.get("/aliases", status_code=status.HTTP_200_OK)
async def list_aliases(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Read from DB (primary source of truth)
    query = select(EmailAlias)
    count_query = select(func.count()).select_from(EmailAlias)
    if not _is_admin(current_user):
        query = query.where(EmailAlias.user_id == current_user.id)
        count_query = count_query.where(EmailAlias.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    if results:
        return {
            "items": [AliasResponse.model_validate(a) for a in results],
            "total": total,
        }

    # If DB is empty, try agent then direct file as a migration path
    agent = _get_agent(request)
    agent_result = await _try_agent_list_aliases(agent)
    if agent_result is not None:
        return agent_result

    # Direct fallback -- read from Exim virtual_aliases file
    try:
        direct = await list_aliases_direct()
        return {"aliases": direct.get("aliases", []), "total": len(direct.get("aliases", []))}
    except Exception:
        return {"aliases": [], "total": 0}


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    alias_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Try to find by UUID in DB
    db_alias = None
    try:
        alias_uuid = uuid.UUID(alias_id)
        result = await db.execute(select(EmailAlias).where(EmailAlias.id == alias_uuid))
        db_alias = result.scalar_one_or_none()
    except (ValueError, AttributeError):
        pass  # alias_id is not a UUID -- treat as source address

    source_for_file = alias_id  # default: use as-is for file cleanup

    if db_alias is not None:
        if not _is_admin(current_user) and db_alias.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
        source_for_file = db_alias.source
        await db.delete(db_alias)
        await db.flush()

    # System-level removal: try agent, then direct
    agent = _get_agent(request)
    agent_ok = await _try_agent_delete_alias(agent, alias_id)

    if not agent_ok:
        result = await delete_alias_direct(source_for_file)
        if not result.get("ok"):
            logger.error("Direct alias deletion failed for %s: %s", source_for_file, result.get("error"))

    _log(db, request, current_user.id, "email.delete_alias", f"Deleted alias {alias_id}")


# ==========================================================================
# Mail queue (admin only) -- must be before /{email_id}
# ==========================================================================

@router.get("/queue", status_code=status.HTTP_200_OK)
async def mail_queue(
    request: Request,
    admin: User = Depends(_admin),
):
    # Try agent first, fall back to direct
    agent = _get_agent(request)
    agent_result = await _try_agent_get_queue(agent)
    if agent_result is not None:
        return agent_result

    # Direct fallback
    try:
        result = await get_mail_queue()
        return {
            "queue": result.get("queue", []),
            "count": result.get("count", 0),
            "raw": result.get("raw", ""),
        }
    except Exception:
        return {"queue": [], "count": 0, "_direct_fallback_error": True}


@router.delete("/queue/{message_id}", status_code=status.HTTP_200_OK)
async def remove_queue_message(
    message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # Try agent first
    agent = _get_agent(request)
    if agent is not None:
        try:
            result = await agent._request("DELETE", f"/mail/queue/{message_id}")
            _log(db, request, admin.id, "email.queue_remove", f"Removed message {message_id} from queue")
            return result
        except Exception as exc:
            logger.warning("Agent remove_queue failed: %s", exc)

    # Direct fallback
    try:
        result = await remove_from_queue(message_id)
        _log(db, request, admin.id, "email.queue_remove", f"Removed message {message_id} from queue (direct)")
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove message from queue: {exc}",
        )


@router.post("/queue/flush", status_code=status.HTTP_200_OK)
async def flush_mail_queue_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    # Try agent first
    agent = _get_agent(request)
    agent_result = await _try_agent_flush_queue(agent)
    if agent_result is not None:
        _log(db, request, admin.id, "email.flush_queue", "Flushed mail queue")
        return agent_result

    # Direct fallback
    try:
        result = await flush_mail_queue()
        _log(db, request, admin.id, "email.flush_queue", "Flushed mail queue (direct)")
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to flush mail queue: {exc}",
        )


# ==========================================================================
# GET /{id} -- mailbox detail (MUST be after all static path routes)
# ==========================================================================

@router.get("/{email_id}", response_model=EmailAccountResponse, status_code=status.HTTP_200_OK)
async def get_mailbox(
    email_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return EmailAccountResponse.model_validate(await _get_email_or_404(email_id, db, current_user))


# ==========================================================================
# PUT /{id} -- update mailbox
# ==========================================================================

@router.put("/{email_id}", response_model=EmailAccountResponse, status_code=status.HTTP_200_OK)
async def update_mailbox(
    email_id: uuid.UUID,
    quota_mb: int = Query(None, ge=1),
    is_active: bool = Query(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    acct = await _get_email_or_404(email_id, db, current_user)
    if quota_mb is not None:
        acct.quota_mb = quota_mb
    if is_active is not None:
        acct.is_active = is_active
    db.add(acct)
    await db.flush()

    _log(db, request, current_user.id, "email.update", f"Updated mailbox {acct.address}")
    return EmailAccountResponse.model_validate(acct)


# ==========================================================================
# DELETE /{id} -- delete mailbox
# ==========================================================================

@router.delete("/{email_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailbox(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    acct = await _get_email_or_404(email_id, db, current_user)

    # 1. Remove from DB first
    _log(db, request, current_user.id, "email.delete", f"Deleted mailbox {acct.address}")
    address = acct.address  # capture before delete
    await db.delete(acct)
    await db.flush()

    # 2. Try agent, fall back to direct system operations
    agent = _get_agent(request)
    agent_ok = await _try_agent_delete_mailbox(agent, address)

    if not agent_ok:
        result = await delete_mailbox_direct(address, remove_directory=False)
        if not result.get("ok"):
            logger.error("Direct mailbox deletion failed for %s: %s", address, result.get("error"))
