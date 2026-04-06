"""
Backup executor — create, restore, delete, and list backups.

Backup types:
  - "full"        — home directory + all MySQL & PostgreSQL databases for the user
  - "incremental" — rsync --link-dest against previous backup (files) + DB dump
  - "files"       — home directory only
  - "db"          — databases only
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
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
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------


def _dump_databases(username: str, dest_dir: Path) -> list[str]:
    """Dump MySQL and PostgreSQL databases into *dest_dir*.

    Returns list of successfully dumped engines (e.g. ["mysql", "postgres"]).
    """
    dumped: list[str] = []

    mysql_dump = dest_dir / "mysql_dump.sql"
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
        dumped.append("mysql")

    pg_dump = dest_dir / "pg_dumpall.sql"
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
        dumped.append("postgres")

    return dumped


def create_backup(
    username: str,
    backup_type: str = "full",
    parent_backup_path: str | None = None,
) -> dict[str, Any]:
    """Create a backup archive.

    *backup_type* is one of: ``full``, ``incremental``, ``files``, ``db``.

    For **incremental** backups, *parent_backup_path* should point to the
    directory of the previous (full or incremental) backup snapshot.  The
    executor uses ``rsync -a --link-dest`` so that unchanged files are
    hard-linked to the parent, saving disk space.
    """
    username = safe_username(username)
    if backup_type not in ("full", "incremental", "files", "db"):
        raise ValueError(f"invalid backup_type: {backup_type!r}")

    ts = _timestamp()
    backup_dir = _user_backup_dir(username)
    home_dir = HOME_BASE / username

    # ---- incremental backup (rsync --link-dest) -------------------------
    if backup_type == "incremental":
        return _create_incremental_backup(
            username, backup_dir, home_dir, ts, parent_backup_path,
        )

    # ---- full / files / db (original tar-based flow) --------------------
    archive_name = f"{username}_{backup_type}_{ts}.tar.gz"
    archive_path = backup_dir / archive_name

    temp_dir = backup_dir / f".tmp_{ts}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        items_to_tar: list[str] = []

        if backup_type in ("full", "files"):
            if home_dir.is_dir():
                items_to_tar.append(str(home_dir))

        if backup_type in ("full", "db"):
            dumped = _dump_databases(username, temp_dir)
            for engine in dumped:
                if engine == "mysql":
                    items_to_tar.append(str(temp_dir / "mysql_dump.sql"))
                elif engine == "postgres":
                    items_to_tar.append(str(temp_dir / "pg_dumpall.sql"))

        if not items_to_tar:
            raise RuntimeError("nothing to back up")

        r = subprocess.run(
            ["tar", "-czf", str(archive_path)] + items_to_tar,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"tar failed: {r.stderr}")

    finally:
        subprocess.run(["rm", "-rf", str(temp_dir)], capture_output=True, timeout=30)

    size = archive_path.stat().st_size
    return {
        "username": username,
        "backup_type": backup_type,
        "file": str(archive_path),
        "size_bytes": size,
    }


def _parse_rsync_stats(stderr: str) -> dict[str, Any]:
    """Extract useful numbers from rsync --stats output."""
    stats: dict[str, Any] = {}
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("Number of files:"):
            stats["total_files"] = line.split(":", 1)[1].strip()
        elif line.startswith("Number of regular files transferred:"):
            stats["files_transferred"] = line.split(":", 1)[1].strip()
        elif line.startswith("Total file size:"):
            stats["total_file_size"] = line.split(":", 1)[1].strip()
        elif line.startswith("Total transferred file size:"):
            stats["transferred_size"] = line.split(":", 1)[1].strip()
    return stats


def _create_incremental_backup(
    username: str,
    backup_dir: Path,
    home_dir: Path,
    ts: str,
    parent_backup_path: str | None,
) -> dict[str, Any]:
    """Create an incremental backup using rsync --link-dest.

    The backup is stored as a plain directory snapshot (not a tar).  Files
    unchanged since *parent_backup_path* are hard-linked, so they consume
    almost no extra disk space.  A companion DB dump is always created fresh
    (full dump) and placed inside the snapshot directory under `_dbdumps/`.
    """
    snapshot_name = f"{username}_incremental_{ts}"
    snapshot_dir = backup_dir / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    metadata: dict[str, Any] = {
        "parent_backup_path": parent_backup_path,
        "type": "incremental",
    }

    # --- rsync files with --link-dest for deduplication ------------------
    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    rsync_cmd = [
        "rsync", "-a", "--stats", "--delete",
    ]
    if parent_backup_path:
        # The parent path should point to the *files* subdirectory of the
        # previous incremental snapshot, or the extracted home dir.
        parent_files = Path(parent_backup_path) / "files"
        if parent_files.is_dir():
            rsync_cmd += [f"--link-dest={parent_files}"]
        elif Path(parent_backup_path).is_dir():
            rsync_cmd += [f"--link-dest={parent_backup_path}"]

    if home_dir.is_dir():
        rsync_cmd += [str(home_dir) + "/", str(files_dir) + "/"]

        r = subprocess.run(
            rsync_cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode not in (0, 24):
            # 24 = "vanished source files" which is non-fatal
            raise RuntimeError(f"rsync failed (rc={r.returncode}): {r.stderr}")

        rsync_stats = _parse_rsync_stats(r.stdout + r.stderr)
        metadata["rsync_stats"] = rsync_stats
    else:
        metadata["rsync_stats"] = {"note": "home directory not found, skipped"}

    # --- database dumps (always full, stored inside the snapshot) --------
    db_dir = snapshot_dir / "_dbdumps"
    db_dir.mkdir(parents=True, exist_ok=True)
    dumped = _dump_databases(username, db_dir)
    metadata["db_engines_dumped"] = dumped

    # --- compute total size (du) -----------------------------------------
    r = subprocess.run(
        ["du", "-sb", str(snapshot_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode == 0:
        size = int(r.stdout.split()[0])
    else:
        size = 0

    metadata["snapshot_dir"] = str(snapshot_dir)

    # Write metadata file inside the snapshot for self-documentation
    meta_file = snapshot_dir / "_incremental_meta.json"
    meta_file.write_text(json.dumps(metadata, indent=2, default=str))

    return {
        "username": username,
        "backup_type": "incremental",
        "file": str(snapshot_dir),
        "size_bytes": size,
        "metadata": metadata,
    }


# ------------------------------------------------------------------
# Restore
# ------------------------------------------------------------------


def _restore_db_dumps(search_root: Path, username: str) -> list[str]:
    """Restore MySQL and PostgreSQL dumps found under *search_root*."""
    restored: list[str] = []

    mysql_dump = None
    for candidate in search_root.rglob("mysql_dump.sql"):
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

    pg_dump = None
    for candidate in search_root.rglob("pg_dumpall.sql"):
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

    return restored


def _restore_emails(source_dir: Path, dest_dir: Path, username: str) -> bool:
    """Restore email directories (Maildir) from backup to user home."""
    # Look for common mail directory patterns
    for mail_dir_name in ("Maildir", "mail", ".mail"):
        mail_source = source_dir / mail_dir_name
        if mail_source.is_dir():
            mail_dest = dest_dir / mail_dir_name
            r = subprocess.run(
                ["rsync", "-a", str(mail_source) + "/", str(mail_dest) + "/"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                # Fix ownership
                subprocess.run(
                    ["chown", "-R", f"{username}:{username}", str(mail_dest)],
                    capture_output=True,
                    timeout=60,
                )
                return True
    return False


def _restore_cron(source_dir: Path, username: str) -> bool:
    """Restore crontab from backup."""
    # Look for saved crontab file in the backup
    for cron_file_name in ("crontab", "crontab.bak", ".crontab"):
        cron_file = source_dir / cron_file_name
        if cron_file.is_file():
            r = subprocess.run(
                ["crontab", "-u", username, str(cron_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return r.returncode == 0

    # Also check inside a _cron/ subdirectory
    cron_dir = source_dir / "_cron"
    if cron_dir.is_dir():
        for f in cron_dir.iterdir():
            if f.is_file():
                r = subprocess.run(
                    ["crontab", "-u", username, str(f)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r.returncode == 0:
                    return True
    return False


def restore_backup(
    username: str,
    backup_file: str,
    restore_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Restore a backup archive or incremental snapshot directory.

    *restore_options* controls which parts of the backup to restore:
      - restore_files (bool, default True)
      - restore_databases (bool, default True)
      - restore_emails (bool, default False)
      - restore_cron (bool, default False)
      - target_path (str|None) -- custom restore path overriding /home/{username}
    """
    username = safe_username(username)
    backup_file = safe_path(backup_file, str(BACKUP_BASE / username))
    backup_path = Path(backup_file)

    if not backup_path.exists():
        raise FileNotFoundError(f"backup file not found: {backup_file}")

    # Defaults
    opts = restore_options or {}
    do_files = opts.get("restore_files", True)
    do_databases = opts.get("restore_databases", True)
    do_emails = opts.get("restore_emails", False)
    do_cron = opts.get("restore_cron", False)
    target_path = opts.get("target_path")

    restore_dest = Path(target_path) if target_path else HOME_BASE / username

    # ------- Incremental snapshot (directory) ----------------------------
    if backup_path.is_dir():
        restored: list[str] = []

        files_dir = backup_path / "files"

        # Restore files from the snapshot's files/ subdirectory
        if do_files and files_dir.is_dir():
            r = subprocess.run(
                ["rsync", "-a", "--delete",
                 str(files_dir) + "/", str(restore_dest) + "/"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                restored.append("files")

        # Restore DB dumps from _dbdumps/
        if do_databases:
            db_dir = backup_path / "_dbdumps"
            if db_dir.is_dir():
                restored.extend(_restore_db_dumps(db_dir, username))

        # Restore emails from the files directory
        if do_emails and files_dir.is_dir():
            if _restore_emails(files_dir, restore_dest, username):
                restored.append("emails")

        # Restore cron
        if do_cron:
            if _restore_cron(backup_path, username):
                restored.append("cron")

        return {"username": username, "backup_file": backup_file, "restored": restored}

    # ------- Tar archive (full / files / db) -----------------------------
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

        restored = []

        home_extracted = temp_dir / "home" / username

        if do_files and home_extracted.is_dir():
            r = subprocess.run(
                ["rsync", "-a", str(home_extracted) + "/", str(restore_dest) + "/"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                restored.append("files")

        if do_databases:
            restored.extend(_restore_db_dumps(temp_dir, username))

        if do_emails and home_extracted.is_dir():
            if _restore_emails(home_extracted, restore_dest, username):
                restored.append("emails")

        if do_cron:
            if _restore_cron(temp_dir, username):
                restored.append("cron")

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
