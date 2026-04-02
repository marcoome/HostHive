"""Resource limits router -- /api/v1/resources (admin only).

Manages per-user CPU/RAM/IO cgroup limits, disk quotas, process limits,
and per-domain PHP memory limits.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.resources import ResourceLimit
from api.models.users import User
from api.schemas.resources import (
    DomainUsageResponse,
    PHPFPMLimitsResponse,
    PHPFPMLimitsUpdate,
    ResourceOverviewEntry,
    UserLimitsResponse,
    UserLimitsUpdate,
    UserUsageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# --------------------------------------------------------------------------
# GET /users/{username}/usage -- current resource usage
# --------------------------------------------------------------------------


@router.get("/users/{username}/usage", response_model=UserUsageResponse)
async def get_user_usage(
    username: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/resources/user/{username}/usage")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to get usage"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# PUT /users/{username}/limits -- set CPU/RAM/IO limits
# --------------------------------------------------------------------------


@router.put("/users/{username}/limits", response_model=UserLimitsResponse)
async def set_user_limits(
    username: str,
    body: UserLimitsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    # Call agent to apply cgroup limits
    agent = request.app.state.agent
    resp = await agent.post("/resources/user/limits", json={
        "username": username,
        "cpu_percent": body.cpu_percent,
        "memory_mb": body.memory_mb,
        "io_weight": body.io_weight,
    })
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to set limits"))

    # Persist to DB
    result = await db.execute(
        select(ResourceLimit).where(ResourceLimit.user_id == current_user.id)
    )
    limit_row = result.scalar_one_or_none()
    if limit_row:
        limit_row.cpu_percent = body.cpu_percent
        limit_row.memory_mb = body.memory_mb
        limit_row.io_weight = body.io_weight
    else:
        # Look up user by username to get their id
        from api.models.users import User as UserModel
        user_result = await db.execute(
            select(UserModel).where(UserModel.username == username)
        )
        target_user = user_result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(status_code=404, detail=f"User {username} not found")

        db.add(ResourceLimit(
            user_id=target_user.id,
            cpu_percent=body.cpu_percent,
            memory_mb=body.memory_mb,
            io_weight=body.io_weight,
        ))

    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /users/{username}/limits -- get current limits
# --------------------------------------------------------------------------


@router.get("/users/{username}/limits", response_model=UserLimitsResponse)
async def get_user_limits(
    username: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/resources/user/{username}/limits")
    if not resp.get("ok", True):
        raise HTTPException(status_code=404, detail=resp.get("error", "No limits found"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /domains/{domain}/usage -- domain resource usage
# --------------------------------------------------------------------------


@router.get("/domains/{domain}/usage", response_model=DomainUsageResponse)
async def get_domain_usage(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get(f"/resources/domain/{domain}/usage")
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to get usage"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# PUT /domains/{domain}/php-limits -- set PHP-FPM pool limits
# --------------------------------------------------------------------------


@router.put("/domains/{domain}/php-limits", response_model=PHPFPMLimitsResponse)
async def set_domain_php_limits(
    domain: str,
    body: PHPFPMLimitsUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.post("/resources/domain/php-limits", json={
        "domain": domain,
        "max_children": body.max_children,
        "memory_limit": body.memory_limit,
        "php_version": body.php_version,
    })
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to set PHP limits"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# GET /overview -- all users resource usage overview
# --------------------------------------------------------------------------


@router.get("/overview", response_model=list[ResourceOverviewEntry])
async def resource_overview(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    agent = request.app.state.agent
    resp = await agent.get("/resources/overview")
    return resp.get("data", [])


# ==========================================================================
# Disk quotas, process limits, per-domain PHP memory_limit
# ==========================================================================

async def _run(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "Command timed out"
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


# ---------------------------------------------------------------------------
# Schemas for new endpoints
# ---------------------------------------------------------------------------

class DiskQuotaUpdate(BaseModel):
    soft_limit_mb: int = Field(..., ge=0, description="Soft block limit in MB (0 = unlimited)")
    hard_limit_mb: int = Field(..., ge=0, description="Hard block limit in MB (0 = unlimited)")
    soft_inodes: int = Field(default=0, ge=0, description="Soft inode limit (0 = unlimited)")
    hard_inodes: int = Field(default=0, ge=0, description="Hard inode limit (0 = unlimited)")
    filesystem: str = Field(default="/home", description="Filesystem/mount point for quota")


class DiskQuotaResponse(BaseModel):
    username: str
    filesystem: str
    used_mb: float
    soft_limit_mb: int
    hard_limit_mb: int
    used_inodes: int
    soft_inodes: int
    hard_inodes: int
    grace_period: str


class ProcessLimitsUpdate(BaseModel):
    max_processes: int = Field(default=256, ge=16, le=65535, description="Max user processes (nproc)")
    max_open_files: int = Field(default=4096, ge=256, le=1048576, description="Max open files (nofile)")
    max_logins: int = Field(default=10, ge=1, le=1000, description="Max concurrent logins (maxlogins)")


class ProcessLimitsResponse(BaseModel):
    username: str
    max_processes: int
    max_open_files: int
    max_logins: int


class DomainPhpMemoryUpdate(BaseModel):
    memory_limit: str = Field(..., pattern=r"^\d+[MmGg]$", description="PHP memory_limit, e.g. '256M'")
    php_version: str = Field(default="8.2", pattern=r"^\d+\.\d+$")


class DomainPhpMemoryResponse(BaseModel):
    domain: str
    php_version: str
    memory_limit: str
    pool_config_path: str


# ---------------------------------------------------------------------------
# PUT /users/{username}/disk-quota -- set disk quota
# ---------------------------------------------------------------------------

@router.put("/users/{username}/disk-quota", response_model=DiskQuotaResponse)
async def set_disk_quota(
    username: str,
    body: DiskQuotaUpdate,
    current_user: User = Depends(get_current_user),
):
    """Set per-user disk quota using setquota.

    Requires filesystem quotas to be enabled on the target mount point
    (typically via ``usrquota`` in /etc/fstab and ``quotaon``).
    """
    _require_admin(current_user)

    # Sanitise username
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    # Convert MB to 1K blocks (setquota uses 1K-blocks)
    soft_blocks = body.soft_limit_mb * 1024 if body.soft_limit_mb else 0
    hard_blocks = body.hard_limit_mb * 1024 if body.hard_limit_mb else 0

    cmd = (
        f"setquota -u {username} "
        f"{soft_blocks} {hard_blocks} "
        f"{body.soft_inodes} {body.hard_inodes} "
        f"{body.filesystem}"
    )
    rc, out, err = await _run(cmd)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"setquota failed: {err or out}. "
                   "Ensure quotas are enabled (usrquota in /etc/fstab, quotaon).",
        )

    logger.info(
        "Disk quota set for %s: soft=%dMB hard=%dMB on %s by %s",
        username, body.soft_limit_mb, body.hard_limit_mb,
        body.filesystem, current_user.username,
    )

    # Return current quota
    return await _get_disk_quota(username, body.filesystem)


async def _get_disk_quota(username: str, filesystem: str = "/home") -> DiskQuotaResponse:
    """Read current disk quota for a user via ``repquota`` or ``quota``."""
    rc, out, err = await _run(f"quota -u {username} -w 2>/dev/null")
    if rc != 0:
        # Try repquota
        rc2, out2, _ = await _run(f"repquota {filesystem} 2>/dev/null | grep '^{username}'")
        if rc2 != 0 or not out2:
            return DiskQuotaResponse(
                username=username,
                filesystem=filesystem,
                used_mb=0,
                soft_limit_mb=0,
                hard_limit_mb=0,
                used_inodes=0,
                soft_inodes=0,
                hard_inodes=0,
                grace_period="none",
            )
        # Parse repquota line: username -- used soft hard grace used soft hard grace
        parts = out2.split()
        if len(parts) >= 8:
            return DiskQuotaResponse(
                username=username,
                filesystem=filesystem,
                used_mb=round(int(parts[2]) / 1024, 2) if parts[2].isdigit() else 0,
                soft_limit_mb=int(parts[3]) // 1024 if parts[3].isdigit() else 0,
                hard_limit_mb=int(parts[4]) // 1024 if parts[4].isdigit() else 0,
                used_inodes=int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0,
                soft_inodes=int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0,
                hard_inodes=int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else 0,
                grace_period="none",
            )

    # Parse ``quota`` output
    lines = out.strip().split("\n")
    for line in lines:
        parts = line.split()
        if len(parts) >= 7 and filesystem in line:
            return DiskQuotaResponse(
                username=username,
                filesystem=filesystem,
                used_mb=round(int(parts[1]) / 1024, 2) if parts[1].replace("*", "").isdigit() else 0,
                soft_limit_mb=int(parts[2]) // 1024 if parts[2].isdigit() else 0,
                hard_limit_mb=int(parts[3]) // 1024 if parts[3].isdigit() else 0,
                used_inodes=int(parts[4]) if parts[4].replace("*", "").isdigit() else 0,
                soft_inodes=int(parts[5]) if parts[5].isdigit() else 0,
                hard_inodes=int(parts[6]) if parts[6].isdigit() else 0,
                grace_period=parts[7] if len(parts) > 7 else "none",
            )

    return DiskQuotaResponse(
        username=username,
        filesystem=filesystem,
        used_mb=0,
        soft_limit_mb=0,
        hard_limit_mb=0,
        used_inodes=0,
        soft_inodes=0,
        hard_inodes=0,
        grace_period="none",
    )


@router.get("/users/{username}/disk-quota", response_model=DiskQuotaResponse)
async def get_disk_quota(
    username: str,
    filesystem: str = "/home",
    current_user: User = Depends(get_current_user),
):
    """Get current disk quota for a user."""
    _require_admin(current_user)

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    return await _get_disk_quota(username, filesystem)


# ---------------------------------------------------------------------------
# PUT /users/{username}/process-limits -- set process/file limits
# ---------------------------------------------------------------------------

LIMITS_CONF = Path("/etc/security/limits.conf")
LIMITS_D_DIR = Path("/etc/security/limits.d")


def _read_limits_for_user(username: str) -> dict[str, int]:
    """Read current limits.conf entries for a user."""
    current: dict[str, int] = {
        "max_processes": 256,
        "max_open_files": 4096,
        "max_logins": 10,
    }
    # Check per-user file first
    user_limits_file = LIMITS_D_DIR / f"99-hosthive-{username}.conf"
    if user_limits_file.exists():
        content = user_limits_file.read_text(encoding="utf-8")
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4 and parts[0] == username and parts[1] == "hard":
                if parts[2] == "nproc":
                    current["max_processes"] = int(parts[3])
                elif parts[2] == "nofile":
                    current["max_open_files"] = int(parts[3])
                elif parts[2] == "maxlogins":
                    current["max_logins"] = int(parts[3])
    return current


def _write_limits_for_user(username: str, limits: ProcessLimitsUpdate) -> str:
    """Write a per-user limits.d file. Returns the file path."""
    LIMITS_D_DIR.mkdir(parents=True, exist_ok=True)
    user_limits_file = LIMITS_D_DIR / f"99-hosthive-{username}.conf"

    content = f"""# Managed by HostHive -- do not edit manually
# User: {username}
{username}  soft  nproc     {limits.max_processes}
{username}  hard  nproc     {limits.max_processes}
{username}  soft  nofile    {limits.max_open_files}
{username}  hard  nofile    {limits.max_open_files}
{username}  hard  maxlogins {limits.max_logins}
"""
    user_limits_file.write_text(content, encoding="utf-8")
    return str(user_limits_file)


@router.put("/users/{username}/process-limits", response_model=ProcessLimitsResponse)
async def set_process_limits(
    username: str,
    body: ProcessLimitsUpdate,
    current_user: User = Depends(get_current_user),
):
    """Set per-user process limits (nproc, nofile, maxlogins) via limits.d."""
    _require_admin(current_user)

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    try:
        config_path = _write_limits_for_user(username, body)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write limits configuration: {exc}",
        )

    logger.info(
        "Process limits set for %s: nproc=%d nofile=%d maxlogins=%d by %s",
        username, body.max_processes, body.max_open_files, body.max_logins,
        current_user.username,
    )

    return ProcessLimitsResponse(
        username=username,
        max_processes=body.max_processes,
        max_open_files=body.max_open_files,
        max_logins=body.max_logins,
    )


@router.get("/users/{username}/process-limits", response_model=ProcessLimitsResponse)
async def get_process_limits(
    username: str,
    current_user: User = Depends(get_current_user),
):
    """Get current process limits for a user."""
    _require_admin(current_user)

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    limits = _read_limits_for_user(username)
    return ProcessLimitsResponse(
        username=username,
        max_processes=limits["max_processes"],
        max_open_files=limits["max_open_files"],
        max_logins=limits["max_logins"],
    )


# ---------------------------------------------------------------------------
# PUT /domains/{domain}/php-memory -- per-domain PHP memory_limit
# ---------------------------------------------------------------------------

@router.put("/domains/{domain}/php-memory", response_model=DomainPhpMemoryResponse)
async def set_domain_php_memory(
    domain: str,
    body: DomainPhpMemoryUpdate,
    current_user: User = Depends(get_current_user),
):
    """Set PHP memory_limit for a specific domain's PHP-FPM pool.

    This writes a ``php_admin_value[memory_limit]`` directive into the
    pool configuration file for the domain.
    """
    _require_admin(current_user)

    pool_dir = Path(f"/etc/php/{body.php_version}/fpm/pool.d")
    if not pool_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"PHP-FPM pool directory not found for PHP {body.php_version}.",
        )

    # Find the pool config for this domain
    pool_conf = pool_dir / f"{domain}.conf"
    if not pool_conf.exists():
        # Try to find by pattern
        candidates = list(pool_dir.glob(f"*{domain}*"))
        if candidates:
            pool_conf = candidates[0]
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No PHP-FPM pool config found for domain '{domain}'.",
            )

    content = pool_conf.read_text(encoding="utf-8")

    # Update or add memory_limit directive
    directive = f"php_admin_value[memory_limit] = {body.memory_limit}"
    pattern = re.compile(r"^\s*php_admin_value\[memory_limit\]\s*=.*$", re.MULTILINE)

    if pattern.search(content):
        content = pattern.sub(directive, content)
    else:
        # Append before the end of the pool section or at the end
        content = content.rstrip() + f"\n{directive}\n"

    # Create backup
    backup_path = pool_conf.with_suffix(".conf.bak.hosthive")
    backup_path.write_text(pool_conf.read_text(encoding="utf-8"), encoding="utf-8")

    pool_conf.write_text(content, encoding="utf-8")

    # Reload PHP-FPM
    warnings: list[str] = []
    rc, _, err = await _run(f"systemctl reload php{body.php_version}-fpm")
    if rc != 0:
        warnings.append(f"PHP-FPM reload failed: {err}")

    logger.info(
        "PHP memory_limit for domain %s set to %s (PHP %s) by %s",
        domain, body.memory_limit, body.php_version, current_user.username,
    )

    return DomainPhpMemoryResponse(
        domain=domain,
        php_version=body.php_version,
        memory_limit=body.memory_limit,
        pool_config_path=str(pool_conf),
    )
