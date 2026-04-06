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

from api.core.config import settings
from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.email_aliases import EmailAlias
from api.models.packages import Package
from api.models.users import User
from api.schemas.email import (
    AliasCreate,
    AliasResponse,
    AutoresponderResponse,
    AutoresponderUpdate,
    CatchAllResponse,
    CatchAllSet,
    EmailAccountCreate,
    EmailAccountResponse,
    PasswordChange,
    QuotaResponse,
    RateLimitResponse,
    RateLimitUpdate,
    SieveFilterGet,
    SieveFilterPut,
    SieveTestRequest,
    SieveTestResponse,
    SpamFilterResponse,
    SpamFilterUpdate,
)
from api.services.mail_ops import (
    configure_autoresponder_direct,
    configure_catch_all_direct,
    configure_ratelimit_direct,
    configure_spam_filter_direct,
    create_alias_direct,
    create_mailbox_direct,
    delete_alias_direct,
    delete_mailbox_direct,
    flush_mail_queue,
    get_mail_queue,
    get_quota_usage_direct,
    list_aliases_direct,
    read_sieve_filters_direct,
    remove_catch_all_direct,
    remove_from_queue,
    set_password_direct,
    train_spam_direct,
    validate_sieve_direct,
    write_sieve_filters_direct,
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


async def _try_agent_set_password(agent, address: str, new_password: str) -> bool:
    """Attempt password change via agent.  Returns True on success."""
    if agent is None:
        return False
    try:
        await agent._request("PUT", "/mail/set-password", json={
            "address": address,
            "new_password": new_password,
        })
        return True
    except Exception as exc:
        logger.warning("Agent set_password failed, will use direct fallback: %s", exc)
        return False


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

    # -- Package limit check: max_mail_domains --
    if not _is_admin(current_user) and current_user.package_id:
        pkg_result = await db.execute(select(Package).where(Package.id == current_user.package_id))
        pkg = pkg_result.scalar_one_or_none()
        if pkg and pkg.max_mail_domains > 0:
            # Count distinct domains that already have mailboxes for this user
            distinct_domains = (await db.execute(
                select(func.count(func.distinct(EmailAccount.domain_id)))
                .where(EmailAccount.user_id == current_user.id)
            )).scalar() or 0
            # Check if this domain is already in use by the user
            domain_in_use = (await db.execute(
                select(EmailAccount).where(
                    EmailAccount.user_id == current_user.id,
                    EmailAccount.domain_id == body.domain_id,
                ).limit(1)
            )).scalar_one_or_none()
            if domain_in_use is None and distinct_domains >= pkg.max_mail_domains:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Mail domain limit reached ({pkg.max_mail_domains}). Upgrade your package for more.",
                )

    # 1. Save to DB first (store both bcrypt hash for system auth and Fernet-encrypted for SSO)
    acct = EmailAccount(
        user_id=current_user.id,
        domain_id=body.domain_id,
        address=body.address,
        password_hash=hash_password(body.password),
        password_encrypted=encrypt_value(body.password, settings.SECRET_KEY),
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
    # Resolve destinations (supports both legacy single + new multi-target)
    dest_list = body.resolved_destinations()
    if not dest_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one destination address is required.",
        )
    dest_str = ", ".join(dest_list)

    # 1. Check uniqueness in DB
    exists = await db.execute(select(EmailAlias).where(EmailAlias.source == body.source))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Alias source already exists.")

    # 2. Save to DB first
    alias = EmailAlias(
        user_id=current_user.id,
        source=body.source,
        destination=dest_str,
        keep_local_copy=body.keep_local_copy,
    )
    db.add(alias)
    await db.flush()

    # 3. Try agent, fall back to direct
    agent = _get_agent(request)
    agent_ok = await _try_agent_create_alias(agent, body.source, dest_str)

    if not agent_ok:
        result = await create_alias_direct(
            body.source, dest_str,
            destinations=dest_list,
            keep_local_copy=body.keep_local_copy,
        )
        if not result.get("ok"):
            logger.error("Direct alias creation failed for %s: %s", body.source, result.get("error"))

    _log(db, request, current_user.id, "email.create_alias", f"Created alias {body.source} -> {dest_str}")
    return AliasResponse.from_alias(alias)


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
            "items": [AliasResponse.from_alias(a) for a in results],
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
# Catch-All email -- /domains/{domain}/catch-all
# MUST be before /{email_id} to avoid path conflicts.
# ==========================================================================

@router.get("/domains/{domain}/catch-all", response_model=CatchAllResponse, status_code=status.HTTP_200_OK)
async def get_catch_all(
    domain: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the catch-all configuration for a domain."""
    result = await db.execute(select(Domain).where(Domain.domain_name == domain))
    dom = result.scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and dom.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    return CatchAllResponse(
        domain=dom.domain_name,
        catch_all_address=dom.catch_all_address,
        enabled=dom.catch_all_address is not None,
    )


@router.put("/domains/{domain}/catch-all", response_model=CatchAllResponse, status_code=status.HTTP_200_OK)
async def set_catch_all(
    domain: str,
    body: CatchAllSet,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the catch-all email address for a domain."""
    result = await db.execute(select(Domain).where(Domain.domain_name == domain))
    dom = result.scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and dom.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    dom.catch_all_address = body.address
    db.add(dom)
    await db.flush()

    # Configure catch-all in Exim4 virtual aliases
    sys_result = await configure_catch_all_direct(domain, body.address)
    if not sys_result.get("ok"):
        logger.error("Failed to configure catch-all for %s: %s", domain, sys_result.get("error"))

    _log(db, request, current_user.id, "email.catch_all_set", f"Set catch-all for {domain} -> {body.address}")
    return CatchAllResponse(
        domain=dom.domain_name,
        catch_all_address=dom.catch_all_address,
        enabled=True,
    )


@router.delete("/domains/{domain}/catch-all", status_code=status.HTTP_200_OK)
async def delete_catch_all(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable the catch-all email for a domain."""
    result = await db.execute(select(Domain).where(Domain.domain_name == domain))
    dom = result.scalar_one_or_none()
    if dom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and dom.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    dom.catch_all_address = None
    db.add(dom)
    await db.flush()

    # Remove catch-all from Exim4 virtual aliases
    sys_result = await remove_catch_all_direct(domain)
    if not sys_result.get("ok"):
        logger.error("Failed to remove catch-all for %s: %s", domain, sys_result.get("error"))

    _log(db, request, current_user.id, "email.catch_all_remove", f"Removed catch-all for {domain}")
    return CatchAllResponse(domain=dom.domain_name, catch_all_address=None, enabled=False)


# ==========================================================================
# PUT /{id}/password -- change mailbox password
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================

@router.put("/{email_id}/password", status_code=status.HTTP_200_OK)
async def change_password(
    email_id: uuid.UUID,
    body: PasswordChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the password for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # 1. Update DB: bcrypt hash + re-encrypt for SSO
    acct.password_hash = hash_password(body.new_password)
    acct.password_encrypted = encrypt_value(body.new_password, settings.SECRET_KEY)
    db.add(acct)
    await db.flush()

    # 2. Update system: agent -> direct fallback
    agent = _get_agent(request)
    agent_ok = await _try_agent_set_password(agent, acct.address, body.new_password)

    if not agent_ok:
        result = await set_password_direct(acct.address, body.new_password)
        if not result.get("ok"):
            logger.error("Direct set_password failed for %s: %s", acct.address, result.get("error"))

    _log(db, request, current_user.id, "email.change_password", f"Changed password for {acct.address}")
    return {"detail": "Password changed successfully."}


# ==========================================================================
# GET /{id}/quota -- get current quota usage
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================

@router.get("/{email_id}/quota", response_model=QuotaResponse, status_code=status.HTTP_200_OK)
async def get_quota(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current quota usage for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # Try to get live usage from the system
    usage_result = await get_quota_usage_direct(acct.address)
    used_mb = usage_result.get("used_mb", acct.quota_used_mb)

    # Update cached value in DB
    acct.quota_used_mb = used_mb
    db.add(acct)
    await db.flush()

    usage_percent = round((used_mb / acct.quota_mb) * 100, 1) if acct.quota_mb > 0 else 0.0

    return QuotaResponse(
        address=acct.address,
        quota_mb=acct.quota_mb,
        quota_used_mb=used_mb,
        usage_percent=usage_percent,
    )


# ==========================================================================
# PUT /{id}/rate-limit -- configure email rate limiting
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================

@router.put("/{email_id}/rate-limit", response_model=RateLimitResponse, status_code=status.HTTP_200_OK)
async def update_rate_limit(
    email_id: uuid.UUID,
    body: RateLimitUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Configure the outbound email rate limit for a mailbox."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # 1. Save to DB
    acct.max_emails_per_hour = body.max_emails_per_hour
    db.add(acct)
    await db.flush()

    # 2. Configure in Exim4 (direct -- no agent endpoint for this yet)
    result = await configure_ratelimit_direct(acct.address, body.max_emails_per_hour)
    if not result.get("ok"):
        logger.error("configure_ratelimit_direct failed for %s: %s", acct.address, result.get("error"))

    _log(db, request, current_user.id, "email.rate_limit",
         f"Set rate limit to {body.max_emails_per_hour}/hr for {acct.address}")

    return RateLimitResponse(
        address=acct.address,
        max_emails_per_hour=acct.max_emails_per_hour,
    )


# ==========================================================================
# POST /{id}/sso -- generate SSO token for Roundcube auto-login
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================

@router.post("/{email_id}/sso", status_code=status.HTTP_200_OK)
async def email_sso(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a one-time SSO token for Roundcube webmail auto-login."""
    import json as _json
    import secrets

    acct = await _get_email_or_404(email_id, db, current_user)

    if not acct.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email account is inactive.",
        )

    # Decrypt the stored password
    if not acct.password_encrypted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No recoverable password stored. Re-set the mailbox password to enable SSO.",
        )

    try:
        password = decrypt_value(acct.password_encrypted, settings.SECRET_KEY)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to recover email credentials. Password may need to be reset.",
        )

    # Generate one-time token stored in Redis (expires 30s)
    token = secrets.token_urlsafe(32)
    redis = request.app.state.redis
    await redis.setex(
        f"hosthive:rc_sso:{token}",
        30,
        _json.dumps({
            "user": acct.address,
            "password": password,
        }),
    )

    _log(db, request, current_user.id, "email.sso", f"SSO login to Roundcube for {acct.address}")
    return {"sso_url": f"/roundcube/sso.php?token={token}"}


# ==========================================================================
# Sieve filter endpoints
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================


def _rules_to_sieve(rules: list) -> str:
    """Compile a list of visual filter rules into a Sieve script."""
    requires = set()
    rule_blocks = []

    for rule in rules:
        field = rule.field.lower()
        match_type = rule.match_type
        value = rule.value
        action = rule.action.lower()
        action_value = rule.action_value or ""

        # Determine require extensions
        if action == "fileinto":
            requires.add('"fileinto"')
        if action == "addflag":
            requires.add('"imap4flags"')
        if action == "redirect":
            pass  # redirect is built-in
        if match_type == "regex":
            requires.add('"regex"')

        # Build the test
        header_name = {
            "from": '"From"',
            "to": '"To"',
            "subject": '"Subject"',
            "cc": '"Cc"',
        }.get(field, f'"{field}"')

        match_tag = {
            "contains": ":contains",
            "matches": ":matches",
            "is": ":is",
            "regex": ":regex",
        }.get(match_type, ":contains")

        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        test = f'header {match_tag} {header_name} "{escaped_value}"'

        # Build the action
        escaped_action_value = action_value.replace("\\", "\\\\").replace('"', '\\"')
        if action == "fileinto":
            action_line = f'fileinto "{escaped_action_value}";'
        elif action == "redirect":
            action_line = f'redirect "{escaped_action_value}";'
        elif action == "discard":
            action_line = "discard;"
        elif action == "addflag":
            action_line = f'addflag "{escaped_action_value}";'
        else:
            action_line = "keep;"

        rule_blocks.append(f"if {test} {{\n    {action_line}\n}}")

    lines = []
    if requires:
        lines.append(f"require [{', '.join(sorted(requires))}];")
        lines.append("")
    lines.extend(rule_blocks)
    return "\n".join(lines) + "\n"


@router.get("/accounts/{email_id}/filters", response_model=SieveFilterGet, status_code=status.HTTP_200_OK)
async def get_sieve_filters(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current Sieve filter rules for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)

    result = await read_sieve_filters_direct(acct.address)
    return SieveFilterGet(
        script=result.get("script", ""),
        active=result.get("active", False),
    )


@router.put("/accounts/{email_id}/filters", response_model=SieveFilterGet, status_code=status.HTTP_200_OK)
async def save_sieve_filters(
    email_id: uuid.UUID,
    body: SieveFilterPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a Sieve filter script (from raw text or compiled from visual rules)."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # Determine the script to write
    if body.rules is not None:
        script = _rules_to_sieve(body.rules)
    elif body.script is not None:
        script = body.script
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either 'script' or 'rules'.",
        )

    result = await write_sieve_filters_direct(acct.address, script)
    if not result.get("ok"):
        logger.error("write_sieve_filters_direct failed for %s: %s", acct.address, result.get("error"))

    _log(db, request, current_user.id, "email.filters_save", f"Saved Sieve filters for {acct.address}")

    return SieveFilterGet(
        script=script,
        active=bool(script.strip()),
    )


@router.post("/accounts/{email_id}/filters/test", response_model=SieveTestResponse, status_code=status.HTTP_200_OK)
async def test_sieve_filters(
    email_id: uuid.UUID,
    body: SieveTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate a Sieve script syntax using sievec."""
    # Verify the user owns this account
    await _get_email_or_404(email_id, db, current_user)

    result = await validate_sieve_direct(body.script)
    return SieveTestResponse(
        valid=result.get("valid", False),
        errors=result.get("errors"),
    )


# ==========================================================================
# Spam filter endpoints
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================


@router.get("/accounts/{email_id}/spam", response_model=SpamFilterResponse, status_code=status.HTTP_200_OK)
async def get_spam_settings(
    email_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the per-user spam filter settings for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)
    return SpamFilterResponse(
        enabled=acct.spam_filter_enabled,
        threshold=acct.spam_threshold,
        action=acct.spam_action,
        whitelist=acct.spam_whitelist,
        blacklist=acct.spam_blacklist,
    )


@router.put("/accounts/{email_id}/spam", response_model=SpamFilterResponse, status_code=status.HTTP_200_OK)
async def update_spam_settings(
    email_id: uuid.UUID,
    body: SpamFilterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update per-user spam filter settings for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # Validate action
    if body.action not in ("move", "delete", "tag_only"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid spam action. Must be 'move', 'delete', or 'tag_only'.",
        )

    # 1. Save to DB
    acct.spam_filter_enabled = body.enabled
    acct.spam_threshold = body.threshold
    acct.spam_action = body.action
    acct.spam_whitelist = body.whitelist
    acct.spam_blacklist = body.blacklist
    db.add(acct)
    await db.flush()

    # 2. Configure SpamAssassin + Sieve on the system (direct fallback)
    result = await configure_spam_filter_direct(
        address=acct.address,
        enabled=body.enabled,
        threshold=body.threshold,
        action=body.action,
        whitelist=body.whitelist,
        blacklist=body.blacklist,
    )
    if not result.get("ok"):
        logger.error("configure_spam_filter_direct failed for %s: %s", acct.address, result.get("error"))

    _log(db, request, current_user.id, "email.spam_filter",
         f"Updated spam filter for {acct.address} (enabled={body.enabled}, action={body.action})")

    return SpamFilterResponse(
        enabled=acct.spam_filter_enabled,
        threshold=acct.spam_threshold,
        action=acct.spam_action,
        whitelist=acct.spam_whitelist,
        blacklist=acct.spam_blacklist,
    )


@router.post("/accounts/{email_id}/spam/train-ham", status_code=status.HTTP_200_OK)
async def train_ham(
    email_id: uuid.UUID,
    request: Request,
    message_path: str = Query(..., description="Path to the message file to train as not-spam"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Train SpamAssassin: mark a message as not-spam (ham)."""
    acct = await _get_email_or_404(email_id, db, current_user)

    result = await train_spam_direct(
        address=acct.address,
        message_path=message_path,
        is_spam=False,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to train ham."),
        )

    _log(db, request, current_user.id, "email.spam_train_ham",
         f"Trained ham for {acct.address}: {message_path}")
    return result


@router.post("/accounts/{email_id}/spam/train-spam", status_code=status.HTTP_200_OK)
async def train_spam_endpoint(
    email_id: uuid.UUID,
    request: Request,
    message_path: str = Query(..., description="Path to the message file to train as spam"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Train SpamAssassin: mark a message as spam."""
    acct = await _get_email_or_404(email_id, db, current_user)

    result = await train_spam_direct(
        address=acct.address,
        message_path=message_path,
        is_spam=True,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to train spam."),
        )

    _log(db, request, current_user.id, "email.spam_train_spam",
         f"Trained spam for {acct.address}: {message_path}")
    return result


# ==========================================================================
# Autoresponder endpoints
# MUST be before /{email_id} catch-all to avoid path conflicts.
# ==========================================================================

async def _try_agent_configure_autoresponder(agent, address: str, enabled: bool,
                                              subject: str | None, body: str | None,
                                              start_date: str | None, end_date: str | None) -> bool:
    """Attempt to configure autoresponder via agent. Returns True on success."""
    if agent is None:
        return False
    try:
        await agent._request("PUT", "/mail/autoresponder", json={
            "address": address,
            "enabled": enabled,
            "subject": subject,
            "body": body,
            "start_date": start_date,
            "end_date": end_date,
        })
        return True
    except Exception as exc:
        logger.warning("Agent configure_autoresponder failed, will use direct fallback: %s", exc)
        return False


@router.get("/{email_id}/autoresponder", response_model=AutoresponderResponse, status_code=status.HTTP_200_OK)
async def get_autoresponder(
    email_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current autoresponder settings for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)
    return AutoresponderResponse(
        enabled=acct.autoresponder_enabled,
        subject=acct.autoresponder_subject,
        body=acct.autoresponder_body,
        start_date=acct.autoresponder_start_date,
        end_date=acct.autoresponder_end_date,
    )


@router.put("/{email_id}/autoresponder", response_model=AutoresponderResponse, status_code=status.HTTP_200_OK)
async def update_autoresponder(
    email_id: uuid.UUID,
    body: AutoresponderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable or configure the autoresponder for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # Validate: subject and body required when enabling
    if body.enabled and (not body.subject or not body.body):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject and body are required when enabling autoresponder.",
        )

    # 1. Save to DB
    acct.autoresponder_enabled = body.enabled
    acct.autoresponder_subject = body.subject
    acct.autoresponder_body = body.body
    acct.autoresponder_start_date = body.start_date
    acct.autoresponder_end_date = body.end_date
    db.add(acct)
    await db.flush()

    # 2. Configure Sieve on the system (agent -> direct fallback)
    start_str = body.start_date.isoformat() if body.start_date else None
    end_str = body.end_date.isoformat() if body.end_date else None

    agent = _get_agent(request)
    agent_ok = await _try_agent_configure_autoresponder(
        agent, acct.address, body.enabled, body.subject, body.body, start_str, end_str,
    )

    if not agent_ok:
        result = await configure_autoresponder_direct(
            address=acct.address,
            enabled=body.enabled,
            subject=body.subject,
            body=body.body,
            start_date=start_str,
            end_date=end_str,
        )
        if not result.get("ok"):
            logger.error("Direct autoresponder config failed for %s: %s", acct.address, result.get("error"))

    _log(db, request, current_user.id, "email.autoresponder",
         f"{'Enabled' if body.enabled else 'Updated'} autoresponder for {acct.address}")

    return AutoresponderResponse(
        enabled=acct.autoresponder_enabled,
        subject=acct.autoresponder_subject,
        body=acct.autoresponder_body,
        start_date=acct.autoresponder_start_date,
        end_date=acct.autoresponder_end_date,
    )


@router.delete("/{email_id}/autoresponder", status_code=status.HTTP_200_OK)
async def disable_autoresponder(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable the autoresponder for an email account."""
    acct = await _get_email_or_404(email_id, db, current_user)

    # 1. Update DB
    acct.autoresponder_enabled = False
    db.add(acct)
    await db.flush()

    # 2. Remove Sieve script on the system
    agent = _get_agent(request)
    agent_ok = await _try_agent_configure_autoresponder(
        agent, acct.address, False, None, None, None, None,
    )

    if not agent_ok:
        result = await configure_autoresponder_direct(
            address=acct.address,
            enabled=False,
        )
        if not result.get("ok"):
            logger.error("Direct autoresponder disable failed for %s: %s", acct.address, result.get("error"))

    _log(db, request, current_user.id, "email.autoresponder", f"Disabled autoresponder for {acct.address}")
    return {"detail": "Autoresponder disabled."}


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
