"""Databases router -- /api/v1/databases.

Supports MySQL/MariaDB and PostgreSQL.  Every mutating endpoint persists to the
app database first, then tries the agent.  If the agent is unreachable or
errors out, a *direct* subprocess fallback is attempted so the panel keeps
working without a running agent.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import subprocess
import uuid
from functools import partial
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.databases import Database, DbType
from api.models.users import User
from api.schemas.databases import DatabaseCreate, DatabaseResponse

router = APIRouter()
logger = logging.getLogger(__name__)


# =====================================================================
# Helpers
# =====================================================================

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_db_or_404(
    db_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Database:
    result = await db.execute(select(Database).where(Database.id == db_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database not found.")
    if not _is_admin(current_user) and record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return record


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# =====================================================================
# Direct subprocess helpers (fallback when agent is unavailable)
# =====================================================================

def _run_cmd(cmd: list[str], *, stdin_data: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a command synchronously. Meant to be called via run_in_executor."""
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def _run_async(
    cmd: list[str],
    *,
    stdin_data: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a blocking subprocess in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(_run_cmd, cmd, stdin_data=stdin_data, timeout=timeout),
    )


# -- MySQL / MariaDB -------------------------------------------------------

async def _mysql_exec(sql: str, db_password: str | None = None) -> subprocess.CompletedProcess:
    """Execute a MySQL statement as root (via sudo for Debian compatibility)."""
    cmd = ["sudo", "mysql", "-u", "root"]
    if db_password:
        cmd.append(f"-p{db_password}")
    return await _run_async(cmd, stdin_data=sql)


async def _mysql_create(db_name: str, db_user: str, db_password: str) -> None:
    """Create a MySQL database + user with full privileges."""
    r1 = await _mysql_exec(f"CREATE DATABASE IF NOT EXISTS `{db_name}`;")
    if r1.returncode != 0:
        raise RuntimeError(f"MySQL CREATE DATABASE failed: {r1.stderr.strip()}")

    r2 = await _mysql_exec(
        f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';"
    )
    if r2.returncode != 0:
        raise RuntimeError(f"MySQL CREATE USER failed: {r2.stderr.strip()}")

    r3 = await _mysql_exec(
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';"
    )
    if r3.returncode != 0:
        raise RuntimeError(f"MySQL GRANT failed: {r3.stderr.strip()}")

    await _mysql_exec("FLUSH PRIVILEGES;")


async def _mysql_delete(db_name: str, db_user: str) -> None:
    """Drop a MySQL database and its user."""
    r1 = await _mysql_exec(f"DROP DATABASE IF EXISTS `{db_name}`;")
    if r1.returncode != 0:
        raise RuntimeError(f"MySQL DROP DATABASE failed: {r1.stderr.strip()}")

    r2 = await _mysql_exec(f"DROP USER IF EXISTS '{db_user}'@'localhost';")
    if r2.returncode != 0:
        raise RuntimeError(f"MySQL DROP USER failed: {r2.stderr.strip()}")

    await _mysql_exec("FLUSH PRIVILEGES;")


async def _mysql_reset_password(db_user: str, new_password: str) -> None:
    """Reset a MySQL user password."""
    r = await _mysql_exec(
        f"ALTER USER '{db_user}'@'localhost' IDENTIFIED BY '{new_password}';"
    )
    if r.returncode != 0:
        raise RuntimeError(f"MySQL ALTER USER failed: {r.stderr.strip()}")
    await _mysql_exec("FLUSH PRIVILEGES;")


async def _mysql_get_sizes() -> dict[str, int]:
    """Return {db_name: size_bytes} from information_schema."""
    sql = (
        "SELECT table_schema, IFNULL(SUM(data_length + index_length), 0) "
        "FROM information_schema.tables GROUP BY table_schema;"
    )
    r = await _mysql_exec(sql)
    sizes: dict[str, int] = {}
    if r.returncode == 0 and r.stdout:
        for line in r.stdout.strip().splitlines()[1:]:  # skip header row
            parts = line.split("\t")
            if len(parts) == 2:
                try:
                    sizes[parts[0]] = int(float(parts[1]))
                except ValueError:
                    pass
    return sizes


# -- PostgreSQL -------------------------------------------------------------

async def _psql_exec(sql: str) -> subprocess.CompletedProcess:
    """Execute a PostgreSQL statement as the postgres OS user."""
    return await _run_async(["sudo", "-u", "postgres", "psql", "-c", sql])


async def _psql_create(db_name: str, db_user: str, db_password: str) -> None:
    """Create a PostgreSQL database + role."""
    # Create user (role) first -- ignore "already exists" errors
    r1 = await _psql_exec(
        f"DO $$ BEGIN "
        f"CREATE USER \"{db_user}\" WITH PASSWORD '{db_password}'; "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    if r1.returncode != 0:
        raise RuntimeError(f"PostgreSQL CREATE USER failed: {r1.stderr.strip()}")

    r2 = await _psql_exec(f"CREATE DATABASE \"{db_name}\" OWNER \"{db_user}\";")
    if r2.returncode != 0 and "already exists" not in r2.stderr:
        raise RuntimeError(f"PostgreSQL CREATE DATABASE failed: {r2.stderr.strip()}")

    r3 = await _psql_exec(
        f"GRANT ALL PRIVILEGES ON DATABASE \"{db_name}\" TO \"{db_user}\";"
    )
    if r3.returncode != 0:
        raise RuntimeError(f"PostgreSQL GRANT failed: {r3.stderr.strip()}")


async def _psql_delete(db_name: str, db_user: str) -> None:
    """Drop a PostgreSQL database and role."""
    r1 = await _psql_exec(f"DROP DATABASE IF EXISTS \"{db_name}\";")
    if r1.returncode != 0:
        raise RuntimeError(f"PostgreSQL DROP DATABASE failed: {r1.stderr.strip()}")

    r2 = await _psql_exec(f"DROP USER IF EXISTS \"{db_user}\";")
    if r2.returncode != 0:
        raise RuntimeError(f"PostgreSQL DROP USER failed: {r2.stderr.strip()}")


async def _psql_reset_password(db_user: str, new_password: str) -> None:
    """Reset a PostgreSQL user password."""
    r = await _psql_exec(
        f"ALTER USER \"{db_user}\" WITH PASSWORD '{new_password}';"
    )
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL ALTER USER failed: {r.stderr.strip()}")


async def _psql_get_size(db_name: str) -> int:
    """Return size in bytes for a single PostgreSQL database."""
    r = await _psql_exec(f"SELECT pg_database_size('{db_name}');")
    if r.returncode == 0 and r.stdout:
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    return 0


# -- Dispatch helpers -------------------------------------------------------

async def _direct_create(db_name: str, db_user: str, db_password: str, db_type: str) -> None:
    if db_type == "mysql":
        await _mysql_create(db_name, db_user, db_password)
    else:
        await _psql_create(db_name, db_user, db_password)


async def _direct_delete(db_name: str, db_user: str, db_type: str) -> None:
    if db_type == "mysql":
        await _mysql_delete(db_name, db_user)
    else:
        await _psql_delete(db_name, db_user)


async def _direct_reset_password(db_user: str, new_password: str, db_type: str) -> None:
    if db_type == "mysql":
        await _mysql_reset_password(db_user, new_password)
    else:
        await _psql_reset_password(db_user, new_password)


async def _get_size_for_record(record: Database) -> int:
    """Best-effort size lookup for a single database record."""
    try:
        if record.db_type == DbType.MYSQL:
            sizes = await _mysql_get_sizes()
            return sizes.get(record.db_name, 0)
        else:
            return await _psql_get_size(record.db_name)
    except Exception:
        return 0


# =====================================================================
# Endpoints
# =====================================================================


# --------------------------------------------------------------------------
# GET / -- list databases (with sizes)
# --------------------------------------------------------------------------
@router.get("", status_code=status.HTTP_200_OK)
async def list_databases(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Database)
    count_query = select(func.count()).select_from(Database)
    if not _is_admin(current_user):
        query = query.where(Database.user_id == current_user.id)
        count_query = count_query.where(Database.user_id == current_user.id)

    total = (await db.execute(count_query)).scalar() or 0
    results = (
        await db.execute(query.order_by(Database.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    # --- Collect sizes (best-effort) ---
    # Pre-fetch MySQL sizes in one query to avoid N+1
    mysql_sizes: dict[str, int] = {}
    has_mysql = any(r.db_type == DbType.MYSQL for r in results)
    if has_mysql:
        try:
            mysql_sizes = await _mysql_get_sizes()
        except Exception:
            logger.debug("Could not fetch MySQL sizes", exc_info=True)

    items: list[DatabaseResponse] = []
    for record in results:
        resp = DatabaseResponse.model_validate(record)
        try:
            if record.db_type == DbType.MYSQL:
                resp.size = mysql_sizes.get(record.db_name, 0)
            else:
                resp.size = await _psql_get_size(record.db_name)
        except Exception:
            resp.size = 0
        items.append(resp)

    return {
        "items": items,
        "total": total,
    }


# --------------------------------------------------------------------------
# POST / -- create database (agent -> direct fallback)
# --------------------------------------------------------------------------
@router.post("", response_model=DatabaseResponse, status_code=status.HTTP_201_CREATED)
async def create_database(
    body: DatabaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Uniqueness check
    exists = await db.execute(select(Database).where(Database.db_name == body.db_name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database name already exists.")

    # 1. Save to app DB first (Fernet-encrypted so password is recoverable for SSO)
    from api.core.config import settings
    record = Database(
        user_id=current_user.id,
        db_name=body.db_name,
        db_user=body.db_user,
        db_password_encrypted=encrypt_value(body.db_password, settings.SECRET_KEY),
        db_type=body.db_type,
    )
    db.add(record)
    await db.flush()

    # 2. Try agent
    agent = getattr(request.app.state, "agent", None)
    provisioned = False
    provision_error: Optional[str] = None

    if agent is not None:
        try:
            await agent.create_database(
                db_name=body.db_name,
                db_user=body.db_user,
                db_password=body.db_password,
                db_type=body.db_type.value,
            )
            provisioned = True
            logger.info("Database %s created via agent", body.db_name)
        except Exception as exc:
            provision_error = str(exc)
            logger.warning("Agent failed to create database %s: %s", body.db_name, exc)

    # 3. Fallback to direct subprocess
    if not provisioned:
        try:
            await _direct_create(
                db_name=body.db_name,
                db_user=body.db_user,
                db_password=body.db_password,
                db_type=body.db_type.value,
            )
            provisioned = True
            logger.info("Database %s created via direct command (fallback)", body.db_name)
        except Exception as exc:
            logger.error("Direct fallback also failed for %s: %s", body.db_name, exc)
            # Roll back the app DB record since we could not provision
            await db.delete(record)
            await db.flush()
            detail = f"Agent error: {provision_error}; Direct error: {exc}" if provision_error else str(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to create database: {detail}",
            )

    _log(db, request, current_user.id, "databases.create", f"Created {body.db_type.value} database {body.db_name}")
    return DatabaseResponse.model_validate(record)


# --------------------------------------------------------------------------
# GET /{id} -- database detail (with size)
# --------------------------------------------------------------------------
@router.get("/{db_id}", response_model=DatabaseResponse, status_code=status.HTTP_200_OK)
async def get_database(
    db_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _get_db_or_404(db_id, db, current_user)
    resp = DatabaseResponse.model_validate(record)
    resp.size = await _get_size_for_record(record)
    return resp


# --------------------------------------------------------------------------
# DELETE /{id} -- delete database (agent -> direct fallback)
# --------------------------------------------------------------------------
@router.delete("/{db_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_database(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _get_db_or_404(db_id, db, current_user)
    db_name = record.db_name
    db_user = record.db_user
    db_type = record.db_type.value

    # Try agent first
    agent = getattr(request.app.state, "agent", None)
    deleted = False
    delete_error: Optional[str] = None

    if agent is not None:
        try:
            await agent.delete_database(db_name, db_user, db_type)
            deleted = True
            logger.info("Database %s deleted via agent", db_name)
        except Exception as exc:
            delete_error = str(exc)
            logger.warning("Agent failed to delete database %s: %s", db_name, exc)

    # Fallback to direct subprocess
    if not deleted:
        try:
            await _direct_delete(db_name, db_user, db_type)
            deleted = True
            logger.info("Database %s deleted via direct command (fallback)", db_name)
        except Exception as exc:
            logger.error("Direct fallback also failed for %s: %s", db_name, exc)
            detail = f"Agent error: {delete_error}; Direct error: {exc}" if delete_error else str(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to delete database: {detail}",
            )

    _log(db, request, current_user.id, "databases.delete", f"Deleted database {db_name}")
    await db.delete(record)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/reset-password -- generate new password (agent -> direct fallback)
# --------------------------------------------------------------------------
@router.post("/{db_id}/reset-password", status_code=status.HTTP_200_OK)
async def reset_database_password(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = await _get_db_or_404(db_id, db, current_user)
    new_password = secrets.token_urlsafe(24)

    # Try agent first
    agent = getattr(request.app.state, "agent", None)
    reset_done = False
    reset_error: Optional[str] = None

    if agent is not None:
        try:
            await agent._request(
                "POST",
                "/database/reset-password",
                json_body={
                    "db_name": record.db_name,
                    "db_user": record.db_user,
                    "db_password": new_password,
                    "db_type": record.db_type.value,
                },
            )
            reset_done = True
            logger.info("Password reset for %s via agent", record.db_name)
        except Exception as exc:
            reset_error = str(exc)
            logger.warning("Agent failed to reset password for %s: %s", record.db_name, exc)

    # Fallback to direct subprocess
    if not reset_done:
        try:
            await _direct_reset_password(
                db_user=record.db_user,
                new_password=new_password,
                db_type=record.db_type.value,
            )
            reset_done = True
            logger.info("Password reset for %s via direct command (fallback)", record.db_name)
        except Exception as exc:
            logger.error("Direct fallback also failed for %s: %s", record.db_name, exc)
            detail = f"Agent error: {reset_error}; Direct error: {exc}" if reset_error else str(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reset password: {detail}",
            )

    from api.core.config import settings
    record.db_password_encrypted = encrypt_value(new_password, settings.SECRET_KEY)
    db.add(record)
    await db.flush()

    _log(db, request, current_user.id, "databases.reset_password", f"Reset password for {record.db_name}")
    return {"db_name": record.db_name, "new_password": new_password}


# --------------------------------------------------------------------------
# POST /{id}/sso -- generate SSO token for phpMyAdmin auto-login
# --------------------------------------------------------------------------
@router.post("/{db_id}/sso", status_code=status.HTTP_200_OK)
async def database_sso(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a one-time SSO token for phpMyAdmin auto-login."""
    record = await _get_db_or_404(db_id, db, current_user)

    if record.db_type not in (DbType.MYSQL, DbType.POSTGRESQL):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database SSO is only available for MySQL and PostgreSQL.",
        )

    # Decrypt the stored password
    import json as _json
    from api.core.config import settings

    password = None

    # Try to decrypt stored password
    if record.db_password_encrypted:
        try:
            password = decrypt_value(record.db_password_encrypted, settings.SECRET_KEY)
        except (ValueError, Exception):
            password = None

    # If no encrypted password available, generate new one and reset
    if not password:
        import string
        import random
        new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
        try:
            await _direct_reset_password(record.db_user, new_password, record.db_type)
            record.db_password_encrypted = encrypt_value(new_password, settings.SECRET_KEY)
            db.add(record)
            await db.commit()
            password = new_password
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not reset database password for SSO: {exc}",
            )

    # Generate one-time token stored in Redis (expires 30s)
    token = secrets.token_urlsafe(32)
    redis = request.app.state.redis
    await redis.setex(
        f"hosthive:pma_sso:{token}",
        30,
        _json.dumps({
            "user": record.db_user,
            "password": password,
            "server": "localhost",
        }),
    )

    _log(db, request, current_user.id, "databases.sso", f"SSO login to phpMyAdmin for {record.db_name}")
    return {"sso_url": f"/phpmyadmin/sso.php?token={token}"}
