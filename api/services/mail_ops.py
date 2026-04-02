"""Direct mail operations -- fallback when the agent is unavailable.

All functions are async wrappers around subprocess calls so they integrate
naturally with the FastAPI async router.  Every public function returns a
dict with results and never raises -- callers check ``result["ok"]``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VIRTUAL_MAILBOX_DIR = Path("/var/mail/vhosts")
DOVECOT_VIRTUAL_USERS = Path("/etc/dovecot/virtual_users")
EXIM_VIRTUAL_ALIASES = Path("/etc/exim4/virtual_aliases")

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _validate_email(address: str) -> str:
    address = address.strip().lower()
    if not _EMAIL_RE.match(address):
        raise ValueError(f"Invalid email address: {address!r}")
    return address


async def _run(cmd: list[str], timeout: int = 30) -> asyncio.subprocess.Process:
    """Run a command asynchronously and return the completed process."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    return proc


async def _hash_password(password: str) -> str:
    """Generate a SHA512-CRYPT hash using doveadm, with a fallback."""
    try:
        proc = await _run(["doveadm", "pw", "-s", "SHA512-CRYPT", "-p", password], timeout=10)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode().strip()
    except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
        logger.warning("doveadm not available, using fallback hash: %s", exc)

    # Fallback: SSHA256 via hashlib
    salt = os.urandom(16)
    h = hashlib.sha256(password.encode("utf-8") + salt).hexdigest()
    return "{SSHA256}" + h


def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    """Write *content* to *path* atomically via a temp file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(str(tmp), mode)
    tmp.rename(path)


# ------------------------------------------------------------------
# Mailbox operations
# ------------------------------------------------------------------

async def create_mailbox_direct(address: str, password: str, quota_mb: int = 1024) -> dict[str, Any]:
    """Create a Dovecot virtual mailbox + mail directory on disk."""
    try:
        address = _validate_email(address)
        user, domain = address.split("@")

        pw_hash = await _hash_password(password)

        # Dovecot virtual_users line:
        # user@domain:{scheme}hash:vmail:vmail::/var/mail/vhosts/domain/user::userdb_quota_rule=*:storage=NNM
        line = (
            f"{address}:{pw_hash}:vmail:vmail::"
            f"{VIRTUAL_MAILBOX_DIR}/{domain}/{user}::"
            f"userdb_quota_rule=*:storage={quota_mb}M"
        )

        # Append to virtual_users (create if missing)
        DOVECOT_VIRTUAL_USERS.parent.mkdir(parents=True, exist_ok=True)
        existing = DOVECOT_VIRTUAL_USERS.read_text() if DOVECOT_VIRTUAL_USERS.exists() else ""

        if any(l.startswith(f"{address}:") for l in existing.splitlines()):
            return {"ok": True, "detail": "Entry already present in virtual_users"}

        _atomic_write(
            DOVECOT_VIRTUAL_USERS,
            existing.rstrip("\n") + "\n" + line + "\n",
            mode=0o600,
        )

        # Create Maildir structure
        maildir = VIRTUAL_MAILBOX_DIR / domain / user
        for sub in ("cur", "new", "tmp"):
            (maildir / sub).mkdir(parents=True, exist_ok=True)

        # Set ownership to vmail (uid/gid 5000 is conventional)
        try:
            await _run(["chown", "-R", "vmail:vmail", str(VIRTUAL_MAILBOX_DIR / domain / user)])
        except Exception as exc:
            logger.warning("Could not chown maildir: %s", exc)

        return {"ok": True, "address": address, "maildir": str(maildir)}

    except Exception as exc:
        logger.error("create_mailbox_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def delete_mailbox_direct(address: str, remove_directory: bool = False) -> dict[str, Any]:
    """Remove a mailbox entry from Dovecot virtual_users.  Optionally remove mail dir."""
    try:
        address = _validate_email(address)

        # Remove from virtual_users
        if DOVECOT_VIRTUAL_USERS.exists():
            lines = DOVECOT_VIRTUAL_USERS.read_text().splitlines(keepends=True)
            new_lines = [l for l in lines if not l.startswith(f"{address}:")]
            _atomic_write(DOVECOT_VIRTUAL_USERS, "".join(new_lines), mode=0o600)

        # Optionally remove mail directory
        if remove_directory:
            user, domain = address.split("@")
            maildir = VIRTUAL_MAILBOX_DIR / domain / user
            if maildir.exists():
                try:
                    await _run(["rm", "-rf", str(maildir)])
                except Exception as exc:
                    logger.warning("Could not remove maildir %s: %s", maildir, exc)

        return {"ok": True, "address": address, "deleted": True}

    except Exception as exc:
        logger.error("delete_mailbox_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------
# Alias operations
# ------------------------------------------------------------------

async def create_alias_direct(source: str, destination: str) -> dict[str, Any]:
    """Add an entry to Exim4 virtual_aliases file."""
    try:
        source = _validate_email(source)
        destination = _validate_email(destination)

        EXIM_VIRTUAL_ALIASES.parent.mkdir(parents=True, exist_ok=True)
        existing = EXIM_VIRTUAL_ALIASES.read_text() if EXIM_VIRTUAL_ALIASES.exists() else ""

        line = f"{source}: {destination}"
        if line in existing:
            return {"ok": True, "detail": "Alias already present in virtual_aliases"}

        _atomic_write(
            EXIM_VIRTUAL_ALIASES,
            existing.rstrip("\n") + "\n" + line + "\n",
            mode=0o644,
        )

        return {"ok": True, "source": source, "destination": destination}

    except Exception as exc:
        logger.error("create_alias_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def delete_alias_direct(source: str) -> dict[str, Any]:
    """Remove an alias from the Exim4 virtual_aliases file by source address."""
    try:
        source = _validate_email(source)

        if not EXIM_VIRTUAL_ALIASES.exists():
            return {"ok": True, "detail": "Aliases file does not exist, nothing to remove"}

        lines = EXIM_VIRTUAL_ALIASES.read_text().splitlines(keepends=True)
        new_lines = [l for l in lines if not l.startswith(f"{source}:")]
        _atomic_write(EXIM_VIRTUAL_ALIASES, "".join(new_lines), mode=0o644)

        return {"ok": True, "source": source, "deleted": True}

    except Exception as exc:
        logger.error("delete_alias_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def list_aliases_direct() -> dict[str, Any]:
    """Read all aliases from the Exim4 virtual_aliases file."""
    try:
        if not EXIM_VIRTUAL_ALIASES.exists():
            return {"ok": True, "aliases": []}

        aliases = []
        for line in EXIM_VIRTUAL_ALIASES.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                src, dst = line.split(":", 1)
                aliases.append({
                    "source": src.strip(),
                    "destination": dst.strip(),
                })

        return {"ok": True, "aliases": aliases}

    except Exception as exc:
        logger.error("list_aliases_direct failed: %s", exc)
        return {"ok": False, "aliases": [], "error": str(exc)}


# ------------------------------------------------------------------
# Mail queue operations
# ------------------------------------------------------------------

async def get_mail_queue() -> dict[str, Any]:
    """List the Exim4 mail queue."""
    try:
        proc = await _run(["exim", "-bp"], timeout=30)
        raw = proc.stdout.decode() if proc.stdout else ""
        lines = [l for l in raw.strip().splitlines() if l.strip()]
        return {"ok": True, "count": len(lines), "raw": raw, "queue": lines}

    except FileNotFoundError:
        return {"ok": False, "error": "exim binary not found", "queue": []}
    except Exception as exc:
        logger.error("get_mail_queue failed: %s", exc)
        return {"ok": False, "error": str(exc), "queue": []}


async def remove_from_queue(message_id: str) -> dict[str, Any]:
    """Remove a single message from the Exim4 queue."""
    try:
        # Sanitise message_id
        if not re.match(r"^[a-zA-Z0-9-]+$", message_id):
            return {"ok": False, "error": "Invalid message ID format"}

        proc = await _run(["exim", "-Mrm", message_id], timeout=15)
        stderr = proc.stderr.decode() if proc.stderr else ""
        return {
            "ok": proc.returncode == 0,
            "message_id": message_id,
            "detail": stderr.strip() if stderr else "removed",
        }

    except Exception as exc:
        logger.error("remove_from_queue failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def flush_mail_queue() -> dict[str, Any]:
    """Force delivery attempt on all queued messages."""
    try:
        proc = await _run(["exim", "-qf"], timeout=60)
        stdout = proc.stdout.decode() if proc.stdout else ""
        stderr = proc.stderr.decode() if proc.stderr else ""
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    except FileNotFoundError:
        return {"ok": False, "error": "exim binary not found"}
    except Exception as exc:
        logger.error("flush_mail_queue failed: %s", exc)
        return {"ok": False, "error": str(exc)}
