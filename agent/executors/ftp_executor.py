"""
FTP executor — ProFTPD virtual user management.

Manages users in /etc/proftpd/ftpd.passwd using ftpasswd-style entries.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from agent.executors._helpers import atomic_write, safe_path, safe_username

FTPD_PASSWD = Path("/etc/proftpd/ftpd.passwd")

# UID/GID for the virtual FTP user — typically mapped to a dedicated system user
FTP_UID = 1001
FTP_GID = 1001


def _hash_password(password: str) -> str:
    """Hash password using OpenSSL (SHA-256 based crypt)."""
    result = subprocess.run(
        ["openssl", "passwd", "-6", password],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"openssl passwd failed: {result.stderr}")
    return result.stdout.strip()


def _read_passwd() -> list[str]:
    if FTPD_PASSWD.exists():
        return FTPD_PASSWD.read_text().splitlines()
    return []


def _write_passwd(lines: list[str]) -> None:
    FTPD_PASSWD.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(FTPD_PASSWD, "\n".join(lines) + "\n" if lines else "", mode=0o600)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def create_ftp_user(username: str, password: str, home_dir: str) -> dict[str, Any]:
    """Create a virtual FTP user in the ProFTPD passwd file."""
    username = safe_username(username)
    home_dir = safe_path(home_dir, "/home")
    pw_hash = _hash_password(password)

    lines = _read_passwd()
    for line in lines:
        if line.startswith(f"{username}:"):
            raise ValueError(f"FTP user already exists: {username}")

    # Format: username:password:uid:gid:gecos:home:shell
    entry = f"{username}:{pw_hash}:{FTP_UID}:{FTP_GID}:HostHive FTP user:{home_dir}:/sbin/nologin"
    lines.append(entry)
    _write_passwd(lines)

    # Ensure home directory exists
    Path(home_dir).mkdir(parents=True, exist_ok=True)

    return {"username": username, "home_dir": home_dir}


def delete_ftp_user(username: str) -> dict[str, Any]:
    """Remove a virtual FTP user."""
    username = safe_username(username)

    lines = _read_passwd()
    new_lines = [l for l in lines if not l.startswith(f"{username}:")]
    if len(new_lines) == len(lines):
        raise ValueError(f"FTP user not found: {username}")

    _write_passwd(new_lines)
    return {"username": username, "deleted": True}


def set_ftp_password(username: str, password: str) -> dict[str, Any]:
    """Update the password for an existing FTP user."""
    username = safe_username(username)
    pw_hash = _hash_password(password)

    lines = _read_passwd()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{username}:"):
            parts = line.split(":")
            parts[1] = pw_hash
            lines[i] = ":".join(parts)
            found = True
            break

    if not found:
        raise ValueError(f"FTP user not found: {username}")

    _write_passwd(lines)
    return {"username": username, "password_changed": True}
