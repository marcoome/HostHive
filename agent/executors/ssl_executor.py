"""
SSL / TLS certificate executor.

Manages Let's Encrypt issuance / renewal / revocation and custom certificate
installation.  Uses the ``cryptography`` library for certificate parsing.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.executors._helpers import (
    atomic_write_bytes,
    safe_domain,
    safe_path,
)

SSL_DIR = Path("/etc/ssl/hosthive")


# ------------------------------------------------------------------
# Let's Encrypt
# ------------------------------------------------------------------


def issue_letsencrypt(domain: str, email: str) -> dict[str, Any]:
    """Issue a certificate via certbot using the nginx plugin."""
    domain = safe_domain(domain)

    result = subprocess.run(
        [
            "certbot", "certonly",
            "--nginx",
            "--non-interactive",
            "--agree-tos",
            "--email", email,
            "-d", domain,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "domain": domain,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def renew_certificate(domain: str) -> dict[str, Any]:
    """Renew a specific certificate."""
    domain = safe_domain(domain)

    result = subprocess.run(
        ["certbot", "renew", "--cert-name", domain, "--non-interactive"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "domain": domain,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def revoke_certificate(domain: str) -> dict[str, Any]:
    """Revoke a Let's Encrypt certificate."""
    domain = safe_domain(domain)

    result = subprocess.run(
        [
            "certbot", "revoke",
            "--cert-name", domain,
            "--non-interactive",
            "--delete-after-revoke",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "domain": domain,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ------------------------------------------------------------------
# Custom certificates
# ------------------------------------------------------------------


def install_custom_cert(domain: str, cert_pem: str, key_pem: str) -> dict[str, Any]:
    """Install a user-supplied certificate + key to the HostHive SSL directory."""
    domain = safe_domain(domain)

    cert_dir = SSL_DIR / domain
    cert_dir.mkdir(parents=True, exist_ok=True)

    cert_path = cert_dir / "fullchain.pem"
    key_path = cert_dir / "privkey.pem"

    atomic_write_bytes(cert_path, cert_pem.encode("utf-8"), mode=0o644)
    atomic_write_bytes(key_path, key_pem.encode("utf-8"), mode=0o600)

    return {
        "domain": domain,
        "cert_path": str(cert_path),
        "key_path": str(key_path),
    }


# ------------------------------------------------------------------
# Inspection
# ------------------------------------------------------------------


def get_expiry(domain: str) -> dict[str, Any]:
    """Read the certificate for *domain* and return its expiry date."""
    domain = safe_domain(domain)

    # Try HostHive SSL dir first, then Let's Encrypt live dir
    candidates = [
        SSL_DIR / domain / "fullchain.pem",
        Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem"),
    ]

    cert_path = None
    for p in candidates:
        if p.exists():
            cert_path = p
            break

    if cert_path is None:
        raise FileNotFoundError(f"no certificate found for {domain}")

    from cryptography import x509
    from cryptography.hazmat.backends import default_backend

    pem_data = cert_path.read_bytes()
    cert = x509.load_pem_x509_certificate(pem_data, default_backend())

    not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
    not_before = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    days_remaining = (not_after - now).days

    return {
        "domain": domain,
        "issuer": cert.issuer.rfc4514_string(),
        "not_before": not_before.isoformat(),
        "not_after": not_after.isoformat(),
        "days_remaining": days_remaining,
        "expired": days_remaining < 0,
    }
