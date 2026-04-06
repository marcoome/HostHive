"""
Database executor — MySQL and PostgreSQL database/user management.

All subprocess calls use list arguments.  shell=True is NEVER used.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

_DB_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")
_DB_USER_RE = re.compile(r"^[a-zA-Z0-9_]{1,32}$")


def _validate_db_name(name: str) -> str:
    name = name.strip()
    if not _DB_NAME_RE.match(name):
        raise ValueError(f"invalid database name: {name!r}")
    return name


def _validate_db_user(user: str) -> str:
    user = user.strip()
    if not _DB_USER_RE.match(user):
        raise ValueError(f"invalid database user: {user!r}")
    return user


def _escape_mysql(value: str) -> str:
    """Escape a string value for safe inclusion in a MySQL single-quoted literal.

    Handles backslashes first (to avoid double-escaping), then single quotes.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("'", "\\'")
    return value


def _escape_pg(value: str) -> str:
    """Escape a string value for safe inclusion in a PostgreSQL single-quoted literal.

    PostgreSQL uses '' (doubled single quote) as the escape for a literal quote
    inside a standard string. Also escape backslashes for safety.
    """
    value = value.replace("'", "''")
    return value


def _escape_pg_dollar(value: str) -> str:
    """Escape a string for use inside a PostgreSQL dollar-quoted block (DO $$ ... $$).

    Inside a dollar-quoted body, standard SQL quoting applies to inner string
    literals — so single quotes must be doubled.
    """
    value = value.replace("'", "''")
    return value


def _run_mysql(sql: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Execute a MySQL statement via the mysql CLI."""
    return subprocess.run(
        ["mysql", "--batch", "--skip-column-names", "-e", sql],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_psql(sql: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Execute a PostgreSQL statement via psql as the postgres user."""
    return subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-t", "-A", "-c", sql],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ------------------------------------------------------------------
# MySQL
# ------------------------------------------------------------------


def create_mysql_db(db_name: str, db_user: str, db_password: str) -> dict[str, Any]:
    """Create a MySQL database and a user with full privileges on it."""
    db_name = _validate_db_name(db_name)
    db_user = _validate_db_user(db_user)

    safe_user = _escape_mysql(db_user)
    safe_pass = _escape_mysql(db_password)

    stmts = [
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"CREATE USER IF NOT EXISTS '{safe_user}'@'localhost' IDENTIFIED BY '{safe_pass}';",
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{safe_user}'@'localhost';",
        "FLUSH PRIVILEGES;",
    ]

    results = []
    for sql in stmts:
        r = _run_mysql(sql)
        results.append({"sql": sql.split("'")[0] + "...", "rc": r.returncode, "err": r.stderr.strip()})
        if r.returncode != 0:
            raise RuntimeError(f"MySQL error: {r.stderr.strip()}")

    return {"db_name": db_name, "db_user": db_user, "steps": results}


def delete_mysql_db(db_name: str, db_user: str) -> dict[str, Any]:
    """Drop a MySQL database and user."""
    db_name = _validate_db_name(db_name)
    db_user = _validate_db_user(db_user)

    safe_user = _escape_mysql(db_user)

    stmts = [
        f"DROP DATABASE IF EXISTS `{db_name}`;",
        f"DROP USER IF EXISTS '{safe_user}'@'localhost';",
        "FLUSH PRIVILEGES;",
    ]

    for sql in stmts:
        r = _run_mysql(sql)
        if r.returncode != 0:
            raise RuntimeError(f"MySQL error: {r.stderr.strip()}")

    return {"db_name": db_name, "db_user": db_user, "deleted": True}


# ------------------------------------------------------------------
# PostgreSQL
# ------------------------------------------------------------------


def create_postgres_db(db_name: str, db_user: str, db_password: str) -> dict[str, Any]:
    """Create a PostgreSQL database and role."""
    db_name = _validate_db_name(db_name)
    db_user = _validate_db_user(db_user)

    safe_user = _escape_pg(db_user)
    safe_pass_dollar = _escape_pg_dollar(db_password)
    safe_name = _escape_pg(db_name)

    # Create role if not exists
    r = _run_psql(
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{safe_user}') THEN "
        f"CREATE ROLE {db_user} LOGIN PASSWORD '{safe_pass_dollar}'; "
        f"END IF; END $$;"
    )
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL error: {r.stderr.strip()}")

    # Create database
    # Can't use IF NOT EXISTS in CREATE DATABASE easily, so check first
    check = _run_psql(f"SELECT 1 FROM pg_database WHERE datname = '{safe_name}';")
    if "1" not in (check.stdout or ""):
        r = subprocess.run(
            ["sudo", "-u", "postgres", "createdb", "-O", db_user, db_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"PostgreSQL error: {r.stderr.strip()}")

    # Grant — db_name and db_user are validated as alphanumeric+underscore,
    # so they are safe as SQL identifiers without quoting here.
    r = _run_psql(f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};")
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL error: {r.stderr.strip()}")

    return {"db_name": db_name, "db_user": db_user}


def delete_postgres_db(db_name: str, db_user: str) -> dict[str, Any]:
    """Drop a PostgreSQL database and role."""
    db_name = _validate_db_name(db_name)
    db_user = _validate_db_user(db_user)

    # Drop DB
    r = subprocess.run(
        ["sudo", "-u", "postgres", "dropdb", "--if-exists", db_name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL error: {r.stderr.strip()}")

    # Drop role
    r = _run_psql(f"DROP ROLE IF EXISTS {db_user};")
    if r.returncode != 0:
        raise RuntimeError(f"PostgreSQL error: {r.stderr.strip()}")

    return {"db_name": db_name, "db_user": db_user, "deleted": True}


# ------------------------------------------------------------------
# Backup & Restore
# ------------------------------------------------------------------

import glob
import gzip
import os
from datetime import datetime, timezone
from pathlib import Path

_BACKUP_BASE = "/opt/hosthive/backups"


def _backup_dir_for_user(username: str) -> Path:
    """Return (and create) the backup directory for a user."""
    p = Path(_BACKUP_BASE) / username / "databases"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backup_database(
    db_name: str,
    db_type: str,
    username: str,
) -> dict[str, Any]:
    """Dump a database to a gzipped SQL file.

    Returns {"path": "<absolute path>", "filename": "...", "size": <bytes>}.
    """
    db_name = _validate_db_name(db_name)
    dest = _backup_dir_for_user(username)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{db_name}_{ts}.sql.gz"
    output_path = dest / filename

    if db_type == "mysql":
        # mysqldump piped through gzip
        dump = subprocess.run(
            ["mysqldump", "--single-transaction", "--routines", "--triggers", db_name],
            capture_output=True,
            timeout=600,
        )
        if dump.returncode != 0:
            raise RuntimeError(f"mysqldump failed: {dump.stderr.decode(errors='replace').strip()}")
        with gzip.open(output_path, "wb") as f:
            f.write(dump.stdout)
    elif db_type == "postgresql":
        dump = subprocess.run(
            ["sudo", "-u", "postgres", "pg_dump", db_name],
            capture_output=True,
            timeout=600,
        )
        if dump.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {dump.stderr.decode(errors='replace').strip()}")
        with gzip.open(output_path, "wb") as f:
            f.write(dump.stdout)
    else:
        raise ValueError(f"unsupported db_type: {db_type}")

    return {
        "path": str(output_path),
        "filename": filename,
        "size": output_path.stat().st_size,
    }


def restore_database(
    db_name: str,
    db_type: str,
    input_path: str,
) -> dict[str, Any]:
    """Restore a database from a (possibly gzipped) SQL dump.

    ``input_path`` must be an existing file.
    """
    db_name = _validate_db_name(db_name)
    p = Path(input_path)
    if not p.is_file():
        raise FileNotFoundError(f"backup file not found: {input_path}")

    # Read, decompressing if needed
    if p.suffix == ".gz":
        with gzip.open(p, "rb") as f:
            sql_bytes = f.read()
    else:
        sql_bytes = p.read_bytes()

    if db_type == "mysql":
        r = subprocess.run(
            ["mysql", db_name],
            input=sql_bytes,
            capture_output=True,
            timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"mysql restore failed: {r.stderr.decode(errors='replace').strip()}")
    elif db_type == "postgresql":
        r = subprocess.run(
            ["sudo", "-u", "postgres", "psql", db_name],
            input=sql_bytes,
            capture_output=True,
            timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"psql restore failed: {r.stderr.decode(errors='replace').strip()}")
    else:
        raise ValueError(f"unsupported db_type: {db_type}")

    return {"db_name": db_name, "restored_from": str(p)}


def list_database_backups(username: str, db_name: str | None = None) -> list[dict[str, Any]]:
    """List backup files for a user, optionally filtered by db_name prefix.

    Returns a list of dicts with keys: filename, path, size, created_at.
    """
    dest = _backup_dir_for_user(username)
    pattern = f"{db_name}_*.sql.gz" if db_name else "*.sql.gz"
    files = sorted(dest.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)

    results: list[dict[str, Any]] = []
    for f in files:
        stat = f.stat()
        results.append({
            "filename": f.name,
            "path": str(f),
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return results


def delete_database_backup(username: str, backup_name: str) -> dict[str, Any]:
    """Delete a specific backup file. Returns {"deleted": True}."""
    # Sanitise: only allow filenames, no path traversal
    if "/" in backup_name or "\\" in backup_name or ".." in backup_name:
        raise ValueError("invalid backup name")
    dest = _backup_dir_for_user(username)
    target = dest / backup_name
    if not target.is_file():
        raise FileNotFoundError(f"backup not found: {backup_name}")
    target.unlink()
    return {"deleted": True, "filename": backup_name}
