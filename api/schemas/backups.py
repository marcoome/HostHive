"""Backup schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from api.models.backups import BackupType


class BackupCreate(BaseModel):
    backup_type: BackupType = BackupType.FULL


class BackupResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    file_path: str
    size_bytes: int
    created_at: datetime
    backup_type: BackupType

    model_config = {"from_attributes": True}
