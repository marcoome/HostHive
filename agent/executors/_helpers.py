"""
Shared helpers used across all executors.

Security-critical utilities: path validation, domain sanitisation, atomic writes.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# Strict domain regex: labels of alphanum/hyphens separated by dots.
_DOMAIN_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*$")
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def safe_domain(domain: str) -> str:
    """Validate and return *domain*, or raise ValueError."""
    domain = domain.strip().lower()
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"invalid domain name: {domain!r}")
    if len(domain) > 253:
        raise ValueError("domain name too long")
    return domain


def safe_path(path: str, required_prefix: str) -> str:
    """Resolve *path* and ensure it starts with *required_prefix*.

    Prevents directory-traversal attacks.
    """
    resolved = os.path.realpath(path)
    prefix = os.path.realpath(required_prefix)
    if not resolved.startswith(prefix + os.sep) and resolved != prefix:
        raise ValueError(
            f"path {path!r} resolves outside allowed prefix {required_prefix!r}"
        )
    return resolved


def safe_username(username: str) -> str:
    """Validate a Unix username."""
    username = username.strip()
    if not _USERNAME_RE.match(username):
        raise ValueError(f"invalid username: {username!r}")
    return username


def atomic_write(target: Path | str, content: str, mode: int = 0o644) -> None:
    """Write *content* to *target* atomically via a temp file + rename."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.rename(tmp, str(target))
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_bytes(target: Path | str, data: bytes, mode: int = 0o600) -> None:
    """Binary variant of atomic_write."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.rename(tmp, str(target))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def increment_serial(serial: str) -> str:
    """Increment a BIND SOA serial of the form YYYYMMDDNN."""
    from datetime import date as _date

    today = _date.today().strftime("%Y%m%d")
    if serial[:8] == today:
        nn = int(serial[8:]) + 1
        return f"{today}{nn:02d}"
    return f"{today}01"
