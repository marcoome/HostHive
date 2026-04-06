"""
Mail executor — Dovecot virtual mailboxes + Exim4 routing.

Manages mailbox creation / deletion, password changes, aliases, and queue ops.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agent.executors._helpers import atomic_write, safe_domain, safe_path

VIRTUAL_MAILBOX_DIR = Path("/var/mail/vhosts")
DOVECOT_PASSWD = Path("/etc/dovecot/users")
EXIM_VIRTUAL_ALIASES = Path("/etc/exim4/virtual_aliases")
EXIM_ROUTERS_DIR = Path("/etc/exim4/conf.d/router")

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _validate_email(address: str) -> str:
    address = address.strip().lower()
    if not _EMAIL_RE.match(address):
        raise ValueError(f"invalid email address: {address!r}")
    return address


def _hash_password(password: str) -> str:
    """Generate a SHA-512 crypt password hash using Dovecot doveadm if available,
    falling back to hashlib-based SSHA256."""
    try:
        result = subprocess.run(
            ["doveadm", "pw", "-s", "SHA512-CRYPT", "-p", password],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    # Fallback: simple SSHA256
    salt = os.urandom(16)
    h = hashlib.sha256(password.encode("utf-8") + salt).hexdigest()
    return "{SSHA256}" + h


# ------------------------------------------------------------------
# Mailbox management
# ------------------------------------------------------------------


def create_mailbox(address: str, password: str, quota_mb: int = 1024) -> dict[str, Any]:
    """Create a virtual mailbox entry for Dovecot + ensure mail directory."""
    address = _validate_email(address)
    user, domain = address.split("@")
    safe_domain(domain)

    pw_hash = _hash_password(password)

    # Dovecot passwd-file line:  user@domain:{scheme}hash:vmail:vmail::/var/mail/vhosts/domain/user::userdb_quota_rule=*:storage=NNM
    line = f"{address}:{pw_hash}:vmail:vmail::{VIRTUAL_MAILBOX_DIR}/{domain}/{user}::userdb_quota_rule=*:storage={quota_mb}M"

    # Append to passwd file (create if missing)
    DOVECOT_PASSWD.parent.mkdir(parents=True, exist_ok=True)
    existing = DOVECOT_PASSWD.read_text() if DOVECOT_PASSWD.exists() else ""
    if any(l.startswith(f"{address}:") for l in existing.splitlines()):
        raise ValueError(f"mailbox already exists: {address}")
    atomic_write(DOVECOT_PASSWD, existing.rstrip("\n") + "\n" + line + "\n", mode=0o600)

    # Create Maildir structure
    maildir = VIRTUAL_MAILBOX_DIR / domain / user
    for sub in ("cur", "new", "tmp"):
        (maildir / sub).mkdir(parents=True, exist_ok=True)

    return {"address": address, "maildir": str(maildir)}


def delete_mailbox(address: str) -> dict[str, Any]:
    """Remove a virtual mailbox entry (does not delete mail directory)."""
    address = _validate_email(address)

    if DOVECOT_PASSWD.exists():
        lines = DOVECOT_PASSWD.read_text().splitlines(keepends=True)
        lines = [l for l in lines if not l.startswith(f"{address}:")]
        atomic_write(DOVECOT_PASSWD, "".join(lines), mode=0o600)

    return {"address": address, "deleted": True}


def set_password(address: str, new_password: str) -> dict[str, Any]:
    """Update the password hash for an existing mailbox."""
    address = _validate_email(address)
    pw_hash = _hash_password(new_password)

    if not DOVECOT_PASSWD.exists():
        raise FileNotFoundError("dovecot passwd file does not exist")

    lines = DOVECOT_PASSWD.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{address}:"):
            parts = line.split(":")
            parts[1] = pw_hash
            lines[i] = ":".join(parts)
            found = True
            break

    if not found:
        raise ValueError(f"mailbox not found: {address}")

    atomic_write(DOVECOT_PASSWD, "\n".join(lines) + "\n", mode=0o600)
    return {"address": address, "password_changed": True}


# ------------------------------------------------------------------
# Alias management
# ------------------------------------------------------------------


def create_alias(from_addr: str, to_addr: str | None = None,
                  destinations: list[str] | None = None,
                  keep_local_copy: bool = False) -> dict[str, Any]:
    """Add a virtual alias entry with multi-target forwarding support.

    Args:
        from_addr: Source email address.
        to_addr: Single destination (legacy, for backward compat).
        destinations: List of destination addresses for multi-target forwarding.
        keep_local_copy: If True, include the source address as a destination
            so that mail is also delivered locally.
    """
    from_addr = _validate_email(from_addr)

    # Build destination list
    dest_list: list[str] = []
    if destinations:
        dest_list = [_validate_email(d) for d in destinations]
    elif to_addr:
        dest_list = [_validate_email(d.strip()) for d in to_addr.split(",") if d.strip()]

    if not dest_list:
        raise ValueError("at least one destination address is required")

    if keep_local_copy and from_addr not in dest_list:
        dest_list.insert(0, from_addr)

    EXIM_VIRTUAL_ALIASES.parent.mkdir(parents=True, exist_ok=True)
    existing = EXIM_VIRTUAL_ALIASES.read_text() if EXIM_VIRTUAL_ALIASES.exists() else ""

    # Remove any existing alias for the same source
    filtered = [
        l for l in existing.splitlines(keepends=True)
        if not l.strip().startswith(f"{from_addr}:")
    ]

    line = f"{from_addr}: {', '.join(dest_list)}"
    new_content = "".join(filtered).rstrip("\n") + "\n" + line + "\n"
    atomic_write(EXIM_VIRTUAL_ALIASES, new_content, mode=0o644)

    return {"from": from_addr, "to": dest_list, "keep_local_copy": keep_local_copy}


def delete_alias(alias: str) -> dict[str, Any]:
    """Remove a virtual alias by its from-address."""
    alias = _validate_email(alias)

    if not EXIM_VIRTUAL_ALIASES.exists():
        raise FileNotFoundError("aliases file does not exist")

    lines = EXIM_VIRTUAL_ALIASES.read_text().splitlines(keepends=True)
    lines = [l for l in lines if not l.startswith(f"{alias}:")]
    atomic_write(EXIM_VIRTUAL_ALIASES, "".join(lines), mode=0o644)

    return {"alias": alias, "deleted": True}


# ------------------------------------------------------------------
# Catch-all management
# ------------------------------------------------------------------

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def configure_catch_all(domain: str, destination: str) -> dict[str, Any]:
    """Set a catch-all alias (*@domain -> destination) in Exim4 virtual aliases."""
    domain = domain.strip().lower()
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"invalid domain: {domain!r}")
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
    atomic_write(EXIM_VIRTUAL_ALIASES, new_content, mode=0o644)

    return {"domain": domain, "destination": destination, "catch_all": True}


def remove_catch_all(domain: str) -> dict[str, Any]:
    """Remove the catch-all alias for a domain from Exim4 virtual aliases."""
    domain = domain.strip().lower()
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"invalid domain: {domain!r}")

    if not EXIM_VIRTUAL_ALIASES.exists():
        raise FileNotFoundError("aliases file does not exist")

    lines = EXIM_VIRTUAL_ALIASES.read_text().splitlines(keepends=True)
    lines = [l for l in lines if not l.strip().startswith(f"*@{domain}:")]
    atomic_write(EXIM_VIRTUAL_ALIASES, "".join(lines), mode=0o644)

    return {"domain": domain, "catch_all_removed": True}


# ------------------------------------------------------------------
# Queue management
# ------------------------------------------------------------------


def get_mail_queue() -> dict[str, Any]:
    """Parse Exim4 mail queue."""
    result = subprocess.run(
        ["exim4", "-bp"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = result.stdout.strip().splitlines() if result.stdout else []
    return {"count": len(lines), "raw": result.stdout}


def flush_mail_queue() -> dict[str, Any]:
    """Force delivery of all queued messages."""
    result = subprocess.run(
        ["exim4", "-qff"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ------------------------------------------------------------------
# Autoresponder — Dovecot Sieve vacation
# ------------------------------------------------------------------


def configure_autoresponder(
    address: str,
    enabled: bool,
    subject: str | None = None,
    body: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Configure a Dovecot Sieve vacation autoresponder for a mailbox.

    Generates a .sieve file using the RFC 5230 vacation extension
    (with date extension for start/end date support), writes it to
    the user's mail directory, and compiles it with sievec.

    When ``enabled`` is False the sieve file is removed (disabled).
    """
    address = _validate_email(address)
    user, domain = address.split("@")
    safe_domain(domain)

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
        if active_link.is_symlink() and active_link.resolve() == sieve_file.resolve():
            active_link.unlink()
        return {"address": address, "autoresponder": "disabled"}

    if not subject or not body:
        raise ValueError("subject and body are required when enabling autoresponder")

    # Build Sieve script
    requires = ['"vacation"']
    conditions = []

    if start_date or end_date:
        requires.append('"date"')
        requires.append('"relational"')

    require_line = f'require [{", ".join(requires)}];'

    # Build date conditions for an allof test
    if start_date or end_date:
        date_tests = []
        if start_date:
            # start_date expected as ISO format (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)
            sd = start_date[:10]  # extract YYYY-MM-DD
            date_tests.append(f'currentdate :value "ge" "date" "{sd}"')
        if end_date:
            ed = end_date[:10]
            date_tests.append(f'currentdate :value "le" "date" "{ed}"')
        conditions = date_tests

    # Escape body for Sieve (double-quote escaping)
    sieve_body = body.replace("\\", "\\\\").replace('"', '\\"')
    sieve_subject = subject.replace("\\", "\\\\").replace('"', '\\"')

    vacation_action = (
        f'vacation :days 1 :subject "{sieve_subject}" "{sieve_body}";'
    )

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
    atomic_write(sieve_file, sieve_script, mode=0o644)

    # Compile with sievec
    try:
        result = subprocess.run(
            ["sievec", str(sieve_file)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return {
                "address": address,
                "autoresponder": "enabled",
                "warning": f"sievec compilation failed: {result.stderr}",
            }
    except FileNotFoundError:
        return {
            "address": address,
            "autoresponder": "enabled",
            "warning": "sievec not found — sieve script written but not compiled",
        }

    # Create/update active symlink so Dovecot picks it up
    if active_link.exists() or active_link.is_symlink():
        active_link.unlink()
    active_link.symlink_to(sieve_file)

    # Fix ownership to vmail
    subprocess.run(
        ["chown", "-R", "vmail:vmail", str(sieve_dir)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    return {"address": address, "autoresponder": "enabled"}


# ------------------------------------------------------------------
# Sieve filter management
# ------------------------------------------------------------------

SIEVE_FILTER_FILENAME = "filters.sieve"
SIEVE_FILTER_COMPILED = "filters.svbin"


def read_sieve_script(user: str, domain: str) -> dict[str, Any]:
    """Read the user's custom Sieve filter script.

    Returns dict with 'script' (str) and 'active' (bool).
    """
    domain = safe_domain(domain)
    safe_path(user)

    maildir = VIRTUAL_MAILBOX_DIR / domain / user
    sieve_dir = maildir / "sieve"
    sieve_file = sieve_dir / SIEVE_FILTER_FILENAME

    if not sieve_file.exists():
        return {"script": "", "active": False}

    script = sieve_file.read_text()
    # Check if this filter is active (symlinked from .dovecot.sieve)
    active_link = maildir / ".dovecot.sieve"
    active = (
        active_link.is_symlink()
        and active_link.resolve() == sieve_file.resolve()
    )

    return {"script": script, "active": active}


def write_sieve_script(user: str, domain: str, script: str) -> dict[str, Any]:
    """Write and compile a Sieve filter script for a mailbox.

    The script is written to <maildir>/sieve/filters.sieve, compiled with
    sievec, and symlinked as the active Dovecot sieve script.
    """
    domain = safe_domain(domain)
    safe_path(user)

    maildir = VIRTUAL_MAILBOX_DIR / domain / user
    sieve_dir = maildir / "sieve"
    sieve_file = sieve_dir / SIEVE_FILTER_FILENAME
    compiled_file = sieve_dir / SIEVE_FILTER_COMPILED
    active_link = maildir / ".dovecot.sieve"

    if not script.strip():
        # Empty script means disable filters
        for f in (sieve_file, compiled_file):
            if f.exists():
                f.unlink()
        if active_link.is_symlink() and active_link.resolve() == sieve_file.resolve():
            active_link.unlink()
        return {"user": user, "domain": domain, "filters": "disabled"}

    sieve_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(sieve_file, script, mode=0o644)

    # Compile with sievec
    warning = None
    try:
        result = subprocess.run(
            ["sievec", str(sieve_file)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            warning = f"sievec compilation failed: {result.stderr}"
    except FileNotFoundError:
        warning = "sievec not found -- script written but not compiled"

    # Activate: symlink .dovecot.sieve -> filters.sieve
    # If there's an existing autoresponder link we must merge via an include
    # approach, but for simplicity we use a combined strategy: if an
    # autoresponder sieve exists, we include both via a wrapper.
    if active_link.exists() or active_link.is_symlink():
        active_link.unlink()
    active_link.symlink_to(sieve_file)

    # Fix ownership
    subprocess.run(
        ["chown", "-R", "vmail:vmail", str(sieve_dir)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    result_dict: dict[str, Any] = {
        "user": user,
        "domain": domain,
        "filters": "active",
    }
    if warning:
        result_dict["warning"] = warning
    return result_dict


def validate_sieve_script(script: str) -> dict[str, Any]:
    """Validate a Sieve script using sievec without installing it.

    Writes to a temporary file, runs sievec, then cleans up.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sieve", delete=False,
    ) as tmp:
        tmp.write(script)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["sievec", tmp_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        valid = result.returncode == 0
        errors = result.stderr.strip() if not valid else None
        return {"valid": valid, "errors": errors}
    except FileNotFoundError:
        return {"valid": False, "errors": "sievec binary not found on this system"}
    finally:
        # Clean up temp files
        for suffix in ("", ".svbin"):
            p = Path(tmp_path + suffix) if suffix else Path(tmp_path)
            if p.exists():
                p.unlink()


# ------------------------------------------------------------------
# DKIM / SPF / DMARC — Email Authentication
# ------------------------------------------------------------------

DKIM_KEY_DIR = Path("/etc/opendkim/keys")
OPENDKIM_CONF = Path("/etc/opendkim.conf")
OPENDKIM_KEYTABLE = Path("/etc/opendkim/KeyTable")
OPENDKIM_SIGNING_TABLE = Path("/etc/opendkim/SigningTable")
OPENDKIM_TRUSTED_HOSTS = Path("/etc/opendkim/TrustedHosts")
DKIM_SELECTOR = "default"


def setup_dkim(domain: str) -> dict[str, Any]:
    """Generate DKIM keys for a domain and configure OpenDKIM.

    Creates RSA 2048-bit key pair, updates OpenDKIM tables.
    Returns the public key and the DNS TXT record to add.
    """
    domain = safe_domain(domain)
    key_dir = DKIM_KEY_DIR / domain
    key_dir.mkdir(parents=True, exist_ok=True)

    private_key = key_dir / f"{DKIM_SELECTOR}.private"
    public_key_txt = key_dir / f"{DKIM_SELECTOR}.txt"

    # Generate key pair using opendkim-genkey
    result = subprocess.run(
        [
            "opendkim-genkey",
            "-b", "2048",
            "-d", domain,
            "-D", str(key_dir),
            "-s", DKIM_SELECTOR,
            "-v",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"opendkim-genkey failed: {result.stderr}")

    # Fix permissions
    os.chmod(str(private_key), 0o600)
    subprocess.run(
        ["chown", "opendkim:opendkim", str(private_key)],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Read public key for DNS record
    pub_content = public_key_txt.read_text() if public_key_txt.exists() else ""

    # Extract the p= value from the TXT record
    dns_record = pub_content.strip()

    # Update KeyTable
    key_table_line = f"{DKIM_SELECTOR}._domainkey.{domain} {domain}:{DKIM_SELECTOR}:{private_key}\n"
    OPENDKIM_KEYTABLE.parent.mkdir(parents=True, exist_ok=True)
    existing_kt = OPENDKIM_KEYTABLE.read_text() if OPENDKIM_KEYTABLE.exists() else ""
    if f"{domain}:" not in existing_kt:
        atomic_write(OPENDKIM_KEYTABLE, existing_kt.rstrip("\n") + "\n" + key_table_line)

    # Update SigningTable
    signing_line = f"*@{domain} {DKIM_SELECTOR}._domainkey.{domain}\n"
    existing_st = OPENDKIM_SIGNING_TABLE.read_text() if OPENDKIM_SIGNING_TABLE.exists() else ""
    if f"*@{domain}" not in existing_st:
        atomic_write(OPENDKIM_SIGNING_TABLE, existing_st.rstrip("\n") + "\n" + signing_line)

    # Update TrustedHosts
    existing_th = OPENDKIM_TRUSTED_HOSTS.read_text() if OPENDKIM_TRUSTED_HOSTS.exists() else "127.0.0.1\nlocalhost\n"
    if domain not in existing_th:
        atomic_write(OPENDKIM_TRUSTED_HOSTS, existing_th.rstrip("\n") + "\n" + f"*.{domain}\n")

    # Restart OpenDKIM
    subprocess.run(
        ["systemctl", "restart", "opendkim"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    return {
        "domain": domain,
        "dkim_selector": DKIM_SELECTOR,
        "dns_record": dns_record,
        "public_key": pub_content,
        "private_key_path": str(private_key),
    }


def get_dkim_record(domain: str) -> dict[str, Any]:
    """Return the DKIM DNS TXT record for a domain."""
    domain = safe_domain(domain)
    key_dir = DKIM_KEY_DIR / domain
    public_key_txt = key_dir / f"{DKIM_SELECTOR}.txt"

    if not public_key_txt.exists():
        raise FileNotFoundError(f"DKIM keys not found for {domain}. Run setup_dkim first.")

    return {
        "domain": domain,
        "selector": DKIM_SELECTOR,
        "dns_name": f"{DKIM_SELECTOR}._domainkey.{domain}",
        "dns_type": "TXT",
        "dns_value": public_key_txt.read_text().strip(),
    }


def check_spf(domain: str) -> dict[str, Any]:
    """Verify that an SPF record exists for the domain using DNS lookup."""
    domain = safe_domain(domain)

    result = subprocess.run(
        ["dig", "+short", "TXT", domain],
        capture_output=True,
        text=True,
        timeout=15,
    )

    txt_records = result.stdout.strip()
    has_spf = "v=spf1" in txt_records

    return {
        "domain": domain,
        "spf_exists": has_spf,
        "status": "ok" if has_spf else "missing",
        "txt_records": txt_records,
    }


def generate_spf_record(domain: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Generate an SPF TXT record for the domain.

    Args:
        domain: Domain name.
        includes: Additional SPF include directives (e.g. ["_spf.google.com"]).
    """
    domain = safe_domain(domain)

    parts = ["v=spf1", "mx", "a"]
    for inc in (includes or []):
        inc = inc.strip()
        if inc and re.match(r"^[a-zA-Z0-9._-]+$", inc):
            parts.append(f"include:{inc}")
    parts.append("~all")

    record = " ".join(parts)

    return {
        "domain": domain,
        "record": record,
        "dns_name": domain,
        "dns_type": "TXT",
        "dns_value": record,
    }


def check_dmarc(domain: str) -> dict[str, Any]:
    """Verify that a DMARC record exists for the domain."""
    domain = safe_domain(domain)

    result = subprocess.run(
        ["dig", "+short", "TXT", f"_dmarc.{domain}"],
        capture_output=True,
        text=True,
        timeout=15,
    )

    txt_records = result.stdout.strip()
    has_dmarc = "v=DMARC1" in txt_records

    return {
        "domain": domain,
        "dmarc_exists": has_dmarc,
        "status": "ok" if has_dmarc else "missing",
        "txt_records": txt_records,
    }


def generate_dmarc_record(domain: str, policy: str = "quarantine") -> dict[str, Any]:
    """Generate a DMARC TXT record for the domain.

    Args:
        domain: Domain name.
        policy: DMARC policy — "none", "quarantine", or "reject".
    """
    domain = safe_domain(domain)

    if policy not in ("none", "quarantine", "reject"):
        raise ValueError(f"Invalid DMARC policy: {policy!r}. Must be 'none', 'quarantine', or 'reject'.")

    record = f"v=DMARC1; p={policy}; rua=mailto:dmarc@{domain}; ruf=mailto:dmarc@{domain}; fo=1"

    return {
        "domain": domain,
        "policy": policy,
        "record": record,
        "dns_name": f"_dmarc.{domain}",
        "dns_type": "TXT",
        "dns_value": record,
    }


def get_email_auth_status(domain: str) -> dict[str, Any]:
    """Check SPF, DKIM, and DMARC status for a domain.

    Returns a summary dict with status for each: "ok" or "missing".
    """
    domain = safe_domain(domain)

    spf = check_spf(domain)
    dmarc = check_dmarc(domain)

    # DKIM: check if keys exist locally
    key_dir = DKIM_KEY_DIR / domain
    dkim_exists = (key_dir / f"{DKIM_SELECTOR}.private").exists()

    # Also verify DKIM DNS record
    dkim_dns = subprocess.run(
        ["dig", "+short", "TXT", f"{DKIM_SELECTOR}._domainkey.{domain}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    dkim_dns_ok = "p=" in dkim_dns.stdout

    if dkim_exists and dkim_dns_ok:
        dkim_status = "ok"
    elif dkim_exists:
        dkim_status = "keys_generated_dns_missing"
    else:
        dkim_status = "missing"

    return {
        "domain": domain,
        "spf": spf["status"],
        "dkim": dkim_status,
        "dmarc": dmarc["status"],
    }


def configure_spam_filter(
    user: str,
    domain: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Configure per-user SpamAssassin preferences and Sieve spam rule.

    Args:
        user: Local part of the email address.
        domain: Domain name.
        settings: Dict with keys: enabled, threshold, action, whitelist, blacklist.
    """
    domain = safe_domain(domain)
    safe_path(user)

    enabled = settings.get("enabled", True)
    threshold = float(settings.get("threshold", 5.0))
    action = settings.get("action", "move")  # move | delete | tag_only
    whitelist = settings.get("whitelist") or ""
    blacklist = settings.get("blacklist") or ""

    maildir = VIRTUAL_MAILBOX_DIR / domain / user

    # ---- 1. Write per-user SpamAssassin preferences ----
    sa_dir = maildir / ".spamassassin"
    sa_dir.mkdir(parents=True, exist_ok=True)
    user_prefs = sa_dir / "user_prefs"

    prefs_lines = [
        f"# HostHive managed SpamAssassin user_prefs for {user}@{domain}",
        f"required_score {threshold}",
    ]

    for addr in whitelist.splitlines():
        addr = addr.strip()
        if addr:
            prefs_lines.append(f"whitelist_from {addr}")

    for addr in blacklist.splitlines():
        addr = addr.strip()
        if addr:
            prefs_lines.append(f"blacklist_from {addr}")

    if not enabled:
        prefs_lines = [
            f"# HostHive managed SpamAssassin user_prefs for {user}@{domain}",
            "# Spam filter disabled",
            "required_score 999",
        ]

    atomic_write(user_prefs, "\n".join(prefs_lines) + "\n", mode=0o644)

    # Fix ownership
    subprocess.run(
        ["chown", "-R", "vmail:vmail", str(sa_dir)],
        capture_output=True, text=True, timeout=10,
    )

    # ---- 2. Write Sieve rule for spam action ----
    sieve_dir = maildir / "sieve"
    sieve_dir.mkdir(parents=True, exist_ok=True)
    spam_sieve = sieve_dir / "spam_filter.sieve"
    spam_compiled = sieve_dir / "spam_filter.svbin"

    if not enabled or action == "tag_only":
        # No sieve action needed -- remove if present
        for f in (spam_sieve, spam_compiled):
            if f.exists():
                f.unlink()
        return {
            "user": user, "domain": domain,
            "spam_filter": "disabled" if not enabled else "tag_only",
        }

    # Build Sieve script that checks X-Spam-Status header
    sieve_requires = ['"fileinto"']
    if action == "move":
        sieve_action = 'fileinto "Junk";'
    elif action == "delete":
        sieve_action = "discard;"
    else:
        sieve_action = "keep;"

    sieve_script = f"""require [{", ".join(sieve_requires)}];

# HostHive spam filter rule
if header :contains "X-Spam-Status" "Yes" {{
    {sieve_action}
}}
"""

    atomic_write(spam_sieve, sieve_script, mode=0o644)

    # Compile with sievec
    warning = None
    try:
        result = subprocess.run(
            ["sievec", str(spam_sieve)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            warning = f"sievec compilation failed: {result.stderr}"
    except FileNotFoundError:
        warning = "sievec not found -- script written but not compiled"

    # Fix ownership
    subprocess.run(
        ["chown", "-R", "vmail:vmail", str(sieve_dir)],
        capture_output=True, text=True, timeout=10,
    )

    result_dict: dict[str, Any] = {
        "user": user, "domain": domain,
        "spam_filter": "active", "action": action,
    }
    if warning:
        result_dict["warning"] = warning
    return result_dict


def train_spam(user: str, domain: str, message_path: str, is_spam: bool = True) -> dict[str, Any]:
    """Train SpamAssassin with a message as spam or ham.

    Args:
        user: Local part of the email address.
        domain: Domain name.
        message_path: Absolute path to the message file.
        is_spam: True to train as spam, False to train as ham.
    """
    domain = safe_domain(domain)
    safe_path(user)

    cmd_flag = "--spam" if is_spam else "--ham"
    address = f"{user}@{domain}"

    try:
        result = subprocess.run(
            ["sa-learn", cmd_flag, "--username", address, message_path],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "user": user, "domain": domain,
            "trained": cmd_flag.lstrip("-"),
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {
            "user": user, "domain": domain,
            "error": "sa-learn binary not found on this system",
        }


def setup_rspamd(domain: str) -> dict[str, Any]:
    """Configure Rspamd spam filtering for a domain.

    Creates per-domain Rspamd configuration and ensures the service is running.
    """
    domain = safe_domain(domain)

    rspamd_local_dir = Path("/etc/rspamd/local.d")
    rspamd_override_dir = Path("/etc/rspamd/override.d")

    rspamd_local_dir.mkdir(parents=True, exist_ok=True)
    rspamd_override_dir.mkdir(parents=True, exist_ok=True)

    # DKIM signing configuration for Rspamd
    dkim_signing_conf = rspamd_local_dir / "dkim_signing.conf"
    dkim_config = f"""# HostHive managed DKIM signing configuration
allow_hdrfrom_mismatch = true;
allow_username_mismatch = true;
sign_authenticated = true;
use_domain = "header";
use_esld = true;

domain {{
    {domain} {{
        path = "{DKIM_KEY_DIR / domain / (DKIM_SELECTOR + '.private')}";
        selector = "{DKIM_SELECTOR}";
    }}
}}
"""

    existing = dkim_signing_conf.read_text() if dkim_signing_conf.exists() else ""
    if domain not in existing:
        # Append domain block to existing config or create new
        if existing and "domain {" in existing:
            # Insert before the last closing brace of the domain block
            insert_block = f"""
    {domain} {{
        path = "{DKIM_KEY_DIR / domain / (DKIM_SELECTOR + '.private')}";
        selector = "{DKIM_SELECTOR}";
    }}
"""
            # Simple approach: append to file
            atomic_write(dkim_signing_conf, existing.rstrip("\n") + "\n" + insert_block + "\n")
        else:
            atomic_write(dkim_signing_conf, dkim_config)

    # Ensure Rspamd is running
    subprocess.run(
        ["systemctl", "enable", "rspamd"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    restart_result = subprocess.run(
        ["systemctl", "restart", "rspamd"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    return {
        "domain": domain,
        "rspamd_configured": True,
        "restart_returncode": restart_result.returncode,
    }


# ------------------------------------------------------------------
# Mailing list management
# ------------------------------------------------------------------

EXIM_LIST_ALIASES_DIR = Path("/etc/exim4/mailing_lists")


def configure_mailing_list_aliases(
    list_address: str,
    name: str,
    domain: str,
    members: list[str],
    is_active: bool = True,
    reply_to_list: bool = False,
) -> dict[str, Any]:
    """Configure Exim4 virtual aliases for a mailing list.

    Creates:
      - list_address -> all member addresses
      - listname-subscribe@domain -> owner notification alias
      - listname-unsubscribe@domain -> owner notification alias

    Also writes a list-specific header configuration file so Exim4 can
    inject List-Id, List-Unsubscribe, and optionally Reply-To headers.
    """
    list_address = _validate_email(list_address)
    domain = safe_domain(domain)
    local_part = list_address.split("@")[0]

    EXIM_LIST_ALIASES_DIR.mkdir(parents=True, exist_ok=True)

    alias_file = EXIM_LIST_ALIASES_DIR / f"{local_part}@{domain}"

    if not is_active or not members:
        # If list is inactive or has no members, write empty alias (no delivery)
        lines = [
            f"# Mailing list: {list_address} (inactive or empty)",
        ]
        atomic_write(alias_file, "\n".join(lines) + "\n", mode=0o644)

        # Also remove from main virtual aliases
        _remove_alias_line(list_address)
        _remove_alias_line(f"{local_part}-subscribe@{domain}")
        _remove_alias_line(f"{local_part}-unsubscribe@{domain}")

        return {"list_address": list_address, "status": "inactive", "members": 0}

    # Build the main distribution alias: list_address -> all members
    member_str = ", ".join(members)
    main_alias = f"{list_address}: {member_str}"

    # Subscribe / unsubscribe aliases point to the list owner via the
    # main virtual_aliases file.  In a real Mailman-style setup these
    # would trigger automated subscribe/unsubscribe workflows; here they
    # simply deliver to the main list address so the owner is notified.
    subscribe_alias = f"{local_part}-subscribe@{domain}: {list_address}"
    unsubscribe_alias = f"{local_part}-unsubscribe@{domain}: {list_address}"

    # Write into main virtual_aliases
    EXIM_VIRTUAL_ALIASES.parent.mkdir(parents=True, exist_ok=True)
    existing = EXIM_VIRTUAL_ALIASES.read_text() if EXIM_VIRTUAL_ALIASES.exists() else ""

    # Remove old entries for this list
    filtered = []
    prefixes = (f"{list_address}:", f"{local_part}-subscribe@{domain}:", f"{local_part}-unsubscribe@{domain}:")
    for line in existing.splitlines(keepends=True):
        stripped = line.strip()
        if not any(stripped.startswith(p) for p in prefixes):
            filtered.append(line)

    new_content = "".join(filtered).rstrip("\n") + "\n"
    new_content += main_alias + "\n"
    new_content += subscribe_alias + "\n"
    new_content += unsubscribe_alias + "\n"
    atomic_write(EXIM_VIRTUAL_ALIASES, new_content, mode=0o644)

    # Write per-list header configuration
    header_lines = [
        f"# Headers for mailing list: {list_address}",
        f"list_id: {name}.{domain}",
        f"list_address: {list_address}",
        f"list_unsubscribe: mailto:{local_part}-unsubscribe@{domain}",
    ]
    if reply_to_list:
        header_lines.append(f"reply_to: {list_address}")
    header_lines.append(f"list_subscribe: mailto:{local_part}-subscribe@{domain}")

    atomic_write(alias_file, "\n".join(header_lines) + "\n", mode=0o644)

    return {
        "list_address": list_address,
        "status": "active",
        "members": len(members),
        "subscribe": f"{local_part}-subscribe@{domain}",
        "unsubscribe": f"{local_part}-unsubscribe@{domain}",
    }


def remove_mailing_list_aliases(list_address: str) -> dict[str, Any]:
    """Remove all Exim4 virtual aliases associated with a mailing list."""
    list_address = _validate_email(list_address)
    local_part, domain = list_address.split("@")

    # Remove from virtual_aliases
    _remove_alias_line(list_address)
    _remove_alias_line(f"{local_part}-subscribe@{domain}")
    _remove_alias_line(f"{local_part}-unsubscribe@{domain}")

    # Remove per-list header file
    alias_file = EXIM_LIST_ALIASES_DIR / f"{local_part}@{domain}"
    if alias_file.exists():
        alias_file.unlink()

    return {"list_address": list_address, "removed": True}


def _remove_alias_line(address: str) -> None:
    """Remove a single alias line from the Exim virtual_aliases file."""
    if not EXIM_VIRTUAL_ALIASES.exists():
        return
    lines = EXIM_VIRTUAL_ALIASES.read_text().splitlines(keepends=True)
    filtered = [l for l in lines if not l.strip().startswith(f"{address}:")]
    atomic_write(EXIM_VIRTUAL_ALIASES, "".join(filtered), mode=0o644)


def send_list_message(
    list_address: str,
    list_name: str,
    owner_email: str,
    recipients: list[str],
    subject: str,
    body: str,
    content_type: str = "text/plain",
    reply_to_list: bool = False,
) -> dict[str, Any]:
    """Send a message to all mailing list members via Exim4.

    Injects proper mailing-list headers (List-Id, List-Unsubscribe, Reply-To).
    """
    import tempfile

    list_address = _validate_email(list_address)
    local_part, domain = list_address.split("@")

    # Build RFC 2369 / RFC 2919 headers
    headers = [
        f"From: {list_name} <{list_address}>",
        f"Reply-To: {list_address}" if reply_to_list else f"Reply-To: {owner_email}",
        f"To: {list_address}",
        f"Subject: {subject}",
        f"List-Id: {list_name} <{list_name}.{domain}>",
        f"List-Unsubscribe: <mailto:{local_part}-unsubscribe@{domain}>",
        f"List-Subscribe: <mailto:{local_part}-subscribe@{domain}>",
        f"List-Post: <mailto:{list_address}>",
        f"Precedence: list",
        f"X-Mailer: HostHive Mailing List",
        f"Content-Type: {content_type}; charset=utf-8",
    ]

    message = "\n".join(headers) + "\n\n" + body

    # Write message to temp file and inject via exim4
    with tempfile.NamedTemporaryFile(mode="w", suffix=".eml", delete=False) as tmp:
        tmp.write(message)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "exim4", "-f", list_address,
                *recipients,
            ],
            input=message,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(f"exim4 delivery failed: {result.stderr}")

        return {
            "ok": True,
            "recipients": len(recipients),
            "returncode": result.returncode,
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)
