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


def create_alias(from_addr: str, to_addr: str) -> dict[str, Any]:
    """Add a virtual alias entry."""
    from_addr = _validate_email(from_addr)
    to_addr = _validate_email(to_addr)

    EXIM_VIRTUAL_ALIASES.parent.mkdir(parents=True, exist_ok=True)
    existing = EXIM_VIRTUAL_ALIASES.read_text() if EXIM_VIRTUAL_ALIASES.exists() else ""

    line = f"{from_addr}: {to_addr}"
    if line in existing:
        raise ValueError(f"alias already exists: {from_addr} -> {to_addr}")

    atomic_write(
        EXIM_VIRTUAL_ALIASES,
        existing.rstrip("\n") + "\n" + line + "\n",
        mode=0o644,
    )
    return {"from": from_addr, "to": to_addr}


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
