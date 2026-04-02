"""Backup schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from api.models.backups import BackupStatus, BackupType


class BackupCreate(BaseModel):
    backup_type: BackupType = BackupType.FULL


class BackupSchedule(BaseModel):
    enabled: bool = False
    frequency: str = "daily"  # daily, weekly, monthly
    retention: int = 7  # keep last N backups
    backup_type: BackupType = BackupType.FULL


class BackupResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    file_path: Optional[str] = None
    size_bytes: Optional[int] = 0
    created_at: datetime
    backup_type: BackupType = BackupType.FULL
    status: BackupStatus = BackupStatus.PENDING
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}
