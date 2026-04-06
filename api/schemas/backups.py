"""Backup schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from api.models.backups import BackupStatus, BackupType


class BackupCreate(BaseModel):
    backup_type: BackupType = BackupType.FULL
    parent_backup_id: Optional[uuid.UUID] = None  # auto-resolved if not set


class BackupSchedule(BaseModel):
    enabled: bool = False
    frequency: str = "daily"  # daily, weekly, monthly
    backup_type: BackupType = BackupType.FULL
    retention_days: int = Field(30, ge=1, le=365, description="Delete backups older than N days")
    retention_count: int = Field(5, ge=1, le=100, description="Keep at most N backups")


class RestoreOptions(BaseModel):
    restore_files: bool = True
    restore_databases: bool = True
    restore_emails: bool = False
    restore_cron: bool = False
    target_path: Optional[str] = None  # custom restore path (overrides /home/{username})


class BackupResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    file_path: Optional[str] = None
    size_bytes: Optional[int] = 0
    created_at: datetime
    backup_type: BackupType = BackupType.FULL
    status: BackupStatus = BackupStatus.PENDING
    error_message: Optional[str] = None
    remote_key: Optional[str] = None
    parent_backup_id: Optional[uuid.UUID] = None
    backup_metadata: Optional[dict] = None

    model_config = {"from_attributes": True}
