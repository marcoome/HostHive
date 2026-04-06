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


async def set_password_direct(address: str, new_password: str) -> dict[str, Any]:
    """Update the password hash for an existing mailbox in Dovecot virtual_users."""
    try:
        address = _validate_email(address)
        pw_hash = await _hash_password(new_password)

        if not DOVECOT_VIRTUAL_USERS.exists():
            return {"ok": False, "error": "Dovecot virtual_users file does not exist"}

        lines = DOVECOT_VIRTUAL_USERS.read_text().splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{address}:"):
                parts = line.split(":")
                parts[1] = pw_hash
                lines[i] = ":".join(parts)
                found = True
                break

        if not found:
            return {"ok": False, "error": f"Mailbox not found in virtual_users: {address}"}

        _atomic_write(DOVECOT_VIRTUAL_USERS, "\n".join(lines) + "\n", mode=0o600)
        return {"ok": True, "address": address, "password_changed": True}

    except Exception as exc:
        logger.error("set_password_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def get_quota_usage_direct(address: str) -> dict[str, Any]:
    """Get mailbox disk usage.

    Tries ``doveadm quota get`` first, falls back to calculating directory size.
    """
    try:
        address = _validate_email(address)
        user, domain = address.split("@")

        # Try doveadm quota get
        try:
            proc = await _run(["doveadm", "quota", "get", "-u", address], timeout=15)
            if proc.returncode == 0 and proc.stdout:
                output = proc.stdout.decode()
                # Parse doveadm output: STORAGE  <value>  <limit>  <percentage>
                for line in output.splitlines():
                    parts = line.split()
                    if parts and parts[0] == "STORAGE":
                        # doveadm reports in kilobytes
                        used_kb = int(parts[1]) if len(parts) > 1 else 0
                        return {"ok": True, "address": address, "used_mb": round(used_kb / 1024, 2)}
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            pass

        # Fallback: calculate directory size
        maildir = VIRTUAL_MAILBOX_DIR / domain / user
        if maildir.exists():
            proc = await _run(["du", "-sk", str(maildir)], timeout=15)
            if proc.returncode == 0 and proc.stdout:
                size_kb = int(proc.stdout.decode().split()[0])
                return {"ok": True, "address": address, "used_mb": round(size_kb / 1024, 2)}

        return {"ok": True, "address": address, "used_mb": 0.0}

    except Exception as exc:
        logger.error("get_quota_usage_direct failed: %s", exc)
        return {"ok": False, "error": str(exc), "used_mb": 0.0}


async def configure_ratelimit_direct(address: str, max_per_hour: int) -> dict[str, Any]:
    """Configure Exim4 per-user ratelimit via a ratelimit data file.

    Writes per-user limits to /etc/exim4/ratelimits which should be
    referenced in the Exim4 ACL configuration.
    """
    try:
        address = _validate_email(address)
        ratelimit_file = Path("/etc/exim4/ratelimits")
        ratelimit_file.parent.mkdir(parents=True, exist_ok=True)

        existing = ratelimit_file.read_text() if ratelimit_file.exists() else ""
        lines = existing.splitlines()

        # Update or add the entry
        new_line = f"{address}: {max_per_hour}"
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{address}:"):
                lines[i] = new_line
                updated = True
                break

        if not updated:
            lines.append(new_line)

        _atomic_write(ratelimit_file, "\n".join(lines) + "\n", mode=0o644)
        return {"ok": True, "address": address, "max_emails_per_hour": max_per_hour}

    except Exception as exc:
        logger.error("configure_ratelimit_direct failed: %s", exc)
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

async def create_alias_direct(
    source: str,
    destination: str,
    destinations: list[str] | None = None,
    keep_local_copy: bool = False,
) -> dict[str, Any]:
    """Add an entry to Exim4 virtual_aliases file with multi-target support."""
    try:
        source = _validate_email(source)

        # Build destination list
        dest_list: list[str] = []
        if destinations:
            dest_list = [_validate_email(d) for d in destinations]
        elif destination:
            dest_list = [_validate_email(d.strip()) for d in destination.split(",") if d.strip()]

        if not dest_list:
            return {"ok": False, "error": "At least one destination address is required"}

        if keep_local_copy and source not in dest_list:
            dest_list.insert(0, source)

        EXIM_VIRTUAL_ALIASES.parent.mkdir(parents=True, exist_ok=True)
        existing = EXIM_VIRTUAL_ALIASES.read_text() if EXIM_VIRTUAL_ALIASES.exists() else ""

        # Remove existing alias for this source to allow update
        filtered = [
            l for l in existing.splitlines(keepends=True)
            if not l.strip().startswith(f"{source}:")
        ]

        line = f"{source}: {', '.join(dest_list)}"
        new_content = "".join(filtered).rstrip("\n") + "\n" + line + "\n"
        _atomic_write(EXIM_VIRTUAL_ALIASES, new_content, mode=0o644)

        return {"ok": True, "source": source, "destinations": dest_list}

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
# Autoresponder (Dovecot Sieve vacation)
# ------------------------------------------------------------------

async def configure_autoresponder_direct(
    address: str,
    enabled: bool,
    subject: str | None = None,
    body: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Configure a Dovecot Sieve vacation autoresponder for a mailbox.

    Generates a .sieve file using the RFC 5230 vacation extension,
    compiles it with sievec, and symlinks it as the active script.
    When ``enabled`` is False the sieve file is removed.
    """
    try:
        address = _validate_email(address)
        user, domain = address.split("@")

        maildir = VIRTUAL_MAILBOX_DIR / domain / user
        sieve_dir = maildir / "sieve"
        sieve_file = sieve_dir / "autoresponder.sieve"
        compiled_file = sieve_dir / "autoresponder.svbin"
        active_link = maildir / ".dovecot.sieve"

        if not enabled:
            # Disable: remove sieve script and symlink
            for f in (sieve_file, compiled_file):
                if f.exists():
                    f.unlink()
            if active_link.is_symlink() and str(active_link.resolve()) == str(sieve_file):
                active_link.unlink()
            return {"ok": True, "address": address, "autoresponder": "disabled"}

        if not subject or not body:
            return {"ok": False, "error": "subject and body are required when enabling autoresponder"}

        # Build Sieve script
        requires = ['"vacation"']
        if start_date or end_date:
            requires.append('"date"')
            requires.append('"relational"')

        require_line = f'require [{", ".join(requires)}];'

        # Build date conditions
        conditions = []
        if start_date:
            sd = start_date[:10]
            conditions.append(f'currentdate :value "ge" "date" "{sd}"')
        if end_date:
            ed = end_date[:10]
            conditions.append(f'currentdate :value "le" "date" "{ed}"')

        # Escape for Sieve strings
        sieve_body = body.replace("\\", "\\\\").replace('"', '\\"')
        sieve_subject = subject.replace("\\", "\\\\").replace('"', '\\"')

        vacation_action = f'vacation :days 1 :subject "{sieve_subject}" "{sieve_body}";'

        if conditions:
            allof_tests = ",\n        ".join(conditions)
            sieve_script = f"""{require_line}

if allof (
        {allof_tests}
    ) {{
    {vacation_action}
}}
"""
        else:
            sieve_script = f"""{require_line}

{vacation_action}
"""

        # Write sieve file
        sieve_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(sieve_file, sieve_script, mode=0o644)

        # Compile with sievec
        warning = None
        try:
            proc = await _run(["sievec", str(sieve_file)], timeout=15)
            if proc.returncode != 0:
                stderr = proc.stderr.decode() if proc.stderr else ""
                warning = f"sievec compilation failed: {stderr}"
        except FileNotFoundError:
            warning = "sievec not found — sieve script written but not compiled"

        # Create/update active symlink
        if active_link.exists() or active_link.is_symlink():
            active_link.unlink()
        active_link.symlink_to(sieve_file)

        # Fix ownership
        try:
            await _run(["chown", "-R", "vmail:vmail", str(sieve_dir)])
        except Exception as exc:
            logger.warning("Could not chown sieve dir: %s", exc)

        result: dict[str, Any] = {"ok": True, "address": address, "autoresponder": "enabled"}
        if warning:
            result["warning"] = warning
        return result

    except Exception as exc:
        logger.error("configure_autoresponder_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


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


# ------------------------------------------------------------------
# Catch-all operations
# ------------------------------------------------------------------

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _validate_domain(domain: str) -> str:
    domain = domain.strip().lower()
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"Invalid domain: {domain!r}")
    return domain


async def configure_catch_all_direct(domain: str, destination: str) -> dict[str, Any]:
    """Add a catch-all alias (*@domain -> destination) to Exim4 virtual_aliases."""
    try:
        domain = _validate_domain(domain)
        destination = _validate_email(destination)

        catch_all_source = f"*@{domain}"
        line = f"{catch_all_source}: {destination}"

        EXIM_VIRTUAL_ALIASES.parent.mkdir(parents=True, exist_ok=True)
        existing = EXIM_VIRTUAL_ALIASES.read_text() if EXIM_VIRTUAL_ALIASES.exists() else ""

        # Remove any existing catch-all for this domain first
        filtered = [
            l for l in existing.splitlines(keepends=True)
            if not l.strip().startswith(f"*@{domain}:")
        ]
        new_content = "".join(filtered).rstrip("\n") + "\n" + line + "\n"

        _atomic_write(EXIM_VIRTUAL_ALIASES, new_content, mode=0o644)

        return {"ok": True, "domain": domain, "destination": destination}

    except Exception as exc:
        logger.error("configure_catch_all_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def remove_catch_all_direct(domain: str) -> dict[str, Any]:
    """Remove the catch-all alias for a domain from Exim4 virtual_aliases."""
    try:
        domain = _validate_domain(domain)

        if not EXIM_VIRTUAL_ALIASES.exists():
            return {"ok": True, "detail": "Aliases file does not exist, nothing to remove"}

        lines = EXIM_VIRTUAL_ALIASES.read_text().splitlines(keepends=True)
        new_lines = [l for l in lines if not l.strip().startswith(f"*@{domain}:")]
        _atomic_write(EXIM_VIRTUAL_ALIASES, "".join(new_lines), mode=0o644)

        return {"ok": True, "domain": domain, "deleted": True}

    except Exception as exc:
        logger.error("remove_catch_all_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------
# Sieve filter operations (direct fallback)
# ------------------------------------------------------------------

SIEVE_FILTER_FILENAME = "filters.sieve"
SIEVE_FILTER_COMPILED = "filters.svbin"


async def read_sieve_filters_direct(address: str) -> dict[str, Any]:
    """Read the custom Sieve filter script for a mailbox."""
    try:
        address = _validate_email(address)
        user, domain = address.split("@")

        maildir = VIRTUAL_MAILBOX_DIR / domain / user
        sieve_dir = maildir / "sieve"
        sieve_file = sieve_dir / SIEVE_FILTER_FILENAME

        if not sieve_file.exists():
            return {"ok": True, "script": "", "active": False}

        script = sieve_file.read_text()
        active_link = maildir / ".dovecot.sieve"
        active = (
            active_link.is_symlink()
            and str(active_link.resolve()) == str(sieve_file.resolve())
        )

        return {"ok": True, "script": script, "active": active}

    except Exception as exc:
        logger.error("read_sieve_filters_direct failed: %s", exc)
        return {"ok": False, "error": str(exc), "script": "", "active": False}


async def write_sieve_filters_direct(address: str, script: str) -> dict[str, Any]:
    """Write and compile a Sieve filter script for a mailbox."""
    try:
        address = _validate_email(address)
        user, domain = address.split("@")

        maildir = VIRTUAL_MAILBOX_DIR / domain / user
        sieve_dir = maildir / "sieve"
        sieve_file = sieve_dir / SIEVE_FILTER_FILENAME
        compiled_file = sieve_dir / SIEVE_FILTER_COMPILED
        active_link = maildir / ".dovecot.sieve"

        if not script.strip():
            for f in (sieve_file, compiled_file):
                if f.exists():
                    f.unlink()
            if active_link.is_symlink() and str(active_link.resolve()) == str(sieve_file.resolve()):
                active_link.unlink()
            return {"ok": True, "address": address, "filters": "disabled"}

        sieve_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(sieve_file, script, mode=0o644)

        # Compile
        warning = None
        try:
            proc = await _run(["sievec", str(sieve_file)], timeout=15)
            if proc.returncode != 0:
                stderr = proc.stderr.decode() if proc.stderr else ""
                warning = f"sievec compilation failed: {stderr}"
        except FileNotFoundError:
            warning = "sievec not found -- script written but not compiled"

        # Activate
        if active_link.exists() or active_link.is_symlink():
            active_link.unlink()
        active_link.symlink_to(sieve_file)

        # Fix ownership
        try:
            await _run(["chown", "-R", "vmail:vmail", str(sieve_dir)])
        except Exception as exc:
            logger.warning("Could not chown sieve dir: %s", exc)

        result: dict[str, Any] = {"ok": True, "address": address, "filters": "active"}
        if warning:
            result["warning"] = warning
        return result

    except Exception as exc:
        logger.error("write_sieve_filters_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def configure_spam_filter_direct(
    address: str,
    enabled: bool = True,
    threshold: float = 5.0,
    action: str = "move",
    whitelist: str | None = None,
    blacklist: str | None = None,
) -> dict[str, Any]:
    """Configure per-user SpamAssassin preferences and Sieve spam rule.

    Direct fallback equivalent of agent's configure_spam_filter.
    """
    try:
        address = _validate_email(address)
        user, domain = address.split("@")

        maildir = VIRTUAL_MAILBOX_DIR / domain / user

        # 1. Write per-user SpamAssassin preferences
        sa_dir = maildir / ".spamassassin"
        sa_dir.mkdir(parents=True, exist_ok=True)
        user_prefs = sa_dir / "user_prefs"

        prefs_lines = [
            f"# HostHive managed SpamAssassin user_prefs for {address}",
            f"required_score {threshold}",
        ]

        for addr_line in (whitelist or "").splitlines():
            addr_line = addr_line.strip()
            if addr_line:
                prefs_lines.append(f"whitelist_from {addr_line}")

        for addr_line in (blacklist or "").splitlines():
            addr_line = addr_line.strip()
            if addr_line:
                prefs_lines.append(f"blacklist_from {addr_line}")

        if not enabled:
            prefs_lines = [
                f"# HostHive managed SpamAssassin user_prefs for {address}",
                "# Spam filter disabled",
                "required_score 999",
            ]

        _atomic_write(user_prefs, "\n".join(prefs_lines) + "\n", mode=0o644)

        # Fix ownership
        try:
            await _run(["chown", "-R", "vmail:vmail", str(sa_dir)])
        except Exception as exc:
            logger.warning("Could not chown spamassassin dir: %s", exc)

        # 2. Write Sieve rule for spam action
        sieve_dir = maildir / "sieve"
        sieve_dir.mkdir(parents=True, exist_ok=True)
        spam_sieve = sieve_dir / "spam_filter.sieve"
        spam_compiled = sieve_dir / "spam_filter.svbin"

        if not enabled or action == "tag_only":
            for f in (spam_sieve, spam_compiled):
                if f.exists():
                    f.unlink()
            return {
                "ok": True, "address": address,
                "spam_filter": "disabled" if not enabled else "tag_only",
            }

        # Build Sieve script
        if action == "move":
            sieve_action = 'fileinto "Junk";'
        elif action == "delete":
            sieve_action = "discard;"
        else:
            sieve_action = "keep;"

        sieve_script = f"""require ["fileinto"];

# HostHive spam filter rule
if header :contains "X-Spam-Status" "Yes" {{
    {sieve_action}
}}
"""

        _atomic_write(spam_sieve, sieve_script, mode=0o644)

        # Compile
        warning = None
        try:
            proc = await _run(["sievec", str(spam_sieve)], timeout=15)
            if proc.returncode != 0:
                stderr = proc.stderr.decode() if proc.stderr else ""
                warning = f"sievec compilation failed: {stderr}"
        except FileNotFoundError:
            warning = "sievec not found -- script written but not compiled"

        # Fix ownership
        try:
            await _run(["chown", "-R", "vmail:vmail", str(sieve_dir)])
        except Exception as exc:
            logger.warning("Could not chown sieve dir: %s", exc)

        result: dict[str, Any] = {
            "ok": True, "address": address,
            "spam_filter": "active", "action": action,
        }
        if warning:
            result["warning"] = warning
        return result

    except Exception as exc:
        logger.error("configure_spam_filter_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def train_spam_direct(
    address: str,
    message_path: str,
    is_spam: bool = True,
) -> dict[str, Any]:
    """Train SpamAssassin with a message as spam or ham.

    Direct fallback equivalent of agent's train_spam.
    """
    try:
        address = _validate_email(address)
        cmd_flag = "--spam" if is_spam else "--ham"

        try:
            proc = await _run(
                ["sa-learn", cmd_flag, "--username", address, message_path],
                timeout=30,
            )
            stdout = proc.stdout.decode() if proc.stdout else ""
            stderr = proc.stderr.decode() if proc.stderr else ""
            return {
                "ok": proc.returncode == 0,
                "address": address,
                "trained": "spam" if is_spam else "ham",
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }
        except FileNotFoundError:
            return {"ok": False, "error": "sa-learn binary not found on this system"}

    except Exception as exc:
        logger.error("train_spam_direct failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def validate_sieve_direct(script: str) -> dict[str, Any]:
    """Validate a Sieve script with sievec (dry-run)."""
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sieve", delete=False,
        ) as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        try:
            proc = await _run(["sievec", tmp_path], timeout=15)
            valid = proc.returncode == 0
            errors = None
            if not valid:
                errors = proc.stderr.decode() if proc.stderr else "Unknown error"
            return {"ok": True, "valid": valid, "errors": errors}
        except FileNotFoundError:
            return {"ok": False, "valid": False, "errors": "sievec binary not found on this system"}
        finally:
            for suffix in ("", ".svbin"):
                p = Path(tmp_path + suffix) if suffix else Path(tmp_path)
                if p.exists():
                    p.unlink()

    except Exception as exc:
        logger.error("validate_sieve_direct failed: %s", exc)
        return {"ok": False, "valid": False, "errors": str(exc)}
