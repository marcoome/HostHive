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

    # Read existing serial if zone file already exists, then increment
    zone_file = ZONES_DIR / f"db.{domain}"
    existing_serial = None
    if zone_file.exists():
        import re as _re
        match = _re.search(r"(\d{10})\s*;\s*[Ss]erial", zone_file.read_text())
        if match:
            existing_serial = match.group(1)
    serial = increment_serial(existing_serial) if existing_serial else date.today().strftime("%Y%m%d") + "01"
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
# DNSSEC
# ------------------------------------------------------------------

KEYS_DIR = Path("/etc/bind/keys")

# Map algorithm names to dnssec-keygen -a values
_ALGO_MAP = {
    "ECDSAP256SHA256": "ECDSAP256SHA256",
    "ECDSAP384SHA384": "ECDSAP384SHA384",
    "RSASHA256": "RSASHA256",
    "RSASHA512": "RSASHA512",
}

_RSA_BITS = {"RSASHA256": 2048, "RSASHA512": 2048}


def enable_dnssec(
    domain: str,
    algorithm: str = "ECDSAP256SHA256",
) -> dict[str, Any]:
    """Generate KSK + ZSK, sign the zone, and return the DS record."""
    domain = safe_domain(domain)
    algo = _ALGO_MAP.get(algorithm, "ECDSAP256SHA256")
    KEYS_DIR.mkdir(parents=True, exist_ok=True)

    zone_file = ZONES_DIR / f"db.{domain}"
    if not zone_file.exists():
        raise FileNotFoundError(f"zone file not found for {domain}")

    # Generate KSK
    ksk_cmd = ["dnssec-keygen", "-K", str(KEYS_DIR), "-a", algo, "-f", "KSK", "-n", "ZONE", domain]
    if algo in _RSA_BITS:
        ksk_cmd.extend(["-b", str(_RSA_BITS[algo])])
    ksk_result = subprocess.run(ksk_cmd, capture_output=True, text=True, timeout=60)
    if ksk_result.returncode != 0:
        raise RuntimeError(f"KSK generation failed: {ksk_result.stderr}")
    ksk_name = ksk_result.stdout.strip().split("\n")[-1].strip()

    # Generate ZSK
    zsk_cmd = ["dnssec-keygen", "-K", str(KEYS_DIR), "-a", algo, "-n", "ZONE", domain]
    if algo in _RSA_BITS:
        zsk_cmd.extend(["-b", "1024"])
    zsk_result = subprocess.run(zsk_cmd, capture_output=True, text=True, timeout=60)
    if zsk_result.returncode != 0:
        raise RuntimeError(f"ZSK generation failed: {zsk_result.stderr}")
    zsk_name = zsk_result.stdout.strip().split("\n")[-1].strip()

    # Append $INCLUDE directives to zone file
    content = zone_file.read_text()
    ksk_inc = f'$INCLUDE "{KEYS_DIR}/{ksk_name}.key"'
    zsk_inc = f'$INCLUDE "{KEYS_DIR}/{zsk_name}.key"'
    if ksk_inc not in content:
        content = content.rstrip("\n") + "\n" + ksk_inc + "\n"
    if zsk_inc not in content:
        content = content.rstrip("\n") + "\n" + zsk_inc + "\n"
    atomic_write(zone_file, content, mode=0o644)

    # Sign the zone
    sign_result = _sign_zone_sync(domain, zone_file)

    # Update named.conf.local to use .signed file
    _update_named_conf_signed(domain, zone_file)

    # Extract DS record
    ds_record = _extract_ds_sync(domain)

    return {
        "domain": domain,
        "algorithm": algo,
        "ksk": ksk_name,
        "zsk": zsk_name,
        "ds_record": ds_record,
        "signed": sign_result.returncode == 0,
    }


def disable_dnssec(domain: str) -> dict[str, Any]:
    """Remove DNSSEC keys and unsigned the zone."""
    domain = safe_domain(domain)
    zone_file = ZONES_DIR / f"db.{domain}"
    signed_file = Path(str(zone_file) + ".signed")

    # Remove signed zone file
    if signed_file.exists():
        signed_file.unlink()

    # Clean $INCLUDE lines from zone file
    if zone_file.exists():
        content = zone_file.read_text()
        lines = content.splitlines()
        cleaned = [l for l in lines if not l.strip().startswith("$INCLUDE") or "/keys/" not in l]
        atomic_write(zone_file, "\n".join(cleaned) + "\n", mode=0o644)

    # Remove key files
    fqdn = domain.rstrip(".") + "."
    if KEYS_DIR.exists():
        for p in KEYS_DIR.iterdir():
            if p.name.startswith(f"K{fqdn}+") or p.name.startswith(f"K{domain}+"):
                p.unlink()

    # Revert named.conf.local
    _revert_named_conf_signed(domain, zone_file)

    return {"domain": domain, "dnssec_disabled": True}


def resign_zone(domain: str) -> dict[str, Any]:
    """Re-sign a DNSSEC-enabled zone after record changes."""
    domain = safe_domain(domain)
    zone_file = ZONES_DIR / f"db.{domain}"
    if not zone_file.exists():
        raise FileNotFoundError(f"zone file not found for {domain}")

    sign_result = _sign_zone_sync(domain, zone_file)
    return {
        "domain": domain,
        "signed": sign_result.returncode == 0,
        "output": sign_result.stdout + sign_result.stderr,
    }


def get_ds_record(domain: str) -> dict[str, Any]:
    """Extract and return the DS record for the zone."""
    domain = safe_domain(domain)
    ds = _extract_ds_sync(domain)
    return {"domain": domain, "ds_record": ds}


def _sign_zone_sync(domain: str, zone_file: Path) -> subprocess.CompletedProcess:
    """Sign a zone file with dnssec-signzone (synchronous)."""
    fqdn = domain.rstrip(".")

    # Find KSK key file
    ksk_file = None
    if KEYS_DIR.exists():
        for p in KEYS_DIR.iterdir():
            if p.name.startswith(f"K{fqdn}.+") and p.suffix == ".key":
                content = p.read_text()
                if "257" in content.split("\n")[0]:
                    ksk_file = str(p.with_suffix(""))
                    break

    sign_cmd = [
        "dnssec-signzone",
        "-A", "-3", "-", "-N", "INCREMENT",
        "-o", fqdn, "-t",
        "-K", str(KEYS_DIR),
    ]
    if ksk_file:
        sign_cmd.extend(["-k", ksk_file])
    sign_cmd.append(str(zone_file))

    return subprocess.run(sign_cmd, capture_output=True, text=True, timeout=120, cwd=str(zone_file.parent))


def _extract_ds_sync(domain: str) -> str | None:
    """Extract DS record from the KSK."""
    fqdn = domain.rstrip(".") + "."
    if not KEYS_DIR.exists():
        return None
    for p in KEYS_DIR.iterdir():
        if p.name.startswith(f"K{fqdn}+") and p.suffix == ".key":
            content = p.read_text()
            if "257" in content.split("\n")[0]:
                result = subprocess.run(
                    ["dnssec-dsfromkey", "-2", str(p)],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
    return None


def _update_named_conf_signed(domain: str, zone_file: Path) -> None:
    """Update named.conf.local to use the .signed zone file."""
    if not NAMED_CONF_LOCAL.exists():
        return
    content = NAMED_CONF_LOCAL.read_text()
    zone_path = str(zone_file)
    signed_path = zone_path + ".signed"
    new_content = content.replace(f'file "{zone_path}";', f'file "{signed_path}";')
    if new_content != content:
        atomic_write(NAMED_CONF_LOCAL, new_content, mode=0o644)


def _revert_named_conf_signed(domain: str, zone_file: Path) -> None:
    """Revert named.conf.local to the unsigned zone file."""
    if not NAMED_CONF_LOCAL.exists():
        return
    content = NAMED_CONF_LOCAL.read_text()
    zone_path = str(zone_file)
    signed_path = zone_path + ".signed"
    new_content = content.replace(f'file "{signed_path}";', f'file "{zone_path}";')
    if new_content != content:
        atomic_write(NAMED_CONF_LOCAL, new_content, mode=0o644)


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


def _ensure_named_entry(
    domain: str,
    zone_file: Path,
    cluster_ips: list[str] | None = None,
) -> None:
    """Add a zone stanza to named.conf.local if not already present.

    When *cluster_ips* is provided, ``allow-transfer`` and ``also-notify``
    directives are included to support AXFR/IXFR zone transfers.
    """
    marker = f'zone "{domain}"'

    if cluster_ips:
        ip_list = "; ".join(cluster_ips)
        transfer_line = f"    allow-transfer {{ {ip_list}; }};\n"
        notify_line = f"    also-notify {{ {ip_list}; }};\n"
    else:
        transfer_line = "    allow-transfer { none; };\n"
        notify_line = ""

    stanza = (
        f'\nzone "{domain}" {{\n'
        f"    type master;\n"
        f'    file "{zone_file}";\n'
        f"{transfer_line}"
        f"{notify_line}"
        f"}};\n"
    )

    if NAMED_CONF_LOCAL.exists():
        existing = NAMED_CONF_LOCAL.read_text()
        # Replace existing stanza if present so cluster IPs stay current
        old_pattern = re.compile(
            rf'\n?zone\s+"{re.escape(domain)}"\s*\{{[^}}]*\}};\n?',
            re.DOTALL,
        )
        if old_pattern.search(existing):
            new_content = old_pattern.sub(stanza, existing)
            atomic_write(NAMED_CONF_LOCAL, new_content, mode=0o644)
            return
        if marker in existing:
            return
    else:
        existing = ""

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
