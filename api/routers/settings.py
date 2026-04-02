"""Settings router -- /api/v1/settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from api.core.security import get_current_user
from api.models.users import User

router = APIRouter()


@router.get("/notifications", status_code=status.HTTP_200_OK)
async def get_notification_settings(current_user: User = Depends(get_current_user)):
    """Get notification preferences for the current user."""
    return {
        "email_notifications": True,
        "security_alerts": True,
        "billing_alerts": True,
        "maintenance_alerts": True,
    }


@router.put("/notifications", status_code=status.HTTP_200_OK)
async def update_notification_settings(current_user: User = Depends(get_current_user)):
    """Update notification preferences."""
    return {"detail": "Notification settings updated."}
