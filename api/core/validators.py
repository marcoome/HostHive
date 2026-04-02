"""Security validators and input sanitisation for HostHive.

Every function either returns a clean value or raises ``ValueError``
with a human-readable message.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from config.security import PASSWORD_MIN_LENGTH
except ImportError:
    PASSWORD_MIN_LENGTH = 8  # safe default if config module not on path

# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$")
_MAX_DOMAIN_LEN = 253


def sanitize_domain(domain: str) -> str:
    """Validate and return a cleaned domain name.

    Only ``[a-zA-Z0-9.-]`` are allowed.  Labels must not start or end
    with a hyphen.  Maximum length is 253 characters.
    """
    domain = domain.strip().lower()
    if not domain or len(domain) > _MAX_DOMAIN_LEN:
        raise ValueError(f"Domain must be between 1 and {_MAX_DOMAIN_LEN} characters.")
    if not _DOMAIN_RE.match(domain):
        raise ValueError(
            "Invalid domain — only letters, digits, hyphens, and dots are allowed."
        )
    # Each label between dots must be 1-63 chars and not start/end with hyphen
    for label in domain.split("."):
        if not label or len(label) > 63:
            raise ValueError(f"Invalid domain label: '{label}'.")
        if label.startswith("-") or label.endswith("-"):
            raise ValueError(f"Domain label '{label}' must not start or end with a hyphen.")
    return domain


# ---------------------------------------------------------------------------
# Path traversal prevention
# ---------------------------------------------------------------------------


def sanitize_path(path: str, base_dir: str) -> Path:
    """Resolve *path* and ensure it stays within *base_dir*.

    Rejects any traversal attempt (e.g. ``../``).
    """
    base = Path(base_dir).resolve()
    target = (base / path).resolve()
    if not str(target).startswith(str(base) + "/") and target != base:
        raise ValueError("Path traversal detected — access denied.")
    return target


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

_SPECIAL_CHARS = set("!@#$%^&*()_+-=[]{}|;':\",./<>?`~")


def validate_password(password: str) -> None:
    """Enforce password complexity requirements.

    Raises ``ValueError`` with a descriptive message on failure.
    """
    errors: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    if not any(c.isupper() for c in password):
        errors.append("at least 1 uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("at least 1 lowercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("at least 1 digit")
    if not any(c in _SPECIAL_CHARS for c in password):
        errors.append("at least 1 special character")
    if errors:
        raise ValueError("Password must contain: " + "; ".join(errors) + ".")


# ---------------------------------------------------------------------------
# Shell argument sanitisation
# ---------------------------------------------------------------------------

_SHELL_DANGEROUS = set(";&|`$(){}[]!#~<>\\'\"\n\r\x00")


def sanitize_shell_arg(arg: str) -> str:
    """Reject *arg* if it contains characters dangerous in a shell context."""
    bad = _SHELL_DANGEROUS.intersection(arg)
    if bad:
        raise ValueError(
            f"Argument contains disallowed characters: {', '.join(sorted(repr(c) for c in bad))}"
        )
    if ".." in arg:
        raise ValueError("Argument must not contain '..'.")
    return arg


# ---------------------------------------------------------------------------
# Email (RFC 5322 simplified)
# ---------------------------------------------------------------------------

# Practical regex that covers the vast majority of valid addresses.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def validate_email_address(email: str) -> str:
    """Validate an email address against a practical RFC 5322 subset.

    Returns the lowercased email on success.
    """
    email = email.strip().lower()
    if not email or len(email) > 254:
        raise ValueError("Email address is empty or too long.")
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email address: {email}")
    # Must have at least one dot in the domain part
    _, _, domain_part = email.rpartition("@")
    if "." not in domain_part:
        raise ValueError(f"Invalid email domain: {domain_part}")
    return email


# ---------------------------------------------------------------------------
# Cron expression
# ---------------------------------------------------------------------------

_CRON_FIELD_RE = re.compile(r"^[\d,\-\*/]+$")
_CRON_SPECIAL = {"@reboot", "@yearly", "@annually", "@monthly", "@weekly", "@daily", "@hourly"}


def validate_cron_expression(expr: str) -> str:
    """Validate a standard 5-field cron expression or a named schedule.

    Returns the original expression on success.
    """
    expr = expr.strip()
    if expr in _CRON_SPECIAL:
        return expr

    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have exactly 5 fields (minute hour dom month dow).")

    field_ranges = [
        ("minute", 0, 59),
        ("hour", 0, 23),
        ("day of month", 1, 31),
        ("month", 1, 12),
        ("day of week", 0, 7),
    ]

    for (name, low, high), part in zip(field_ranges, parts):
        if not _CRON_FIELD_RE.match(part):
            raise ValueError(f"Invalid character in cron field '{name}': {part}")
        # Validate numeric values are in range (skip * and ranges for brevity)
        for token in part.replace("-", ",").replace("/", ",").split(","):
            if token == "*":
                continue
            if token.isdigit():
                val = int(token)
                if val < low or val > high:
                    raise ValueError(
                        f"Cron field '{name}' value {val} out of range ({low}-{high})."
                    )
    return expr


# ---------------------------------------------------------------------------
# SQL identifier
# ---------------------------------------------------------------------------

_SQL_IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")
_MAX_SQL_IDENT_LEN = 63


def sanitize_sql_identifier(name: str) -> str:
    """Ensure *name* is a safe SQL identifier (database / user name).

    Only ``[a-zA-Z0-9_]`` is allowed.  Max 63 characters.
    """
    name = name.strip()
    if not name or len(name) > _MAX_SQL_IDENT_LEN:
        raise ValueError(f"SQL identifier must be 1-{_MAX_SQL_IDENT_LEN} characters.")
    if not _SQL_IDENT_RE.match(name):
        raise ValueError(
            "SQL identifier contains invalid characters — only letters, digits, and underscores are allowed."
        )
    return name
