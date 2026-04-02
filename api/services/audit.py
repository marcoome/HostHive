"""Audit service — explicit activity logging for destructive operations.

This is used by routers and services that want to record an action with
richer detail than the automatic AuditLogMiddleware provides.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.models.activity_log import ActivityLog


async def log_activity(
    db: AsyncSession,
    user_id: Optional[uuid.UUID],
    action: str,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> ActivityLog:
    """Write an audit entry to the activity_log table.

    Parameters
    ----------
    db:
        An active async database session (will NOT be committed — the caller
        or the session-scoped dependency is responsible for committing).
    user_id:
        The UUID of the acting user, or ``None`` for system-initiated actions.
    action:
        Short action label, e.g. ``"domain.create"`` or ``"database.delete"``.
    details:
        Optional free-text description of what was changed.
    ip_address:
        Client IP address (from ``request.client.host``).

    Returns
    -------
    ActivityLog
        The newly created (but not yet committed) log entry.
    """
    entry = ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip_address,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    # We intentionally do NOT commit here — the caller's session-scoped
    # transaction will commit (or rollback) the log together with the
    # business operation, guaranteeing atomicity.
    return entry
