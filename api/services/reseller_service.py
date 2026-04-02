"""Reseller service -- limit checking, stats, branding."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.databases import Database
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.reseller import ResellerBranding, ResellerLimit
from api.models.users import User, UserRole

logger = logging.getLogger("hosthive.reseller")


class ResellerService:
    """Stateless service for reseller operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Limit checking
    # ------------------------------------------------------------------

    async def get_limits(self, reseller_id: uuid.UUID) -> Optional[ResellerLimit]:
        """Fetch the resource limits for a reseller."""
        result = await self._db.execute(
            select(ResellerLimit).where(ResellerLimit.reseller_id == reseller_id)
        )
        return result.scalar_one_or_none()

    async def check_reseller_limits(
        self,
        reseller_id: uuid.UUID,
        resource_type: str,
    ) -> bool:
        """Return True if the reseller has capacity for the given resource type.

        Supported resource_type values: "users", "disk".
        """
        limits = await self.get_limits(reseller_id)
        if limits is None:
            # No explicit limits configured -- deny by default
            logger.warning("No reseller limits found for reseller %s", reseller_id)
            return False

        if resource_type == "users":
            return limits.used_users < limits.max_users
        if resource_type == "disk":
            return limits.used_disk_mb < limits.max_total_disk_mb
        return False

    async def increment_user_count(self, reseller_id: uuid.UUID) -> None:
        """Increment the used_users counter after creating a sub-user."""
        limits = await self.get_limits(reseller_id)
        if limits is not None:
            limits.used_users += 1
            self._db.add(limits)
            await self._db.flush()

    async def decrement_user_count(self, reseller_id: uuid.UUID) -> None:
        """Decrement the used_users counter after deleting a sub-user."""
        limits = await self.get_limits(reseller_id)
        if limits is not None and limits.used_users > 0:
            limits.used_users -= 1
            self._db.add(limits)
            await self._db.flush()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_reseller_stats(self, reseller_id: uuid.UUID) -> Dict[str, Any]:
        """Aggregate resource usage across all sub-users of a reseller."""
        # Get sub-user IDs
        sub_users_q = select(User).where(
            User.created_by == reseller_id,
            User.role == UserRole.USER,
        )
        sub_users_result = await self._db.execute(sub_users_q)
        sub_users = sub_users_result.scalars().all()
        sub_user_ids = [u.id for u in sub_users]

        total_users = len(sub_users)
        active_users = sum(1 for u in sub_users if u.is_active and not u.is_suspended)
        suspended_users = sum(1 for u in sub_users if u.is_suspended)

        total_domains = 0
        total_databases = 0
        total_email_accounts = 0

        if sub_user_ids:
            total_domains = (await self._db.execute(
                select(func.count()).select_from(Domain)
                .where(Domain.user_id.in_(sub_user_ids))
            )).scalar() or 0

            total_databases = (await self._db.execute(
                select(func.count()).select_from(Database)
                .where(Database.user_id.in_(sub_user_ids))
            )).scalar() or 0

            total_email_accounts = (await self._db.execute(
                select(func.count()).select_from(EmailAccount)
                .where(EmailAccount.user_id.in_(sub_user_ids))
            )).scalar() or 0

        limits = await self.get_limits(reseller_id)

        return {
            "total_users": total_users,
            "active_users": active_users,
            "suspended_users": suspended_users,
            "total_domains": total_domains,
            "total_databases": total_databases,
            "total_email_accounts": total_email_accounts,
            "used_disk_mb": limits.used_disk_mb if limits else 0,
            "max_disk_mb": limits.max_total_disk_mb if limits else 0,
            "used_users": limits.used_users if limits else total_users,
            "max_users": limits.max_users if limits else 0,
            "max_bandwidth_gb": limits.max_total_bandwidth_gb if limits else 0,
        }

    # ------------------------------------------------------------------
    # Branding
    # ------------------------------------------------------------------

    async def get_branding(self, reseller_id: uuid.UUID) -> Optional[ResellerBranding]:
        """Fetch branding config for a reseller."""
        result = await self._db.execute(
            select(ResellerBranding).where(ResellerBranding.user_id == reseller_id)
        )
        return result.scalar_one_or_none()

    async def get_branding_by_domain(self, domain: str) -> Optional[ResellerBranding]:
        """Fetch branding by custom domain (used by middleware)."""
        result = await self._db.execute(
            select(ResellerBranding).where(ResellerBranding.custom_domain == domain)
        )
        return result.scalar_one_or_none()

    async def apply_branding(
        self,
        reseller_id: uuid.UUID,
        data: Dict[str, Any],
    ) -> ResellerBranding:
        """Create or update the branding configuration for a reseller."""
        branding = await self.get_branding(reseller_id)

        if branding is None:
            branding = ResellerBranding(user_id=reseller_id, **data)
        else:
            for key, value in data.items():
                if value is not None:
                    setattr(branding, key, value)

        self._db.add(branding)
        await self._db.flush()
        await self._db.refresh(branding)
        return branding
