"""Pydantic schemas for antivirus endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScanPathRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024, description="Absolute path to scan")


class ScanResultResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    scan_path: str
    status: str
    files_scanned: int
    infected_count: int
    quarantined_files: Optional[dict] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    celery_task_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuarantineEntryResponse(BaseModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    original_path: str
    quarantine_path: str
    threat_name: str
    file_size: Optional[int] = None
    restored: bool
    deleted: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AntivirusStatusResponse(BaseModel):
    installed: bool = False
    daemon_running: bool = False
    freshclam_running: bool = False
    database_version: Optional[str] = None
    database_last_update: Optional[str] = None
    quarantine_dir: str = "/opt/hosthive/quarantine"
    quarantine_count: int = 0
