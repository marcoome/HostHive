"""Email router -- /api/v1/email."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user, hash_password, require_role
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.users import User
from api.schemas.email import AliasCreate, EmailAccountCreate, EmailAccountResponse

router = APIRouter()

_admin = require_role("admin")


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


# --------------------------------------------------------------------------
# GET / -- list mailboxes
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# POST / -- create mailbox
# --------------------------------------------------------------------------
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

    # Uniqueness
    exists = await db.execute(select(EmailAccount).where(EmailAccount.address == body.address))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email address already exists.")

    agent = request.app.state.agent
    try:
        await agent.create_mailbox(
            address=body.address,
            password=body.password,
            quota_mb=body.quota_mb,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error creating mailbox: {exc}",
        )

    acct = EmailAccount(
        user_id=current_user.id,
        domain_id=body.domain_id,
        address=body.address,
        password_hash=hash_password(body.password),
        quota_mb=body.quota_mb,
    )
    db.add(acct)
    await db.flush()

    _log(db, request, current_user.id, "email.create", f"Created mailbox {body.address}")
    return EmailAccountResponse.model_validate(acct)


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
    agent = request.app.state.agent
    try:
        result = await agent.create_mail_alias(source=body.source, destination=body.destination)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error creating alias: {exc}",
        )

    _log(db, request, current_user.id, "email.create_alias", f"Created alias {body.source} -> {body.destination}")
    return {"source": body.source, "destination": body.destination, "status": "created"}


@router.get("/aliases", status_code=status.HTTP_200_OK)
async def list_aliases(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/mail/aliases")
    except Exception:
        result = {"aliases": []}
    return result


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    alias_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    try:
        await agent._request("DELETE", f"/mail/alias/{alias_id}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting alias: {exc}",
        )

    _log(db, request, current_user.id, "email.delete_alias", f"Deleted alias {alias_id}")


# ==========================================================================
# Mail queue (admin only) -- must be before /{email_id}
# ==========================================================================

@router.get("/queue", status_code=status.HTTP_200_OK)
async def mail_queue(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/mail/queue")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error fetching mail queue: {exc}",
        )
    return result


@router.post("/queue/flush", status_code=status.HTTP_200_OK)
async def flush_mail_queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("POST", "/mail/queue/flush")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error flushing queue: {exc}",
        )

    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=admin.id,
        action="email.flush_queue",
        details="Flushed mail queue",
        ip_address=client_ip,
    ))
    return result


# --------------------------------------------------------------------------
# GET /{id} -- mailbox detail (MUST be after all static path routes)
# --------------------------------------------------------------------------
@router.get("/{email_id}", response_model=EmailAccountResponse, status_code=status.HTTP_200_OK)
async def get_mailbox(
    email_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return EmailAccountResponse.model_validate(await _get_email_or_404(email_id, db, current_user))


# --------------------------------------------------------------------------
# PUT /{id} -- update mailbox
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# DELETE /{id} -- delete mailbox
# --------------------------------------------------------------------------
@router.delete("/{email_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailbox(
    email_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    acct = await _get_email_or_404(email_id, db, current_user)
    agent = request.app.state.agent

    try:
        await agent.delete_mailbox(acct.address)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting mailbox: {exc}",
        )

    _log(db, request, current_user.id, "email.delete", f"Deleted mailbox {acct.address}")
    await db.delete(acct)
    await db.flush()
