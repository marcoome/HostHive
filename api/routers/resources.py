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
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    # CPU/RAM/IO usage for the user's systemd slice (if any)
    slice_name = f"user-{username}.slice"
    cpu_percent = 0.0
    memory_mb = 0.0

    rc, out, _ = await _run(
        f"systemctl show {slice_name} -p CPUUsageNSec,MemoryCurrent --value"
    )
    if rc == 0 and out:
        lines = out.splitlines()
        try:
            cpu_ns = int(lines[0]) if len(lines) > 0 and lines[0].isdigit() else 0
            mem_bytes = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 0
            # CPUUsageNSec is cumulative — we can't derive percent without sampling,
            # so report as an approximation based on recent process CPU shares.
            cpu_percent = 0.0  # sampling left to monitoring service
            memory_mb = round(mem_bytes / (1024 * 1024), 2)
        except (ValueError, IndexError):
            pass

    return UserUsageResponse(
        username=username,
        cpu={"percent": cpu_percent},
        memory={"used_mb": memory_mb},
        io=[],
        limits=None,
    )


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

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    # Apply cgroup limits via systemd transient overrides on the user's slice.
    slice_name = f"user-{username}.slice"
    cpu_quota = f"{body.cpu_percent}%"
    memory_max = f"{body.memory_mb}M"
    io_weight = max(1, min(10000, body.io_weight))

    cmd = (
        f"systemctl set-property {slice_name} "
        f"CPUQuota={cpu_quota} MemoryMax={memory_max} IOWeight={io_weight}"
    )
    rc, out, err = await _run(cmd)
    if rc != 0:
        logger.warning(
            "systemctl set-property failed for %s: %s",
            slice_name, err or out,
        )
        # Continue — persisting limits to DB is still useful even if the slice
        # doesn't exist yet (e.g. the user hasn't logged in yet).

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

    return UserLimitsResponse(
        username=username,
        cpu_percent=body.cpu_percent,
        memory_mb=body.memory_mb,
        io_weight=body.io_weight,
    )


# --------------------------------------------------------------------------
# GET /users/{username}/limits -- get current limits
# --------------------------------------------------------------------------


@router.get("/users/{username}/limits", response_model=UserLimitsResponse)
async def get_user_limits(
    username: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    # Prefer DB-stored limits; fall back to querying systemd.
    from api.models.users import User as UserModel
    user_res = await db.execute(select(UserModel).where(UserModel.username == username))
    target = user_res.scalar_one_or_none()
    if target is not None:
        lim_res = await db.execute(
            select(ResourceLimit).where(ResourceLimit.user_id == target.id)
        )
        row = lim_res.scalar_one_or_none()
        if row is not None:
            return UserLimitsResponse(
                username=username,
                cpu_percent=row.cpu_percent,
                memory_mb=row.memory_mb,
                io_weight=row.io_weight,
            )

    # Fallback: query systemd for the slice
    slice_name = f"user-{username}.slice"
    rc, out, _ = await _run(
        f"systemctl show {slice_name} -p CPUQuotaPerSecUSec,MemoryMax,IOWeight --value"
    )
    cpu_percent = 100
    memory_mb = 1024
    io_weight = 100
    if rc == 0 and out:
        lines = out.splitlines()
        # Parse MemoryMax (bytes) and IOWeight
        if len(lines) >= 2 and lines[1].isdigit():
            memory_mb = max(32, int(lines[1]) // (1024 * 1024))
        if len(lines) >= 3 and lines[2].isdigit():
            io_weight = int(lines[2])

    return UserLimitsResponse(
        username=username,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
        io_weight=io_weight,
    )


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

    if not re.match(r"^[a-zA-Z0-9._-]+$", domain) or ".." in domain:
        raise HTTPException(status_code=400, detail="Invalid domain format.")

    # Find PHP-FPM processes for the domain's pool and sum their RSS.
    rc, out, _ = await _run(
        f"pgrep -af 'php-fpm.*{re.escape(domain)}'"
    )
    pids: list[str] = []
    if rc == 0 and out:
        for line in out.splitlines():
            parts = line.split(None, 1)
            if parts and parts[0].isdigit():
                pids.append(parts[0])

    memory_kb = 0
    if pids:
        rc2, out2, _ = await _run(
            f"ps -o rss= -p {','.join(pids)}"
        )
        if rc2 == 0:
            for line in out2.splitlines():
                line = line.strip()
                if line.isdigit():
                    memory_kb += int(line)

    return DomainUsageResponse(
        domain=domain,
        process_count=len(pids),
        pids=pids,
        memory_kb=memory_kb,
        memory_mb=round(memory_kb / 1024, 2),
    )


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

    if not re.match(r"^[a-zA-Z0-9._-]+$", domain) or ".." in domain:
        raise HTTPException(status_code=400, detail="Invalid domain format.")

    pool_dir = Path(f"/etc/php/{body.php_version}/fpm/pool.d")
    if not pool_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"PHP-FPM pool directory not found for PHP {body.php_version}.",
        )

    pool_conf = pool_dir / f"{domain}.conf"
    if not pool_conf.exists():
        candidates = list(pool_dir.glob(f"*{domain}*"))
        if candidates:
            pool_conf = candidates[0]
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No PHP-FPM pool config found for domain '{domain}'.",
            )

    content = pool_conf.read_text(encoding="utf-8")

    # Update pm.max_children
    mc_pat = re.compile(r"^\s*pm\.max_children\s*=.*$", re.MULTILINE)
    mc_line = f"pm.max_children = {body.max_children}"
    if mc_pat.search(content):
        content = mc_pat.sub(mc_line, content)
    else:
        content = content.rstrip() + f"\n{mc_line}\n"

    # Update memory_limit
    ml_pat = re.compile(r"^\s*php_admin_value\[memory_limit\]\s*=.*$", re.MULTILINE)
    ml_line = f"php_admin_value[memory_limit] = {body.memory_limit}"
    if ml_pat.search(content):
        content = ml_pat.sub(ml_line, content)
    else:
        content = content.rstrip() + f"\n{ml_line}\n"

    pool_conf.write_text(content, encoding="utf-8")

    # Reload PHP-FPM
    await _run(f"systemctl reload php{body.php_version}-fpm")

    # Derive pool name from first [pool] section in the file
    pool_name_match = re.search(r"^\[([^\]]+)\]", content, re.MULTILINE)
    pool_name = pool_name_match.group(1) if pool_name_match else domain

    return PHPFPMLimitsResponse(
        domain=domain,
        php_version=body.php_version,
        pool_name=pool_name,
        max_children=body.max_children,
        memory_limit=body.memory_limit,
        config_path=str(pool_conf),
    )


# --------------------------------------------------------------------------
# GET /overview -- all users resource usage overview
# --------------------------------------------------------------------------


@router.get("/overview", response_model=list[ResourceOverviewEntry])
async def resource_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    # Return DB-stored per-user limits (default when no row exists).
    from api.models.users import User as UserModel
    result = await db.execute(
        select(UserModel.username, ResourceLimit)
        .join(ResourceLimit, ResourceLimit.user_id == UserModel.id, isouter=True)
    )
    entries: list[ResourceOverviewEntry] = []
    for username, limit in result.all():
        if limit is None:
            entries.append(ResourceOverviewEntry(username=username))
        else:
            entries.append(
                ResourceOverviewEntry(
                    username=username,
                    cpu_percent=limit.cpu_percent,
                    memory_mb=limit.memory_mb,
                    io_weight=limit.io_weight,
                )
            )
    return entries


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
