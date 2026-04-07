"""Databases router -- /api/v1/databases.

Supports MySQL/MariaDB and PostgreSQL.  Every mutating endpoint persists to the
app database and then runs the operation directly via subprocess (sudo mysql /
sudo -u postgres psql).  The agent on port 7080 is intentionally NOT used --
the panel runs the commands itself so it works without a running agent.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import secrets
import subprocess
import uuid
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.databases import Database, DatabaseUser, DbType
from api.models.users import User
from api.schemas.databases import (
    BackupInfo,
    BackupListResponse,
    DatabaseCreate,
    DatabaseResponse,
    DatabaseUserCreate,
    DatabaseUserPermissionsUpdate,
    DatabaseUserResponse,
    RemoteAccessUpdate,
    RestoreRequest,
)

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
    result = await db.execute(
        select(Database)
        .options(selectinload(Database.extra_users))
        .where(Database.id == db_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database not found.")
    if not _is_admin(current_user) and record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return record


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


_VALID_PERMISSIONS = {"SELECT", "INSERT", "UPDATE", "DELETE", "ALL"}


def _validate_permissions(perms_str: str) -> str:
    """Validate and normalise a comma-separated permissions string."""
    parts = [p.strip().upper() for p in perms_str.split(",") if p.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="Permissions must not be empty.")
    for p in parts:
        if p not in _VALID_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"Invalid permission: {p}")
    if "ALL" in parts:
        return "ALL"
    return ",".join(sorted(set(parts)))


# =====================================================================
# Direct subprocess helpers (used by every mutating endpoint)
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


# -- Remote-access helpers --------------------------------------------------

async def _mysql_grant_remote(db_name: str, db_user: str, db_password: str, host: str) -> None:
    """Create a MySQL user@host entry and grant privileges."""
    r = await _mysql_exec(
        f"CREATE USER IF NOT EXISTS '{db_user}'@'{host}' IDENTIFIED BY '{db_password}';"
    )
    if r.returncode != 0:
        raise RuntimeError(f"MySQL CREATE USER@{host} failed: {r.stderr.strip()}")
    r = await _mysql_exec(
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'{host}';"
    )
    if r.returncode != 0:
        raise RuntimeError(f"MySQL GRANT@{host} failed: {r.stderr.strip()}")
    await _mysql_exec("FLUSH PRIVILEGES;")


async def _mysql_revoke_remote(db_user: str, host: str) -> None:
    """Drop a MySQL user@host entry (best-effort)."""
    await _mysql_exec(f"DROP USER IF EXISTS '{db_user}'@'{host}';")
    await _mysql_exec("FLUSH PRIVILEGES;")


async def _psql_update_pg_hba(db_name: str, db_user: str, hosts: list[str], enable: bool) -> None:
    """Add or remove host entries in pg_hba.conf for remote access."""
    marker_start = f"# hosthive-remote-start {db_name} {db_user}"
    marker_end = f"# hosthive-remote-end {db_name} {db_user}"

    # Read current pg_hba.conf
    r = await _run_async(["sudo", "-u", "postgres", "psql", "-t", "-A", "-c", "SHOW hba_file;"])
    hba_path = r.stdout.strip() if r.returncode == 0 else "/etc/postgresql/15/main/pg_hba.conf"

    r = await _run_async(["sudo", "cat", hba_path])
    if r.returncode != 0:
        raise RuntimeError(f"Cannot read pg_hba.conf: {r.stderr.strip()}")

    lines = r.stdout.splitlines()

    # Remove existing block for this db/user
    new_lines: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == marker_start:
            skipping = True
            continue
        if line.strip() == marker_end:
            skipping = False
            continue
        if not skipping:
            new_lines.append(line)

    # Add new block if enabling
    if enable and hosts:
        new_lines.append(marker_start)
        for host in hosts:
            if host == "localhost" or host == "127.0.0.1":
                continue
            # Determine if host is CIDR or plain IP
            cidr = host if "/" in host else f"{host}/32"
            new_lines.append(f"host    {db_name}    {db_user}    {cidr}    md5")
        new_lines.append(marker_end)

    content = "\n".join(new_lines) + "\n"
    r = await _run_async(["sudo", "tee", hba_path], stdin_data=content)
    if r.returncode != 0:
        raise RuntimeError(f"Cannot write pg_hba.conf: {r.stderr.strip()}")

    # Reload PostgreSQL to pick up changes
    await _run_async(["sudo", "systemctl", "reload", "postgresql"])


# -- Additional user helpers ------------------------------------------------

async def _mysql_create_user(db_name: str, username: str, password: str, permissions: str) -> None:
    """Create an additional MySQL user with specific permissions on a database."""
    r = await _mysql_exec(
        f"CREATE USER IF NOT EXISTS '{username}'@'localhost' IDENTIFIED BY '{password}';"
    )
    if r.returncode != 0:
        raise RuntimeError(f"MySQL CREATE USER failed: {r.stderr.strip()}")

    grant = "ALL PRIVILEGES" if permissions == "ALL" else permissions

    r = await _mysql_exec(
        f"GRANT {grant} ON `{db_name}`.* TO '{username}'@'localhost';"
    )
    if r.returncode != 0:
        raise RuntimeError(f"MySQL GRANT failed: {r.stderr.strip()}")
    await _mysql_exec("FLUSH PRIVILEGES;")


async def _mysql_drop_user(username: str) -> None:
    await _mysql_exec(f"DROP USER IF EXISTS '{username}'@'localhost';")
    await _mysql_exec("FLUSH PRIVILEGES;")


async def _mysql_update_user_perms(db_name: str, username: str, permissions: str) -> None:
    """Revoke all and re-grant with new permissions."""
    await _mysql_exec(f"REVOKE ALL PRIVILEGES ON `{db_name}`.* FROM '{username}'@'localhost';")
    grant = "ALL PRIVILEGES" if permissions == "ALL" else permissions
    r = await _mysql_exec(f"GRANT {grant} ON `{db_name}`.* TO '{username}'@'localhost';")
    if r.returncode != 0:
        raise RuntimeError(f"MySQL GRANT failed: {r.stderr.strip()}")
    await _mysql_exec("FLUSH PRIVILEGES;")


async def _psql_create_user(db_name: str, username: str, password: str, permissions: str) -> None:
    """Create an additional PostgreSQL role with specific permissions."""
    r = await _psql_exec(
        f"DO $$ BEGIN "
        f"CREATE USER \"{username}\" WITH PASSWORD '{password}'; "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL CREATE USER failed: {r.stderr.strip()}")

    if permissions == "ALL":
        r = await _psql_exec(
            f"GRANT ALL PRIVILEGES ON DATABASE \"{db_name}\" TO \"{username}\";"
        )
    else:
        # For PostgreSQL, grant table-level perms on all tables in public schema
        r = await _run_async([
            "sudo", "-u", "postgres", "psql", "-d", db_name, "-c",
            f"GRANT {permissions} ON ALL TABLES IN SCHEMA public TO \"{username}\";"
        ])
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL GRANT failed: {r.stderr.strip()}")


async def _psql_drop_user(username: str) -> None:
    await _psql_exec(f"DROP ROLE IF EXISTS \"{username}\";")


async def _psql_update_user_perms(db_name: str, username: str, permissions: str) -> None:
    """Revoke all and re-grant with new permissions."""
    await _run_async([
        "sudo", "-u", "postgres", "psql", "-d", db_name, "-c",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM \"{username}\";"
    ])
    await _psql_exec(f"REVOKE ALL PRIVILEGES ON DATABASE \"{db_name}\" FROM \"{username}\";")

    if permissions == "ALL":
        await _psql_exec(
            f"GRANT ALL PRIVILEGES ON DATABASE \"{db_name}\" TO \"{username}\";"
        )
    else:
        r = await _run_async([
            "sudo", "-u", "postgres", "psql", "-d", db_name, "-c",
            f"GRANT {permissions} ON ALL TABLES IN SCHEMA public TO \"{username}\";"
        ])
        if r.returncode != 0:
            raise RuntimeError(f"PostgreSQL GRANT failed: {r.stderr.strip()}")


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
    query = select(Database).options(selectinload(Database.extra_users))
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
# POST / -- create database (direct subprocess, no agent)
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

    # 2. Provision directly via subprocess (no agent proxy)
    try:
        await _direct_create(
            db_name=body.db_name,
            db_user=body.db_user,
            db_password=body.db_password,
            db_type=body.db_type.value,
        )
        logger.info("Database %s created via direct command", body.db_name)
    except Exception as exc:
        logger.error("Failed to create database %s: %s", body.db_name, exc)
        # Roll back the app DB record since we could not provision
        await db.delete(record)
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create database: {exc}",
        )

    _log(db, request, current_user.id, "databases.create", f"Created {body.db_type.value} database {body.db_name}")
    # Reload with extra_users eagerly loaded to avoid greenlet error
    await db.refresh(record, attribute_names=["extra_users"])
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
# DELETE /{id} -- delete database (direct subprocess, no agent)
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

    # Drop directly via subprocess (no agent proxy)
    try:
        await _direct_delete(db_name, db_user, db_type)
        logger.info("Database %s deleted via direct command", db_name)
    except Exception as exc:
        logger.error("Failed to delete database %s: %s", db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete database: {exc}",
        )

    _log(db, request, current_user.id, "databases.delete", f"Deleted database {db_name}")
    await db.delete(record)
    await db.flush()


# --------------------------------------------------------------------------
# POST /{id}/reset-password -- generate new password (direct subprocess, no agent)
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

    # Reset directly via subprocess (no agent proxy)
    try:
        await _direct_reset_password(
            db_user=record.db_user,
            new_password=new_password,
            db_type=record.db_type.value,
        )
        logger.info("Password reset for %s via direct command", record.db_name)
    except Exception as exc:
        logger.error("Failed to reset password for %s: %s", record.db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reset password: {exc}",
        )

    from api.core.config import settings
    record.db_password_encrypted = encrypt_value(new_password, settings.SECRET_KEY)
    db.add(record)
    await db.flush()

    _log(db, request, current_user.id, "databases.reset_password", f"Reset password for {record.db_name}")
    return {"db_name": record.db_name, "new_password": new_password}


# --------------------------------------------------------------------------
# POST /{id}/sso -- generate SSO token for phpMyAdmin auto-login (MySQL)
# --------------------------------------------------------------------------
@router.post("/{db_id}/sso", status_code=status.HTTP_200_OK)
async def database_sso(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a one-time SSO token for phpMyAdmin auto-login (MySQL only)."""
    record = await _get_db_or_404(db_id, db, current_user)

    if record.db_type != DbType.MYSQL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phpMyAdmin SSO is only available for MySQL databases. Use /sso-pgsql for PostgreSQL.",
        )

    from api.core.config import settings

    password = None
    if record.db_password_encrypted:
        try:
            password = decrypt_value(record.db_password_encrypted, settings.SECRET_KEY)
        except (ValueError, Exception):
            password = None

    if not password:
        import random
        import string
        new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
        try:
            await _direct_reset_password(record.db_user, new_password, record.db_type.value)
            record.db_password_encrypted = encrypt_value(new_password, settings.SECRET_KEY)
            db.add(record)
            await db.commit()
            password = new_password
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not reset database password for SSO: {exc}",
            )

    token = secrets.token_urlsafe(32)
    redis = request.app.state.redis
    await redis.setex(
        f"hosthive:pma_sso:{token}",
        120,
        _json.dumps({
            "user": record.db_user,
            "password": password,
            "server": "localhost",
        }),
    )

    _log(db, request, current_user.id, "databases.sso", f"SSO login to phpMyAdmin for {record.db_name}")
    return {"sso_url": f"/phpmyadmin/sso.php?token={token}"}


# --------------------------------------------------------------------------
# POST /{id}/sso-pgsql -- generate SSO token for phpPgAdmin auto-login
# --------------------------------------------------------------------------
@router.post("/{db_id}/sso-pgsql", status_code=status.HTTP_200_OK)
async def database_sso_pgsql(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a one-time SSO token for phpPgAdmin auto-login (PostgreSQL only)."""
    record = await _get_db_or_404(db_id, db, current_user)

    if record.db_type != DbType.POSTGRESQL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phpPgAdmin SSO is only available for PostgreSQL databases.",
        )

    from api.core.config import settings

    password = None
    if record.db_password_encrypted:
        try:
            password = decrypt_value(record.db_password_encrypted, settings.SECRET_KEY)
        except (ValueError, Exception):
            password = None

    # If no password available, generate and reset
    if not password:
        import random
        import string
        new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
        try:
            await _direct_reset_password(record.db_user, new_password, record.db_type.value)
            record.db_password_encrypted = encrypt_value(new_password, settings.SECRET_KEY)
            db.add(record)
            await db.commit()
            password = new_password
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not reset database password for SSO: {exc}",
            )

    # Store one-time token in Redis (120s TTL)
    token = secrets.token_urlsafe(32)
    redis = request.app.state.redis
    await redis.setex(
        f"hosthive:pgadmin_sso:{token}",
        120,
        _json.dumps({
            "user": record.db_user,
            "password": password,
            "database": record.db_name,
            "server": "localhost",
        }),
    )

    _log(db, request, current_user.id, "databases.sso_pgsql", f"SSO login to phpPgAdmin for {record.db_name}")
    return {"sso_url": f"/phppgadmin/sso.php?token={token}"}


# --------------------------------------------------------------------------
# PUT /{id}/remote-access -- enable/disable remote database access
# --------------------------------------------------------------------------
@router.put("/{db_id}/remote-access", status_code=status.HTTP_200_OK)
async def update_remote_access(
    db_id: uuid.UUID,
    body: RemoteAccessUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable or disable remote access for a database with an allowed-hosts whitelist."""
    record = await _get_db_or_404(db_id, db, current_user)

    from api.core.config import settings

    # Decrypt password (needed for MySQL remote grants)
    password = None
    if record.db_password_encrypted:
        try:
            password = decrypt_value(record.db_password_encrypted, settings.SECRET_KEY)
        except Exception:
            pass

    db_type = record.db_type.value
    hosts = body.allowed_hosts

    try:
        if db_type == "mysql":
            if body.enabled:
                for host in hosts:
                    if host in ("localhost", "127.0.0.1"):
                        continue
                    if password:
                        await _mysql_grant_remote(record.db_name, record.db_user, password, host)
            else:
                # Revoke all non-localhost hosts
                old_hosts = _json.loads(record.allowed_hosts or '["localhost"]')
                for host in old_hosts:
                    if host in ("localhost", "127.0.0.1"):
                        continue
                    await _mysql_revoke_remote(record.db_user, host)
        else:
            # PostgreSQL: update pg_hba.conf
            await _psql_update_pg_hba(record.db_name, record.db_user, hosts, body.enabled)
    except Exception as exc:
        logger.error("Failed to update remote access for %s: %s", record.db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to configure remote access: {exc}",
        )

    # Persist to app DB
    record.remote_access = body.enabled
    record.allowed_hosts = _json.dumps(hosts)
    db.add(record)
    await db.flush()

    _log(
        db, request, current_user.id, "databases.remote_access",
        f"{'Enabled' if body.enabled else 'Disabled'} remote access for {record.db_name}"
    )
    return {
        "remote_access": record.remote_access,
        "allowed_hosts": hosts,
    }


# --------------------------------------------------------------------------
# POST /{id}/users -- create additional database user
# --------------------------------------------------------------------------
@router.post("/{db_id}/users", response_model=DatabaseUserResponse, status_code=status.HTTP_201_CREATED)
async def create_database_user(
    db_id: uuid.UUID,
    body: DatabaseUserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an additional user with specific permissions on a database."""
    record = await _get_db_or_404(db_id, db, current_user)
    permissions = _validate_permissions(body.permissions)

    from api.core.config import settings

    # Provision the user on the actual database server
    try:
        if record.db_type == DbType.MYSQL:
            await _mysql_create_user(record.db_name, body.username, body.password, permissions)
        else:
            await _psql_create_user(record.db_name, body.username, body.password, permissions)
    except Exception as exc:
        logger.error("Failed to create DB user %s on %s: %s", body.username, record.db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create database user: {exc}",
        )

    # Save to app DB
    db_user_record = DatabaseUser(
        database_id=record.id,
        username=body.username,
        password_encrypted=encrypt_value(body.password, settings.SECRET_KEY),
        permissions=permissions,
    )
    db.add(db_user_record)
    await db.flush()

    _log(db, request, current_user.id, "databases.create_user",
         f"Created user {body.username} on {record.db_name} with {permissions}")
    return DatabaseUserResponse.model_validate(db_user_record)


# --------------------------------------------------------------------------
# GET /{id}/users -- list additional database users
# --------------------------------------------------------------------------
@router.get("/{db_id}/users", status_code=status.HTTP_200_OK)
async def list_database_users(
    db_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List additional users for a database."""
    record = await _get_db_or_404(db_id, db, current_user)
    users = [DatabaseUserResponse.model_validate(u) for u in record.extra_users]
    return {"users": users}


# --------------------------------------------------------------------------
# DELETE /{id}/users/{user_id} -- remove additional database user
# --------------------------------------------------------------------------
@router.delete("/{db_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_database_user(
    db_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an additional database user."""
    record = await _get_db_or_404(db_id, db, current_user)

    # Find the user record
    result = await db.execute(
        select(DatabaseUser).where(
            DatabaseUser.id == user_id,
            DatabaseUser.database_id == record.id,
        )
    )
    db_user_record = result.scalar_one_or_none()
    if db_user_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database user not found.")

    # Drop from actual database server
    try:
        if record.db_type == DbType.MYSQL:
            await _mysql_drop_user(db_user_record.username)
        else:
            await _psql_drop_user(db_user_record.username)
    except Exception as exc:
        logger.error("Failed to drop DB user %s: %s", db_user_record.username, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to remove database user: {exc}",
        )

    _log(db, request, current_user.id, "databases.delete_user",
         f"Removed user {db_user_record.username} from {record.db_name}")
    await db.delete(db_user_record)
    await db.flush()


# --------------------------------------------------------------------------
# PUT /{id}/users/{user_id}/permissions -- update database user permissions
# --------------------------------------------------------------------------
@router.put("/{db_id}/users/{user_id}/permissions", response_model=DatabaseUserResponse, status_code=status.HTTP_200_OK)
async def update_database_user_permissions(
    db_id: uuid.UUID,
    user_id: uuid.UUID,
    body: DatabaseUserPermissionsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update permissions for an additional database user."""
    record = await _get_db_or_404(db_id, db, current_user)
    permissions = _validate_permissions(body.permissions)

    # Find the user record
    result = await db.execute(
        select(DatabaseUser).where(
            DatabaseUser.id == user_id,
            DatabaseUser.database_id == record.id,
        )
    )
    db_user_record = result.scalar_one_or_none()
    if db_user_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database user not found.")

    # Update permissions on the actual database server
    try:
        if record.db_type == DbType.MYSQL:
            await _mysql_update_user_perms(record.db_name, db_user_record.username, permissions)
        else:
            await _psql_update_user_perms(record.db_name, db_user_record.username, permissions)
    except Exception as exc:
        logger.error("Failed to update perms for %s on %s: %s", db_user_record.username, record.db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to update permissions: {exc}",
        )

    db_user_record.permissions = permissions
    db.add(db_user_record)
    await db.flush()

    _log(db, request, current_user.id, "databases.update_user_perms",
         f"Updated permissions for {db_user_record.username} on {record.db_name} to {permissions}")
    return DatabaseUserResponse.model_validate(db_user_record)


# =====================================================================
# Backup & Restore endpoints
# =====================================================================

async def _get_username(user_id: uuid.UUID, db: AsyncSession) -> str:
    """Resolve a user_id to a username (needed for backup paths)."""
    result = await db.execute(select(User.username).where(User.id == user_id))
    username = result.scalar_one_or_none()
    if username is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return username


# --------------------------------------------------------------------------
# POST /{id}/backup -- create a backup of a specific database
# --------------------------------------------------------------------------
@router.post("/{db_id}/backup", status_code=status.HTTP_201_CREATED)
async def create_database_backup(
    db_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from agent.executors.database_executor import backup_database

    record = await _get_db_or_404(db_id, db, current_user)
    username = await _get_username(record.user_id, db)

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(
                backup_database,
                db_name=record.db_name,
                db_type=record.db_type.value,
                username=username,
            ),
        )
    except Exception as exc:
        logger.error("Backup failed for %s: %s", record.db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Backup failed: {exc}",
        )

    _log(db, request, current_user.id, "databases.backup", f"Backed up {record.db_name} -> {result['filename']}")
    return {
        "filename": result["filename"],
        "size": result["size"],
    }


# --------------------------------------------------------------------------
# GET /{id}/backups -- list backups for a database
# --------------------------------------------------------------------------
@router.get("/{db_id}/backups", response_model=BackupListResponse, status_code=status.HTTP_200_OK)
async def list_backups(
    db_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from agent.executors.database_executor import list_database_backups

    record = await _get_db_or_404(db_id, db, current_user)
    username = await _get_username(record.user_id, db)

    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(
        None,
        partial(list_database_backups, username=username, db_name=record.db_name),
    )

    return BackupListResponse(
        backups=[
            BackupInfo(filename=b["filename"], size=b["size"], created_at=b["created_at"])
            for b in items
        ]
    )


# --------------------------------------------------------------------------
# POST /{id}/restore -- restore from a backup file
# --------------------------------------------------------------------------
@router.post("/{db_id}/restore", status_code=status.HTTP_200_OK)
async def restore_database_backup(
    db_id: uuid.UUID,
    body: RestoreRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from agent.executors.database_executor import (
        _backup_dir_for_user,
        restore_database,
    )

    record = await _get_db_or_404(db_id, db, current_user)
    username = await _get_username(record.user_id, db)

    # Resolve full path from backup_name (prevent path traversal)
    backup_name = body.backup_name
    if "/" in backup_name or "\\" in backup_name or ".." in backup_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup name.")

    backup_dir = _backup_dir_for_user(username)
    input_path = backup_dir / backup_name
    if not input_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup file not found.")

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(
                restore_database,
                db_name=record.db_name,
                db_type=record.db_type.value,
                input_path=str(input_path),
            ),
        )
    except Exception as exc:
        logger.error("Restore failed for %s: %s", record.db_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Restore failed: {exc}",
        )

    _log(db, request, current_user.id, "databases.restore", f"Restored {record.db_name} from {backup_name}")
    return {"restored": True, "db_name": record.db_name, "backup_name": backup_name}


# --------------------------------------------------------------------------
# GET /{id}/backup/download -- download a specific backup file
# --------------------------------------------------------------------------
@router.get("/{db_id}/backup/download", status_code=status.HTTP_200_OK)
async def download_database_backup(
    db_id: uuid.UUID,
    backup_name: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from agent.executors.database_executor import _backup_dir_for_user

    record = await _get_db_or_404(db_id, db, current_user)
    username = await _get_username(record.user_id, db)

    if "/" in backup_name or "\\" in backup_name or ".." in backup_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup name.")

    backup_dir = _backup_dir_for_user(username)
    file_path = backup_dir / backup_name
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup file not found.")

    return FileResponse(
        path=str(file_path),
        filename=backup_name,
        media_type="application/gzip",
    )


# --------------------------------------------------------------------------
# DELETE /{id}/backup/{backup_name} -- delete a specific backup
# --------------------------------------------------------------------------
@router.delete("/{db_id}/backup/{backup_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    db_id: uuid.UUID,
    backup_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from agent.executors.database_executor import delete_database_backup

    record = await _get_db_or_404(db_id, db, current_user)
    username = await _get_username(record.user_id, db)

    try:
        delete_database_backup(username=username, backup_name=backup_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    _log(db, request, current_user.id, "databases.backup_delete", f"Deleted backup {backup_name} of {record.db_name}")
