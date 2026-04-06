"""Celery tasks for server migration (cPanel / HestiaCP backup import)."""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

from celery import shared_task

from api.schemas.migration import MigrationStep, SourceType

logger = logging.getLogger("hosthive.migration.tasks")

_UPLOAD_DIR = Path("/opt/hosthive/tmp/migrations")


def _redis():
    """Get a synchronous Redis connection for progress tracking."""
    from api.core.config import settings
    import redis
    return redis.Redis.from_url(settings.REDIS_URL.replace("+asyncpg", ""), decode_responses=True)


def _status_key(backup_id: str) -> str:
    return f"hosthive:migration:{backup_id}"


def _update_status(
    backup_id: str,
    *,
    progress: float | None = None,
    step: MigrationStep | None = None,
    error: str | None = None,
    warning: str | None = None,
    completed_step: str | None = None,
    created_user_id: str | None = None,
    created_domain_id: str | None = None,
    created_database_id: str | None = None,
    created_email_id: str | None = None,
) -> None:
    """Push a status update to Redis."""
    r = _redis()
    key = _status_key(backup_id)
    raw = r.get(key)
    data: dict[str, Any] = json.loads(raw) if raw else {
        "backup_id": backup_id,
        "progress": 0.0,
        "current_step": MigrationStep.PENDING.value,
        "steps_completed": [],
        "errors": [],
        "warnings": [],
        "created_user_ids": [],
        "created_domain_ids": [],
        "created_database_ids": [],
        "created_email_ids": [],
    }
    if progress is not None:
        data["progress"] = progress
    if step is not None:
        data["current_step"] = step.value
    if error:
        data["errors"].append(error)
    if warning:
        data["warnings"].append(warning)
    if completed_step:
        data["steps_completed"].append(completed_step)
    if created_user_id:
        data["created_user_ids"].append(created_user_id)
    if created_domain_id:
        data["created_domain_ids"].append(created_domain_id)
    if created_database_id:
        data["created_database_ids"].append(created_database_id)
    if created_email_id:
        data["created_email_ids"].append(created_email_id)

    r.set(key, json.dumps(data), ex=86400)  # expire after 24h


@shared_task(name="api.tasks.migration_tasks.execute_migration", bind=True, max_retries=0)
def execute_migration(
    self,
    backup_id: str,
    analysis_json: str,
    options_json: str,
) -> dict[str, Any]:
    """Execute the full migration in a Celery worker.

    This runs synchronously inside the worker process, creating users,
    domains, databases, email accounts, and optionally restoring SQL dumps.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from api.core.config import settings
    from api.core.encryption import encrypt_value
    from api.core.security import hash_password
    from api.models.databases import Database, DbType
    from api.models.domains import Domain
    from api.models.email_accounts import EmailAccount
    from api.models.users import User, UserRole
    from api.schemas.migration import (
        MigrationAnalysis,
        MigrationExecuteOptions,
    )

    analysis = MigrationAnalysis.model_validate_json(analysis_json)
    options = MigrationExecuteOptions.model_validate_json(options_json)

    # Build a sync database URL from the async one
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    extract_dir = _UPLOAD_DIR / backup_id / "extracted"

    # Determine the migrator to use for file access
    from api.services.migration_service import detect_backup_type
    try:
        migrator = detect_backup_type(extract_dir)
    except ValueError as e:
        _update_status(backup_id, step=MigrationStep.FAILED, error=str(e), progress=100)
        return {"success": False, "error": str(e)}

    total_steps = 0
    if analysis.users:
        total_steps += 1  # create users
    if analysis.total_domains:
        total_steps += 1
    if analysis.total_databases and not options.skip_databases:
        total_steps += 2  # create DB records + restore SQL
    if analysis.total_emails and not options.skip_mail:
        total_steps += 1
    if analysis.total_dns_zones and not options.skip_dns:
        total_steps += 1
    if analysis.total_cron_jobs and not options.skip_cron:
        total_steps += 1
    total_steps = max(total_steps, 1)
    completed = 0

    def advance(step_name: str) -> None:
        nonlocal completed
        completed += 1
        pct = min(round((completed / total_steps) * 100, 1), 99.0)
        _update_status(backup_id, progress=pct, completed_step=step_name)

    try:
        with Session(engine) as db:
            for user_info in analysis.users:
                # ── 1. Create user ──────────────────────────────────────
                _update_status(backup_id, step=MigrationStep.CREATING_USERS, progress=5)

                password = secrets.token_urlsafe(16) if options.generate_passwords else "changeme"

                # Check if username already exists
                existing = db.execute(
                    select(User).where(User.username == user_info.username)
                ).scalar_one_or_none()

                if existing:
                    user = existing
                    _update_status(
                        backup_id,
                        warning=f"User '{user_info.username}' already exists, importing into existing account.",
                    )
                else:
                    user = User(
                        username=user_info.username,
                        email=user_info.email or f"{user_info.username}@localhost",
                        password_hash=hash_password(password),
                        role=UserRole.USER,
                        is_active=True,
                    )
                    db.add(user)
                    db.flush()
                    _update_status(backup_id, created_user_id=str(user.id))

                advance("create_users")

                # ── 2. Import domains ───────────────────────────────────
                if user_info.domains:
                    _update_status(backup_id, step=MigrationStep.IMPORTING_DOMAINS)
                    for dinfo in user_info.domains:
                        # Skip if domain already exists
                        existing_domain = db.execute(
                            select(Domain).where(Domain.domain_name == dinfo.name)
                        ).scalar_one_or_none()
                        if existing_domain:
                            _update_status(
                                backup_id,
                                warning=f"Domain '{dinfo.name}' already exists, skipping.",
                            )
                            continue

                        domain = Domain(
                            user_id=user.id,
                            domain_name=dinfo.name,
                            document_root=dinfo.document_root or f"/home/{user_info.username}/web/{dinfo.name}/public_html",
                            ssl_enabled=dinfo.has_ssl,
                        )
                        db.add(domain)
                        db.flush()
                        _update_status(backup_id, created_domain_id=str(domain.id))

                    advance("import_domains")

                # ── 3. Import databases ─────────────────────────────────
                if user_info.databases and not options.skip_databases:
                    _update_status(backup_id, step=MigrationStep.IMPORTING_DATABASES)
                    for dbinfo in user_info.databases:
                        db_password = secrets.token_urlsafe(16)
                        db_type = DbType.MYSQL if dbinfo.db_type == "mysql" else DbType.POSTGRESQL

                        existing_db = db.execute(
                            select(Database).where(Database.db_name == dbinfo.name)
                        ).scalar_one_or_none()
                        if existing_db:
                            _update_status(
                                backup_id,
                                warning=f"Database '{dbinfo.name}' already exists, skipping.",
                            )
                            continue

                        database = Database(
                            user_id=user.id,
                            db_name=dbinfo.name,
                            db_user=f"{user_info.username}_{dbinfo.name}"[:128],
                            db_password_encrypted=encrypt_value(db_password, settings.SECRET_KEY),
                            db_type=db_type,
                        )
                        db.add(database)
                        db.flush()
                        _update_status(backup_id, created_database_id=str(database.id))

                    advance("import_databases")

                    # ── 3b. Restore SQL dumps ───────────────────────────
                    _update_status(backup_id, step=MigrationStep.RESTORING_SQL)
                    for dbinfo in user_info.databases:
                        if not dbinfo.has_dump:
                            continue
                        dump_path = migrator.get_sql_dump_path(dbinfo.name)
                        if dump_path is None:
                            _update_status(
                                backup_id,
                                warning=f"SQL dump for '{dbinfo.name}' not found on disk.",
                            )
                            continue

                        try:
                            if dbinfo.db_type == "mysql":
                                _restore_mysql_dump(dbinfo.name, str(dump_path))
                            else:
                                _restore_pgsql_dump(dbinfo.name, str(dump_path))
                        except Exception as exc:
                            logger.exception("Failed to restore SQL dump for %s", dbinfo.name)
                            _update_status(
                                backup_id,
                                warning=f"SQL restore for '{dbinfo.name}' failed: {exc}",
                            )

                    advance("restore_sql")

                # ── 4. Import email accounts ────────────────────────────
                if user_info.emails and not options.skip_mail:
                    _update_status(backup_id, step=MigrationStep.IMPORTING_EMAIL)
                    for einfo in user_info.emails:
                        # Need to find the domain_id
                        domain_row = db.execute(
                            select(Domain).where(Domain.domain_name == einfo.domain)
                        ).scalar_one_or_none()
                        if not domain_row:
                            _update_status(
                                backup_id,
                                warning=f"Domain '{einfo.domain}' not found for email '{einfo.address}', skipping.",
                            )
                            continue

                        existing_email = db.execute(
                            select(EmailAccount).where(EmailAccount.address == einfo.address)
                        ).scalar_one_or_none()
                        if existing_email:
                            _update_status(
                                backup_id,
                                warning=f"Email '{einfo.address}' already exists, skipping.",
                            )
                            continue

                        email_password = secrets.token_urlsafe(12)
                        email_account = EmailAccount(
                            user_id=user.id,
                            domain_id=domain_row.id,
                            address=einfo.address,
                            password_hash=hash_password(email_password),
                            password_encrypted=encrypt_value(email_password, settings.SECRET_KEY),
                            quota_mb=einfo.quota_mb if einfo.quota_mb > 0 else 1024,
                        )
                        db.add(email_account)
                        db.flush()
                        _update_status(backup_id, created_email_id=str(email_account.id))

                    advance("import_email")

                # ── 5. Import DNS zones (placeholder) ───────────────────
                if user_info.dns_zones and not options.skip_dns:
                    _update_status(backup_id, step=MigrationStep.IMPORTING_DNS)
                    # DNS zone import would call the agent to create BIND/PowerDNS zones.
                    # For now, log the zones that would be created.
                    for zinfo in user_info.dns_zones:
                        logger.info(
                            "Migration %s: would import DNS zone '%s' (%d records)",
                            backup_id, zinfo.domain, zinfo.record_count,
                        )
                        _update_status(
                            backup_id,
                            warning=f"DNS zone '{zinfo.domain}' noted but zone file import requires agent integration.",
                        )
                    advance("import_dns")

                # ── 6. Import cron jobs (placeholder) ───────────────────
                if user_info.cron_jobs and not options.skip_cron:
                    _update_status(backup_id, step=MigrationStep.IMPORTING_CRON)
                    for cinfo in user_info.cron_jobs:
                        logger.info(
                            "Migration %s: would create cron '%s %s'",
                            backup_id, cinfo.schedule, cinfo.command,
                        )
                        _update_status(
                            backup_id,
                            warning=f"Cron job noted: {cinfo.schedule} {cinfo.command} (requires agent integration).",
                        )
                    advance("import_cron")

            db.commit()

        _update_status(backup_id, step=MigrationStep.DONE, progress=100)
        logger.info("Migration %s completed successfully.", backup_id)
        return {"success": True, "backup_id": backup_id}

    except Exception as exc:
        logger.exception("Migration %s failed", backup_id)
        _update_status(backup_id, step=MigrationStep.FAILED, error=str(exc), progress=100)
        return {"success": False, "error": str(exc)}

    finally:
        # Clean up extracted files (keep the original upload for a while)
        extracted = _UPLOAD_DIR / backup_id / "extracted"
        if extracted.is_dir():
            shutil.rmtree(extracted, ignore_errors=True)


# ---------------------------------------------------------------------------
# SQL restore helpers
# ---------------------------------------------------------------------------

def _restore_mysql_dump(db_name: str, dump_path: str) -> None:
    """Restore a MySQL dump file into the given database."""
    cmd: list[str]
    if dump_path.endswith(".gz"):
        cmd = ["bash", "-c", f"zcat {dump_path} | mysql {db_name}"]
    else:
        cmd = ["mysql", db_name, "-e", f"source {dump_path}"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"mysql restore failed: {result.stderr[:500]}")


def _restore_pgsql_dump(db_name: str, dump_path: str) -> None:
    """Restore a PostgreSQL dump file into the given database."""
    cmd: list[str]
    if dump_path.endswith(".gz"):
        cmd = ["bash", "-c", f"zcat {dump_path} | psql {db_name}"]
    else:
        cmd = ["psql", db_name, "-f", dump_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"psql restore failed: {result.stderr[:500]}")
