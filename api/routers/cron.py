"""Cron jobs router -- /api/v1/cron.

Includes predefined common tasks, cron expression builder/validator,
and execution logging.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.cron_jobs import CronJob
from api.models.users import User
from api.schemas.cron import CronJobCreate, CronJobResponse, CronJobUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_cron_or_404(
    cron_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> CronJob:
    result = await db.execute(select(CronJob).where(CronJob.id == cron_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cron job not found.")
    if not _is_admin(current_user) and job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return job


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# Direct crontab management (no agent)
# --------------------------------------------------------------------------

def _direct_list_crontab(username: str) -> list[str]:
    """List the current crontab entries for a system user."""
    result = subprocess.run(
        ["crontab", "-l", "-u", username],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        # crontab returns non-zero when no crontab exists
        return []
    return [line for line in result.stdout.splitlines() if line.strip() and not line.startswith("#")]


def _direct_write_crontab(username: str, entries: list[dict[str, str]]) -> None:
    """Write a full crontab for a system user from a list of {schedule, command} dicts."""
    header = "# Managed by HostHive -- do not edit manually\n"
    lines = [header]
    for entry in entries:
        lines.append(f"{entry['schedule']} {entry['command']}\n")

    crontab_content = "".join(lines)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".crontab", delete=False) as tmp:
        tmp.write(crontab_content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["crontab", "-u", username, tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"crontab install failed: {result.stderr.strip()}")
    finally:
        import os
        os.unlink(tmp_path)


def _direct_clear_crontab(username: str) -> None:
    """Remove all cron jobs for a system user."""
    subprocess.run(
        ["crontab", "-r", "-u", username],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _direct_run_command(username: str, command: str) -> str:
    """Execute a command immediately as the given user."""
    result = subprocess.run(
        ["sudo", "-u", username, "bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout
    if result.returncode != 0:
        output += f"\nSTDERR: {result.stderr}" if result.stderr else ""
        output += f"\nExit code: {result.returncode}"
    return output


async def _sync_crontab(
    db: AsyncSession,
    user: User,
    agent,
):
    """Push the full crontab for a user. Tries agent first, falls back to direct."""
    jobs = (await db.execute(
        select(CronJob).where(CronJob.user_id == user.id, CronJob.is_active.is_(True))
    )).scalars().all()

    entries = [
        {"schedule": j.schedule, "command": j.command}
        for j in jobs
    ]

    # Try agent first
    try:
        await agent.set_crontab(user.username, entries)
        return
    except Exception as exc:
        logger.warning("Agent error syncing crontab, falling back to direct: %s", exc)

    # Direct fallback
    loop = asyncio.get_running_loop()
    if entries:
        await loop.run_in_executor(None, _direct_write_crontab, user.username, entries)
    else:
        await loop.run_in_executor(None, _direct_clear_crontab, user.username)


# --------------------------------------------------------------------------
# GET / -- list cron jobs
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_cron_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(CronJob)
    count_query = select(func.count()).select_from(CronJob)
    if not _is_admin(current_user):
        query = query.where(CronJob.user_id == current_user.id)
        count_query = count_query.where(CronJob.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    return {
        "items": [CronJobResponse.model_validate(j) for j in results],
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create cron job
# --------------------------------------------------------------------------
@router.post("", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_cron_job(
    body: CronJobCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = CronJob(
        user_id=current_user.id,
        schedule=body.schedule,
        command=body.command,
    )
    db.add(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception as exc:
        # Non-fatal: job is saved in DB; agent sync will be retried on next change.
        logger.warning("Agent error syncing crontab after create: %s", exc)

    _log(db, request, current_user.id, "cron.create", f"Created cron job: {body.schedule} {body.command[:80]}")
    return CronJobResponse.model_validate(job)


# --------------------------------------------------------------------------
# GET /{id} -- cron job detail
# --------------------------------------------------------------------------
@router.get("/{cron_id}", response_model=CronJobResponse, status_code=status.HTTP_200_OK)
async def get_cron_job(
    cron_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CronJobResponse.model_validate(await _get_cron_or_404(cron_id, db, current_user))


# --------------------------------------------------------------------------
# PUT /{id} -- update cron job
# --------------------------------------------------------------------------
@router.put("/{cron_id}", response_model=CronJobResponse, status_code=status.HTTP_200_OK)
async def update_cron_job(
    cron_id: uuid.UUID,
    body: CronJobUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await _get_cron_or_404(cron_id, db, current_user)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)
    db.add(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception:
        pass  # non-fatal; DB is source of truth

    _log(db, request, current_user.id, "cron.update", f"Updated cron job {cron_id}")
    return CronJobResponse.model_validate(job)


# --------------------------------------------------------------------------
# DELETE /{id} -- delete cron job
# --------------------------------------------------------------------------
@router.delete("/{cron_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cron_job(
    cron_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await _get_cron_or_404(cron_id, db, current_user)

    _log(db, request, current_user.id, "cron.delete", f"Deleted cron job {cron_id}")
    await db.delete(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception:
        pass


# --------------------------------------------------------------------------
# POST /{id}/run-now -- immediate execution
# --------------------------------------------------------------------------
@router.post("/{cron_id}/run-now", status_code=status.HTTP_200_OK)
async def run_cron_now(
    cron_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await _get_cron_or_404(cron_id, db, current_user)

    # Try agent first, fall back to direct execution
    result = None
    agent = request.app.state.agent
    try:
        result = await agent._request(
            "POST",
            "/cron/run",
            json_body={"username": current_user.username, "command": job.command},
        )
    except Exception as exc:
        logger.warning("Agent error running cron job, falling back to direct: %s", exc)

    if result is None:
        try:
            loop = asyncio.get_running_loop()
            output = await loop.run_in_executor(
                None, _direct_run_command, current_user.username, job.command,
            )
            result = {"output": output}
        except Exception as exc:
            logger.error("Direct cron execution also failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to run cron job: {exc}",
            )

    # Update last_run timestamp
    job.last_run = datetime.now(timezone.utc)
    db.add(job)
    await db.flush()

    _log(db, request, current_user.id, "cron.run_now", f"Manually ran cron job {cron_id}")
    return {"detail": "Job execution triggered.", "result": result}


# ==========================================================================
# Predefined tasks, cron expression builder/validator, execution logs
# ==========================================================================

# ---------------------------------------------------------------------------
# Schemas for new endpoints
# ---------------------------------------------------------------------------

class CronExpressionParts(BaseModel):
    minute: str = Field(default="*", description="Minute (0-59, */N, or *)")
    hour: str = Field(default="*", description="Hour (0-23, */N, or *)")
    day_of_month: str = Field(default="*", description="Day of month (1-31, */N, or *)")
    month: str = Field(default="*", description="Month (1-12, */N, or *)")
    day_of_week: str = Field(default="*", description="Day of week (0-7 where 0,7=Sun, */N, or *)")


class CronBuildRequest(BaseModel):
    parts: Optional[CronExpressionParts] = None
    preset: Optional[str] = Field(
        default=None,
        description="Named preset: every_minute, every_5_minutes, every_15_minutes, "
                    "every_30_minutes, hourly, daily, daily_3am, weekly, monthly",
    )


class CronValidateRequest(BaseModel):
    expression: str = Field(..., min_length=5, max_length=128)


class PredefinedTaskCreate(BaseModel):
    task_type: str = Field(
        ...,
        description="One of: backup_daily, backup_weekly, logrotate, cache_clear, "
                    "ssl_renew, db_optimize, disk_usage_report",
    )
    custom_params: dict = Field(
        default_factory=dict,
        description="Optional overrides (e.g. backup_path, domain).",
    )


# ---------------------------------------------------------------------------
# Cron expression presets
# ---------------------------------------------------------------------------

_CRON_PRESETS: dict[str, str] = {
    "every_minute": "* * * * *",
    "every_5_minutes": "*/5 * * * *",
    "every_15_minutes": "*/15 * * * *",
    "every_30_minutes": "*/30 * * * *",
    "hourly": "0 * * * *",
    "daily": "0 0 * * *",
    "daily_3am": "0 3 * * *",
    "weekly": "0 0 * * 0",
    "monthly": "0 0 1 * *",
}

# ---------------------------------------------------------------------------
# Predefined tasks
# ---------------------------------------------------------------------------

_PREDEFINED_TASKS: dict[str, dict] = {
    "backup_daily": {
        "schedule": "0 2 * * *",
        "command_template": "tar -czf /home/{username}/backups/daily-$(date +\\%Y\\%m\\%d).tar.gz /home/{username}/web/ 2>/dev/null",
        "description": "Daily backup of all web files at 2:00 AM",
    },
    "backup_weekly": {
        "schedule": "0 3 * * 0",
        "command_template": "tar -czf /home/{username}/backups/weekly-$(date +\\%Y\\%m\\%d).tar.gz /home/{username}/web/ 2>/dev/null",
        "description": "Weekly backup of all web files (Sunday 3:00 AM)",
    },
    "logrotate": {
        "schedule": "0 0 * * *",
        "command_template": "find /home/{username}/web/*/logs -name '*.log' -size +100M -exec truncate -s 0 {{}} \\;",
        "description": "Daily log rotation -- truncate logs over 100MB",
    },
    "cache_clear": {
        "schedule": "0 */6 * * *",
        "command_template": "find /home/{username}/web/*/public_html -path '*/cache/*' -type f -mtime +7 -delete 2>/dev/null",
        "description": "Clear cache files older than 7 days (every 6 hours)",
    },
    "ssl_renew": {
        "schedule": "0 4 * * 1",
        "command_template": "certbot renew --quiet --deploy-hook 'systemctl reload nginx'",
        "description": "Weekly SSL certificate renewal check (Monday 4:00 AM)",
    },
    "db_optimize": {
        "schedule": "0 5 * * 0",
        "command_template": "mysqlcheck --optimize --all-databases 2>/dev/null || true",
        "description": "Weekly MySQL database optimization (Sunday 5:00 AM)",
    },
    "disk_usage_report": {
        "schedule": "0 6 * * 1",
        "command_template": "du -sh /home/{username}/web/*/ > /home/{username}/disk_report.txt 2>/dev/null",
        "description": "Weekly disk usage report (Monday 6:00 AM)",
    },
}

# Execution log directory
CRON_LOG_DIR = Path("/var/log/hosthive/cron")


# ---------------------------------------------------------------------------
# Cron expression validator
# ---------------------------------------------------------------------------

def _validate_cron_field(value: str, min_val: int, max_val: int, field_name: str) -> bool:
    """Validate a single cron expression field."""
    if value == "*":
        return True

    # Handle */N (step)
    if value.startswith("*/"):
        step = value[2:]
        return step.isdigit() and 1 <= int(step) <= max_val

    # Handle ranges: N-M
    if "-" in value and "," not in value:
        parts = value.split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return min_val <= int(parts[0]) <= max_val and min_val <= int(parts[1]) <= max_val

    # Handle lists: N,M,O
    if "," in value:
        for part in value.split(","):
            part = part.strip()
            if not part.isdigit():
                return False
            if not (min_val <= int(part) <= max_val):
                return False
        return True

    # Handle range with step: N-M/S
    if "/" in value:
        range_part, step = value.split("/", 1)
        if not step.isdigit():
            return False
        if range_part == "*":
            return True
        if "-" in range_part:
            parts = range_part.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return min_val <= int(parts[0]) <= max_val and min_val <= int(parts[1]) <= max_val
        return False

    # Simple number
    if value.isdigit():
        return min_val <= int(value) <= max_val

    return False


def _validate_cron_expression(expr: str) -> tuple[bool, str]:
    """Validate a full 5-field cron expression. Returns (valid, message)."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False, f"Expected 5 fields, got {len(parts)}."

    field_specs = [
        ("minute", 0, 59),
        ("hour", 0, 23),
        ("day of month", 1, 31),
        ("month", 1, 12),
        ("day of week", 0, 7),
    ]

    for i, (name, min_v, max_v) in enumerate(field_specs):
        if not _validate_cron_field(parts[i], min_v, max_v, name):
            return False, f"Invalid {name} field: '{parts[i]}'."

    return True, "Valid cron expression."


def _describe_cron(expr: str) -> str:
    """Generate a human-readable description of a cron expression."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return "Invalid expression"

    minute, hour, dom, month, dow = parts

    descriptions = []

    # Special common patterns
    if expr == "* * * * *":
        return "Every minute"
    if minute.startswith("*/"):
        return f"Every {minute[2:]} minutes"
    if expr == "0 * * * *":
        return "Every hour (at minute 0)"
    if expr == "0 0 * * *":
        return "Daily at midnight"
    if expr == "0 0 * * 0":
        return "Every Sunday at midnight"
    if expr == "0 0 1 * *":
        return "First day of every month at midnight"

    if minute != "*":
        descriptions.append(f"at minute {minute}")
    if hour != "*":
        descriptions.append(f"at hour {hour}")
    if dom != "*":
        descriptions.append(f"on day {dom} of month")
    if month != "*":
        descriptions.append(f"in month {month}")
    if dow != "*":
        day_names = {
            "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
            "4": "Thursday", "5": "Friday", "6": "Saturday", "7": "Sunday",
        }
        dow_desc = day_names.get(dow, f"day {dow}")
        descriptions.append(f"on {dow_desc}")

    return ", ".join(descriptions) if descriptions else "Custom schedule"


# ---------------------------------------------------------------------------
# POST /validate -- validate cron expression
# ---------------------------------------------------------------------------

@router.post("/validate")
async def validate_cron_expression(
    body: CronValidateRequest,
    current_user: User = Depends(get_current_user),
):
    """Validate a cron expression and return a human-readable description."""
    valid, message = _validate_cron_expression(body.expression)
    description = _describe_cron(body.expression) if valid else None

    return {
        "expression": body.expression,
        "valid": valid,
        "message": message,
        "description": description,
    }


# ---------------------------------------------------------------------------
# POST /build -- build cron expression from parts or preset
# ---------------------------------------------------------------------------

@router.post("/build")
async def build_cron_expression(
    body: CronBuildRequest,
    current_user: User = Depends(get_current_user),
):
    """Build a cron expression from individual parts or a named preset."""
    if body.preset:
        preset_lower = body.preset.lower().replace(" ", "_")
        if preset_lower not in _CRON_PRESETS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown preset '{body.preset}'. "
                       f"Available: {', '.join(sorted(_CRON_PRESETS.keys()))}",
            )
        expression = _CRON_PRESETS[preset_lower]
    elif body.parts:
        expression = (
            f"{body.parts.minute} {body.parts.hour} "
            f"{body.parts.day_of_month} {body.parts.month} "
            f"{body.parts.day_of_week}"
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'preset' or 'parts'.",
        )

    valid, message = _validate_cron_expression(expression)
    description = _describe_cron(expression) if valid else None

    return {
        "expression": expression,
        "valid": valid,
        "message": message,
        "description": description,
        "presets_available": list(_CRON_PRESETS.keys()),
    }


# ---------------------------------------------------------------------------
# GET /presets -- list available presets
# ---------------------------------------------------------------------------

@router.get("/presets")
async def list_cron_presets(
    current_user: User = Depends(get_current_user),
):
    """List all available cron schedule presets."""
    return {
        "presets": {
            name: {
                "expression": expr,
                "description": _describe_cron(expr),
            }
            for name, expr in _CRON_PRESETS.items()
        }
    }


# ---------------------------------------------------------------------------
# GET /predefined-tasks -- list predefined task templates
# ---------------------------------------------------------------------------

@router.get("/predefined-tasks")
async def list_predefined_tasks(
    current_user: User = Depends(get_current_user),
):
    """List all predefined common task templates."""
    return {
        "tasks": {
            name: {
                "schedule": task["schedule"],
                "description": task["description"],
                "schedule_description": _describe_cron(task["schedule"]),
            }
            for name, task in _PREDEFINED_TASKS.items()
        }
    }


# ---------------------------------------------------------------------------
# POST /predefined-tasks -- create cron job from predefined template
# ---------------------------------------------------------------------------

@router.post("/predefined-tasks", response_model=CronJobResponse, status_code=status.HTTP_201_CREATED)
async def create_predefined_task(
    body: PredefinedTaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a cron job from a predefined task template."""
    if body.task_type not in _PREDEFINED_TASKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task type '{body.task_type}'. "
                   f"Available: {', '.join(sorted(_PREDEFINED_TASKS.keys()))}",
        )

    template = _PREDEFINED_TASKS[body.task_type]
    command = template["command_template"].format(
        username=current_user.username,
        **body.custom_params,
    )
    schedule = body.custom_params.get("schedule", template["schedule"])

    # Ensure backup directory exists for backup tasks
    if "backup" in body.task_type:
        backup_dir = Path(f"/home/{current_user.username}/backups")
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    job = CronJob(
        user_id=current_user.id,
        schedule=schedule,
        command=command,
    )
    db.add(job)
    await db.flush()

    agent = request.app.state.agent
    try:
        await _sync_crontab(db, current_user, agent)
    except Exception as exc:
        logger.warning("Agent error syncing crontab after predefined task create: %s", exc)

    _log(
        db, request, current_user.id, "cron.create_predefined",
        f"Created predefined task '{body.task_type}': {schedule} {command[:80]}",
    )
    return CronJobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# GET /{id}/logs -- last N execution logs
# ---------------------------------------------------------------------------

@router.get("/{cron_id}/logs")
async def get_cron_logs(
    cron_id: uuid.UUID,
    lines: int = Query(default=50, ge=1, le=500, description="Number of log lines to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the last N execution log entries for a cron job.

    Logs are stored at /var/log/hosthive/cron/{job_id}.log and also
    fetched from the system journal.
    """
    job = await _get_cron_or_404(cron_id, db, current_user)

    logs: list[dict] = []

    # 1. Check dedicated log file
    log_file = CRON_LOG_DIR / f"{cron_id}.log"
    if log_file.exists():
        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
            log_lines = content.strip().split("\n")
            # Take last N lines
            recent = log_lines[-lines:] if len(log_lines) > lines else log_lines
            for entry in recent:
                logs.append({"source": "hosthive", "line": entry})
        except Exception as exc:
            logger.warning("Could not read cron log %s: %s", log_file, exc)

    # 2. Check syslog / journal for cron entries by this user
    result = subprocess.run(
        [
            "journalctl", "-u", "cron",
            "--no-pager", "-n", str(lines),
            "--output", "short-iso",
            "-g", current_user.username,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and job.command[:30] in line:
                logs.append({"source": "journal", "line": line})

    # 3. Also check the activity log from DB
    result_db = await db.execute(
        select(ActivityLog)
        .where(
            ActivityLog.user_id == current_user.id,
            ActivityLog.action.in_(["cron.run_now", "cron.create", "cron.update", "cron.delete"]),
            ActivityLog.details.contains(str(cron_id)),
        )
        .order_by(ActivityLog.id.desc())
        .limit(lines)
    )
    activity_entries = result_db.scalars().all()
    for entry in activity_entries:
        logs.append({
            "source": "activity_log",
            "action": entry.action,
            "details": entry.details,
            "ip": entry.ip_address,
        })

    return {
        "cron_id": str(cron_id),
        "job_schedule": job.schedule,
        "job_command": job.command,
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "total_entries": len(logs),
        "logs": logs[-lines:],
    }
