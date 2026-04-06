"""Mailing lists router -- /api/v1/email/lists.

Provides Mailman-style mailing list management integrated with Exim4
virtual aliases for message distribution.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.mailing_list import MailingList, MailingListMember
from api.models.users import User
from api.schemas.mailing_list import (
    ListCreate,
    ListResponse,
    ListSendMessage,
    ListUpdate,
    MemberAdd,
    MemberResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _get_list_or_404(
    list_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
    *,
    load_members: bool = False,
) -> MailingList:
    stmt = select(MailingList).where(MailingList.id == list_id)
    if load_members:
        stmt = stmt.options(selectinload(MailingList.members))
    result = await db.execute(stmt)
    ml = result.scalar_one_or_none()
    if ml is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailing list not found.")
    if not _is_admin(current_user) and ml.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return ml


def _build_response(ml: MailingList, *, include_members: bool = False) -> dict:
    members = []
    member_count = 0
    if hasattr(ml, "members") and ml.members is not None:
        member_count = len(ml.members)
        if include_members:
            members = [MemberResponse.model_validate(m).model_dump() for m in ml.members]
    data = ListResponse.model_validate(ml).model_dump()
    data["member_count"] = member_count
    data["members"] = members if include_members else []
    return data


def _sync_exim_aliases(ml: MailingList) -> None:
    """Synchronize Exim4 virtual alias for the mailing list distribution.

    Best-effort: failures are logged but do not block the API response.
    """
    try:
        from agent.executors.mail_executor import (
            configure_mailing_list_aliases,
        )
        member_emails = [m.email for m in ml.members] if ml.members else []
        configure_mailing_list_aliases(
            list_address=ml.list_address,
            name=ml.name,
            domain=ml.list_address.split("@")[1],
            members=member_emails,
            is_active=ml.is_active,
            reply_to_list=ml.reply_to_list,
        )
    except Exception as exc:
        logger.warning("Failed to sync Exim aliases for list %s: %s", ml.list_address, exc)


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/lists", response_model=list[ListResponse])
async def list_mailing_lists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all mailing lists owned by the current user (or all if admin)."""
    stmt = select(MailingList).options(selectinload(MailingList.members))
    if not _is_admin(current_user):
        stmt = stmt.where(MailingList.user_id == current_user.id)
    stmt = stmt.order_by(MailingList.created_at.desc())
    result = await db.execute(stmt)
    lists = result.scalars().all()
    return [_build_response(ml) for ml in lists]


@router.post("/lists", response_model=ListResponse, status_code=status.HTTP_201_CREATED)
async def create_mailing_list(
    payload: ListCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new mailing list."""
    # Verify domain ownership
    result = await db.execute(select(Domain).where(Domain.id == payload.domain_id))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and domain.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this domain.")

    domain_name = domain.domain_name if hasattr(domain, "domain_name") else domain.name
    list_address = f"{payload.name}@{domain_name}"

    # Check uniqueness
    exists = await db.execute(
        select(func.count()).select_from(MailingList).where(MailingList.list_address == list_address)
    )
    if exists.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A mailing list with address '{list_address}' already exists.",
        )

    ml = MailingList(
        user_id=current_user.id,
        domain_id=payload.domain_id,
        name=payload.name,
        list_address=list_address,
        description=payload.description,
        owner_email=payload.owner_email,
        is_moderated=payload.is_moderated,
        archive_enabled=payload.archive_enabled,
        max_message_size_kb=payload.max_message_size_kb,
        reply_to_list=payload.reply_to_list,
    )
    db.add(ml)
    await db.flush()

    _log(db, request, current_user.id, "mailing_list_create", f"Created mailing list {list_address}")

    # Sync Exim aliases (empty member list initially)
    ml.members = []
    _sync_exim_aliases(ml)

    return _build_response(ml)


@router.get("/lists/{list_id}", response_model=ListResponse)
async def get_mailing_list(
    list_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get mailing list details with full member list."""
    ml = await _get_list_or_404(list_id, db, current_user, load_members=True)
    return _build_response(ml, include_members=True)


@router.put("/lists/{list_id}", response_model=ListResponse)
async def update_mailing_list(
    list_id: uuid.UUID,
    payload: ListUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update mailing list settings."""
    ml = await _get_list_or_404(list_id, db, current_user, load_members=True)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(ml, key, value)

    await db.flush()
    _log(db, request, current_user.id, "mailing_list_update", f"Updated mailing list {ml.list_address}")

    _sync_exim_aliases(ml)

    return _build_response(ml)


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailing_list(
    list_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a mailing list and all its members."""
    ml = await _get_list_or_404(list_id, db, current_user, load_members=True)
    address = ml.list_address

    # Remove Exim aliases
    try:
        from agent.executors.mail_executor import remove_mailing_list_aliases
        remove_mailing_list_aliases(address)
    except Exception as exc:
        logger.warning("Failed to remove Exim aliases for list %s: %s", address, exc)

    await db.delete(ml)
    _log(db, request, current_user.id, "mailing_list_delete", f"Deleted mailing list {address}")


# ------------------------------------------------------------------
# Member management
# ------------------------------------------------------------------

@router.post("/lists/{list_id}/members", response_model=list[MemberResponse], status_code=status.HTTP_201_CREATED)
async def add_members(
    list_id: uuid.UUID,
    payload: MemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add one or more members to a mailing list (bulk-capable)."""
    ml = await _get_list_or_404(list_id, db, current_user, load_members=True)

    existing_emails = {m.email.lower() for m in ml.members}
    added: list[MailingListMember] = []

    for email in payload.emails:
        email_lower = email.strip().lower()
        if not email_lower:
            continue
        if email_lower in existing_emails:
            continue  # Skip duplicates silently
        member = MailingListMember(
            list_id=ml.id,
            email=email_lower,
            name=payload.name,
            is_admin=payload.is_admin,
        )
        db.add(member)
        ml.members.append(member)
        existing_emails.add(email_lower)
        added.append(member)

    await db.flush()

    if added:
        _log(
            db, request, current_user.id, "mailing_list_members_add",
            f"Added {len(added)} member(s) to {ml.list_address}",
        )
        _sync_exim_aliases(ml)

    return [MemberResponse.model_validate(m) for m in added]


@router.delete("/lists/{list_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    list_id: uuid.UUID,
    member_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a member from a mailing list."""
    ml = await _get_list_or_404(list_id, db, current_user, load_members=True)

    result = await db.execute(
        select(MailingListMember).where(
            MailingListMember.id == member_id,
            MailingListMember.list_id == ml.id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    email = member.email
    await db.delete(member)
    await db.flush()

    # Refresh members list for alias sync
    ml.members = [m for m in ml.members if m.id != member_id]

    _log(db, request, current_user.id, "mailing_list_member_remove", f"Removed {email} from {ml.list_address}")
    _sync_exim_aliases(ml)


# ------------------------------------------------------------------
# Send message to list
# ------------------------------------------------------------------

@router.post("/lists/{list_id}/send")
async def send_to_list(
    list_id: uuid.UUID,
    payload: ListSendMessage,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message to all list members (admin/owner only)."""
    ml = await _get_list_or_404(list_id, db, current_user, load_members=True)

    # Only list owner or panel admin can send
    is_owner = current_user.email and current_user.email.lower() == ml.owner_email.lower()
    if not _is_admin(current_user) and not is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the list owner or an admin can send messages.")

    if not ml.members:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mailing list has no members.")

    member_emails = [m.email for m in ml.members]

    try:
        from agent.executors.mail_executor import send_list_message
        result = send_list_message(
            list_address=ml.list_address,
            list_name=ml.name,
            owner_email=ml.owner_email,
            recipients=member_emails,
            subject=payload.subject,
            body=payload.body,
            content_type=payload.content_type,
            reply_to_list=ml.reply_to_list,
        )
    except Exception as exc:
        logger.error("Failed to send message to list %s: %s", ml.list_address, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {exc}",
        )

    _log(
        db, request, current_user.id, "mailing_list_send",
        f"Sent message to {ml.list_address} ({len(member_emails)} recipients)",
    )

    return {
        "ok": True,
        "list_address": ml.list_address,
        "recipients": len(member_emails),
        "subject": payload.subject,
    }
