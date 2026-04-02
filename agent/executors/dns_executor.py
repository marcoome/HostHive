"""
BIND DNS zone executor.

Manages zone creation / deletion, record manipulation, and service reloading.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from agent.executors._helpers import (
    atomic_write,
    increment_serial,
    safe_domain,
    safe_path,
)

ZONES_DIR = Path("/etc/bind/zones")
NAMED_CONF_LOCAL = Path("/etc/bind/named.conf.local")
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "templates"

_jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)

_RECORD_TYPES = {"A", "AAAA", "MX", "TXT", "CNAME", "NS", "SRV", "CAA", "PTR"}


def create_zone(domain: str, ip: str) -> dict[str, Any]:
    """Create a new BIND zone file with sensible defaults."""
    domain = safe_domain(domain)
    _validate_ip(ip)

    serial = date.today().strftime("%Y%m%d") + "01"
    template = _jinja.get_template("dns_zone.j2")
    content = template.render(
        domain=domain,
        ip=ip,
        serial=serial,
    )

    zone_file = ZONES_DIR / f"db.{domain}"
    atomic_write(zone_file, content, mode=0o644)

    # Append zone declaration to named.conf.local if not present
    _ensure_named_entry(domain, zone_file)

    return {"domain": domain, "zone_file": str(zone_file)}


def delete_zone(domain: str) -> dict[str, Any]:
    """Remove a zone file and its named.conf.local entry."""
    domain = safe_domain(domain)

    zone_file = ZONES_DIR / f"db.{domain}"
    if zone_file.exists():
        zone_file.unlink()

    _remove_named_entry(domain)
    return {"domain": domain, "deleted": True}


def add_record(
    domain: str,
    record_type: str,
    name: str,
    value: str,
    ttl: int = 3600,
    priority: int | None = None,
) -> dict[str, Any]:
    """Append a DNS record to the zone file and bump the serial."""
    domain = safe_domain(domain)
    record_type = record_type.upper()
    if record_type not in _RECORD_TYPES:
        raise ValueError(f"unsupported record type: {record_type}")

    zone_file = ZONES_DIR / f"db.{domain}"
    if not zone_file.exists():
        raise FileNotFoundError(f"zone file not found for {domain}")

    content = zone_file.read_text()

    # Bump serial
    content = _bump_serial(content)

    # Build record line
    if record_type == "MX" and priority is not None:
        line = f"{name}\t{ttl}\tIN\t{record_type}\t{priority}\t{value}"
    else:
        line = f"{name}\t{ttl}\tIN\t{record_type}\t{value}"

    content = content.rstrip("\n") + "\n" + line + "\n"
    atomic_write(zone_file, content, mode=0o644)

    return {"domain": domain, "record": line}


def delete_record(domain: str, record_id: int) -> dict[str, Any]:
    """Delete a record by its 1-based line number (counting only non-SOA resource records)."""
    domain = safe_domain(domain)

    zone_file = ZONES_DIR / f"db.{domain}"
    if not zone_file.exists():
        raise FileNotFoundError(f"zone file not found for {domain}")

    lines = zone_file.read_text().splitlines(keepends=True)

    # Identify resource-record lines (lines containing IN and a record type)
    rr_pattern = re.compile(r"\bIN\s+(" + "|".join(_RECORD_TYPES) + r")\b")
    rr_indices: list[int] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith(";") and rr_pattern.search(stripped):
            # Skip the SOA record
            if "\tSOA\t" not in stripped and " SOA " not in stripped:
                rr_indices.append(i)

    if record_id < 1 or record_id > len(rr_indices):
        raise ValueError(f"record_id {record_id} out of range (1..{len(rr_indices)})")

    target = rr_indices[record_id - 1]
    removed = lines.pop(target)

    content = "".join(lines)
    content = _bump_serial(content)
    atomic_write(zone_file, content, mode=0o644)

    return {"domain": domain, "removed": removed.strip()}


def reload_bind() -> dict[str, Any]:
    """Reload BIND via rndc."""
    result = subprocess.run(
        ["rndc", "reload"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

_SERIAL_RE = re.compile(r"(\d{10})(\s*;\s*[Ss]erial)")


def _bump_serial(content: str) -> str:
    match = _SERIAL_RE.search(content)
    if match:
        old = match.group(1)
        new = increment_serial(old)
        content = content[: match.start(1)] + new + content[match.end(1) :]
    return content


def _validate_ip(ip: str) -> None:
    import ipaddress

    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"invalid IP address: {ip!r}")


def _ensure_named_entry(domain: str, zone_file: Path) -> None:
    """Add a zone stanza to named.conf.local if not already present."""
    marker = f'zone "{domain}"'
    if NAMED_CONF_LOCAL.exists():
        existing = NAMED_CONF_LOCAL.read_text()
        if marker in existing:
            return
    else:
        existing = ""

    stanza = (
        f'\nzone "{domain}" {{\n'
        f"    type master;\n"
        f'    file "{zone_file}";\n'
        f"}};\n"
    )
    atomic_write(NAMED_CONF_LOCAL, existing + stanza, mode=0o644)


def _remove_named_entry(domain: str) -> None:
    """Remove a zone stanza from named.conf.local."""
    if not NAMED_CONF_LOCAL.exists():
        return
    content = NAMED_CONF_LOCAL.read_text()
    # Remove the zone block for this domain
    pattern = re.compile(
        rf'\n?zone\s+"{re.escape(domain)}"\s*\{{[^}}]*\}};\n?',
        re.DOTALL,
    )
    new_content = pattern.sub("", content)
    if new_content != content:
        atomic_write(NAMED_CONF_LOCAL, new_content, mode=0o644)
