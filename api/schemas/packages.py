"""Package schemas."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from api.models.packages import PackageType


class PackageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    package_type: PackageType = Field(
        default=PackageType.USER,
        description="'user' = regular hosting plan; 'reseller' = wholesale allocation",
    )
    disk_quota_mb: int = Field(default=5120, ge=100)
    bandwidth_gb: int = Field(default=100, ge=1)
    max_domains: int = Field(default=5, ge=1)
    max_databases: int = Field(default=5, ge=0)
    max_email_accounts: int = Field(default=20, ge=0)
    max_ftp_accounts: int = Field(default=5, ge=0)
    max_cron_jobs: int = Field(default=5, ge=0)
    max_dns_domains: int = Field(default=10, ge=0)
    max_mail_domains: int = Field(default=10, ge=0)
    max_backups: int = Field(default=5, ge=0)
    price_monthly: Decimal = Field(default=Decimal("0.00"), ge=0)
    # Docker isolation resource limits
    cpu_cores: float = Field(default=1.0, gt=0, le=32)
    ram_mb: int = Field(default=1024, ge=128, le=65536)
    io_bandwidth_mbps: int = Field(default=100, ge=1, le=10000)
    iops_limit: int = Field(default=1000, ge=100)
    inodes_limit: int = Field(default=500000, ge=10000)
    nproc_limit: int = Field(default=100, ge=10)
    default_webserver: str = Field(default="nginx", description="nginx, apache, openlitespeed, caddy, varnish")
    default_db_version: str = Field(default="mariadb11", description="mysql8, mysql9, mariadb11, percona8")
    redis_enabled: bool = False
    redis_memory_mb: int = Field(default=64, ge=16, le=2048)
    memcached_enabled: bool = False
    memcached_memory_mb: int = Field(default=64, ge=16, le=2048)
    # Shell access
    shell_access: bool = False
    shell_type: str = Field(default="nologin", description="nologin, bash, sh, rbash")

    # --------------------------------------------------------------
    # Reseller-package allocation fields. Required (and validated)
    # only when package_type == "reseller".
    # --------------------------------------------------------------
    max_users: int = Field(default=0, ge=0, description="Reseller-pkg only: max sub-users")
    max_total_disk_gb: int = Field(default=0, ge=0, description="Reseller-pkg only: aggregate disk in GB")
    max_total_bandwidth_gb: int = Field(default=0, ge=0, description="Reseller-pkg only: aggregate bandwidth in GB")
    max_total_domains: int = Field(default=0, ge=0, description="Reseller-pkg only: aggregate domains")

    @model_validator(mode="after")
    def _validate_type_constraints(self) -> "PackageCreate":
        if self.package_type == PackageType.RESELLER:
            if self.max_users <= 0:
                raise ValueError("Reseller package requires max_users > 0")
            if self.max_total_disk_gb <= 0:
                raise ValueError("Reseller package requires max_total_disk_gb > 0")
            if self.max_total_bandwidth_gb <= 0:
                raise ValueError("Reseller package requires max_total_bandwidth_gb > 0")
            if self.max_total_domains <= 0:
                raise ValueError("Reseller package requires max_total_domains > 0")
        return self


class PackageUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    # package_type is intentionally NOT updatable -- changing the type would
    # silently invalidate every user already assigned to it.
    disk_quota_mb: Optional[int] = Field(default=None, ge=100)
    bandwidth_gb: Optional[int] = Field(default=None, ge=1)
    max_domains: Optional[int] = Field(default=None, ge=1)
    max_databases: Optional[int] = Field(default=None, ge=0)
    max_email_accounts: Optional[int] = Field(default=None, ge=0)
    max_ftp_accounts: Optional[int] = Field(default=None, ge=0)
    max_cron_jobs: Optional[int] = Field(default=None, ge=0)
    max_dns_domains: Optional[int] = Field(default=None, ge=0)
    max_mail_domains: Optional[int] = Field(default=None, ge=0)
    max_backups: Optional[int] = Field(default=None, ge=0)
    price_monthly: Optional[Decimal] = Field(default=None, ge=0)
    # Docker isolation resource limits
    cpu_cores: Optional[float] = Field(default=None, gt=0, le=32)
    ram_mb: Optional[int] = Field(default=None, ge=128, le=65536)
    io_bandwidth_mbps: Optional[int] = Field(default=None, ge=1, le=10000)
    iops_limit: Optional[int] = Field(default=None, ge=100)
    inodes_limit: Optional[int] = Field(default=None, ge=10000)
    nproc_limit: Optional[int] = Field(default=None, ge=10)
    default_webserver: Optional[str] = Field(default=None)
    default_db_version: Optional[str] = Field(default=None)
    redis_enabled: Optional[bool] = None
    redis_memory_mb: Optional[int] = Field(default=None, ge=16, le=2048)
    memcached_enabled: Optional[bool] = None
    memcached_memory_mb: Optional[int] = Field(default=None, ge=16, le=2048)
    # Shell access
    shell_access: Optional[bool] = None
    shell_type: Optional[str] = Field(default=None, description="nologin, bash, sh, rbash")
    # Reseller-package allocation overrides (only used when the underlying
    # package_type is "reseller" -- silently ignored for "user" packages).
    max_users: Optional[int] = Field(default=None, ge=0)
    max_total_disk_gb: Optional[int] = Field(default=None, ge=0)
    max_total_bandwidth_gb: Optional[int] = Field(default=None, ge=0)
    max_total_domains: Optional[int] = Field(default=None, ge=0)


class PackageResponse(BaseModel):
    id: uuid.UUID
    name: str
    package_type: PackageType
    disk_quota_mb: int
    bandwidth_gb: int
    max_domains: int
    max_databases: int
    max_email_accounts: int
    max_ftp_accounts: int
    max_cron_jobs: int
    max_dns_domains: int
    max_mail_domains: int
    max_backups: int
    price_monthly: Decimal
    # Docker isolation resource limits
    cpu_cores: float
    ram_mb: int
    io_bandwidth_mbps: int
    iops_limit: int
    inodes_limit: int
    nproc_limit: int
    default_webserver: str
    default_db_version: str
    redis_enabled: bool
    redis_memory_mb: int
    memcached_enabled: bool
    memcached_memory_mb: int
    # Shell access
    shell_access: bool
    shell_type: str
    # Ownership
    created_by: Optional[uuid.UUID] = None
    # Reseller-package allocation (zero for user-type packages)
    max_users: int = 0
    max_total_disk_gb: int = 0
    max_total_bandwidth_gb: int = 0
    max_total_domains: int = 0

    model_config = {"from_attributes": True}


class PackageListResponse(BaseModel):
    items: List[PackageResponse]
    total: int
