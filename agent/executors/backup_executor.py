"""
Backup executor — create, restore, delete, and list backups.

Backup types:
  - "full"  — home directory + all MySQL & PostgreSQL databases for the user
  - "files" — home directory only
  - "db"    — databases only
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.executors._helpers import safe_path, safe_username

BACKUP_BASE = Path("/opt/hosthive/backups")
HOME_BASE = Path("/home")


def _user_backup_dir(username: str) -> Path:
    d = BACKUP_BASE / username
    d.mkdir(parents=True, exist_ok=True)
    return d


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------


def create_backup(username: str, backup_type: str = "full") -> dict[str, Any]:
    """Create a backup archive.

    *backup_type* is one of: ``full``, ``files``, ``db``.
    """
    username = safe_username(username)
    if backup_type not in ("full", "files", "db"):
        raise ValueError(f"invalid backup_type: {backup_type!r}")

    ts = _timestamp()
    backup_dir = _user_backup_dir(username)
    archive_name = f"{username}_{backup_type}_{ts}.tar.gz"
    archive_path = backup_dir / archive_name

    home_dir = HOME_BASE / username
    temp_dir = backup_dir / f".tmp_{ts}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        items_to_tar: list[str] = []

        # --- files ---
        if backup_type in ("full", "files"):
            if home_dir.is_dir():
                items_to_tar.append(str(home_dir))

        # --- databases ---
        if backup_type in ("full", "db"):
            # MySQL
            mysql_dump = temp_dir / "mysql_dump.sql"
            r = subprocess.run(
                [
                    "mysqldump",
                    "--all-databases",
                    f"--user={username}",
                    f"--result-file={mysql_dump}",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0 and mysql_dump.exists():
                items_to_tar.append(str(mysql_dump))

            # PostgreSQL
            pg_dump = temp_dir / "pg_dumpall.sql"
            r = subprocess.run(
                [
                    "sudo", "-u", "postgres",
                    "pg_dumpall",
                    f"--file={pg_dump}",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0 and pg_dump.exists():
                items_to_tar.append(str(pg_dump))

        if not items_to_tar:
            raise RuntimeError("nothing to back up")

        # Create tar.gz
        r = subprocess.run(
            ["tar", "-czf", str(archive_path)] + items_to_tar,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"tar failed: {r.stderr}")

    finally:
        # Cleanup temp directory
        subprocess.run(["rm", "-rf", str(temp_dir)], capture_output=True, timeout=30)

    size = archive_path.stat().st_size
    return {
        "username": username,
        "backup_type": backup_type,
        "file": str(archive_path),
        "size_bytes": size,
    }


# ------------------------------------------------------------------
# Restore
# ------------------------------------------------------------------


def restore_backup(username: str, backup_file: str) -> dict[str, Any]:
    """Restore a backup archive."""
    username = safe_username(username)
    backup_file = safe_path(backup_file, str(BACKUP_BASE / username))

    if not Path(backup_file).exists():
        raise FileNotFoundError(f"backup file not found: {backup_file}")

    # Extract to a temporary location first
    temp_dir = BACKUP_BASE / username / f".restore_{_timestamp()}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        r = subprocess.run(
            ["tar", "-xzf", backup_file, "-C", str(temp_dir)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"tar extract failed: {r.stderr}")

        restored: list[str] = []

        # Restore home directory if present
        home_extracted = temp_dir / "home" / username
        if home_extracted.is_dir():
            r = subprocess.run(
                ["rsync", "-a", str(home_extracted) + "/", str(HOME_BASE / username) + "/"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                restored.append("files")

        # Restore MySQL dump
        mysql_dump = None
        for candidate in temp_dir.rglob("mysql_dump.sql"):
            mysql_dump = candidate
            break
        if mysql_dump and mysql_dump.exists():
            r = subprocess.run(
                ["mysql", f"--user={username}", f"--execute=source {mysql_dump}"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                restored.append("mysql")

        # Restore PostgreSQL dump
        pg_dump = None
        for candidate in temp_dir.rglob("pg_dumpall.sql"):
            pg_dump = candidate
            break
        if pg_dump and pg_dump.exists():
            r = subprocess.run(
                ["sudo", "-u", "postgres", "psql", "-f", str(pg_dump)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                restored.append("postgres")

    finally:
        subprocess.run(["rm", "-rf", str(temp_dir)], capture_output=True, timeout=30)

    return {"username": username, "backup_file": backup_file, "restored": restored}


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


def delete_backup(backup_file: str) -> dict[str, Any]:
    """Delete a backup file with strict path validation."""
    backup_file = safe_path(backup_file, str(BACKUP_BASE))

    p = Path(backup_file)
    if not p.exists():
        raise FileNotFoundError(f"backup file not found: {backup_file}")

    os.unlink(backup_file)
    return {"deleted": backup_file}


# ------------------------------------------------------------------
# List
# ------------------------------------------------------------------


def list_backups(username: str) -> list[dict[str, Any]]:
    """List all backups for a given user."""
    username = safe_username(username)
    backup_dir = BACKUP_BASE / username

    if not backup_dir.is_dir():
        return []

    backups = []
    for entry in sorted(backup_dir.iterdir()):
        if entry.is_file() and entry.name.endswith(".tar.gz"):
            stat = entry.stat()
            backups.append({
                "file": str(entry),
                "name": entry.name,
                "size_bytes": stat.st_size,
                "created": datetime.utcfromtimestamp(stat.st_ctime).isoformat(),
            })

    return backups
