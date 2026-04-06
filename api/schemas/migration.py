"""Pydantic schemas for server migration endpoints."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    CPANEL = "cpanel"
    HESTIA = "hestia"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Analysis result returned after scanning a backup
# ---------------------------------------------------------------------------

class MigrationDomainInfo(BaseModel):
    name: str
    document_root: Optional[str] = None
    has_ssl: bool = False


class MigrationDatabaseInfo(BaseModel):
    name: str
    db_type: str = "mysql"  # mysql | postgresql
    has_dump: bool = False
    size_bytes: int = 0


class MigrationEmailInfo(BaseModel):
    address: str
    domain: str
    quota_mb: int = 0


class MigrationDnsZoneInfo(BaseModel):
    domain: str
    record_count: int = 0


class MigrationCronInfo(BaseModel):
    schedule: str
    command: str


class MigrationUserInfo(BaseModel):
    username: str
    email: Optional[str] = None
    domains: list[MigrationDomainInfo] = []
    databases: list[MigrationDatabaseInfo] = []
    emails: list[MigrationEmailInfo] = []
    dns_zones: list[MigrationDnsZoneInfo] = []
    cron_jobs: list[MigrationCronInfo] = []


class MigrationAnalysis(BaseModel):
    backup_id: str
    source_type: SourceType
    source_version: Optional[str] = None
    users: list[MigrationUserInfo] = []
    total_domains: int = 0
    total_databases: int = 0
    total_emails: int = 0
    total_dns_zones: int = 0
    total_cron_jobs: int = 0
    warnings: list[str] = []


# ---------------------------------------------------------------------------
# Execute request
# ---------------------------------------------------------------------------

class MigrationExecuteOptions(BaseModel):
    skip_dns: bool = Field(default=False, description="Skip importing DNS zones")
    skip_mail: bool = Field(default=False, description="Skip importing email accounts")
    skip_databases: bool = Field(default=False, description="Skip importing databases")
    skip_cron: bool = Field(default=False, description="Skip importing cron jobs")
    generate_passwords: bool = Field(
        default=True,
        description="Generate new passwords instead of trying to reuse backup data",
    )


class MigrationExecuteRequest(BaseModel):
    backup_id: str
    options: MigrationExecuteOptions = MigrationExecuteOptions()


# ---------------------------------------------------------------------------
# Status / progress
# ---------------------------------------------------------------------------

class MigrationStep(str, Enum):
    PENDING = "pending"
    CREATING_USERS = "creating_users"
    IMPORTING_DOMAINS = "importing_domains"
    IMPORTING_DATABASES = "importing_databases"
    RESTORING_SQL = "restoring_sql"
    IMPORTING_EMAIL = "importing_email"
    IMPORTING_DNS = "importing_dns"
    IMPORTING_CRON = "importing_cron"
    COPYING_FILES = "copying_files"
    DONE = "done"
    FAILED = "failed"


class MigrationStatus(BaseModel):
    backup_id: str
    progress: float = Field(0.0, ge=0, le=100, description="Percentage 0-100")
    current_step: MigrationStep = MigrationStep.PENDING
    steps_completed: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    created_user_ids: list[str] = []
    created_domain_ids: list[str] = []
    created_database_ids: list[str] = []
    created_email_ids: list[str] = []
