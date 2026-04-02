"""
WAF (Web Application Firewall) executor -- Nginx Naxsi-style rule management.

Manages per-domain WAF configuration: enable/disable, custom rules,
detect vs block mode, and blocked-request log parsing.

All subprocess calls use list arguments.  shell=True is NEVER used.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.executors._helpers import atomic_write, safe_domain

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
WAF_CONF_DIR = Path("/etc/nginx/waf")
WAF_RULES_DIR = WAF_CONF_DIR / "rules"
WAF_CUSTOM_DIR = WAF_CONF_DIR / "custom"
WAF_LOG_DIR = Path("/var/log/nginx/waf")
WAF_DEFAULT_RULES = Path(__file__).resolve().parent.parent.parent / "data" / "templates" / "waf_rules.conf"

_WAF_INCLUDE_MARKER = "# HostHive WAF include"
_WAF_INCLUDE_PATTERN = re.compile(
    r"^\s*#\s*HostHive WAF include\s*\n\s*include\s+/etc/nginx/waf/[^;]+;\s*$",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_waf_dirs() -> None:
    """Create WAF directories if they do not exist."""
    for d in (WAF_CONF_DIR, WAF_RULES_DIR, WAF_CUSTOM_DIR, WAF_LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _domain_waf_conf(domain: str) -> Path:
    """Return the per-domain WAF config path."""
    return WAF_RULES_DIR / f"{domain}.conf"


def _domain_custom_conf(domain: str) -> Path:
    """Return the per-domain custom rules path."""
    return WAF_CUSTOM_DIR / f"{domain}.conf"


def _domain_waf_log(domain: str) -> Path:
    """Return the per-domain WAF log path."""
    return WAF_LOG_DIR / f"{domain}.log"


def _domain_waf_meta(domain: str) -> Path:
    """Return the per-domain WAF metadata (mode, etc.)."""
    return WAF_CONF_DIR / f"{domain}.meta.json"


def _read_meta(domain: str) -> dict[str, Any]:
    """Read WAF metadata for a domain."""
    meta_path = _domain_waf_meta(domain)
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {"mode": "detect", "enabled": False}


def _write_meta(domain: str, meta: dict[str, Any]) -> None:
    """Write WAF metadata for a domain."""
    atomic_write(_domain_waf_meta(domain), json.dumps(meta, indent=2), mode=0o644)


def _generate_waf_conf(domain: str, mode: str = "detect") -> str:
    """Generate the Nginx WAF configuration snippet for a domain.

    In 'detect' mode, violations are logged but not blocked.
    In 'block' mode, violations return 403.
    """
    log_path = _domain_waf_log(domain)
    custom_path = _domain_custom_conf(domain)

    # Naxsi-style configuration using Nginx map + access rules
    # We use a combination of Nginx's built-in features for WAF
    block_action = "return 403" if mode == "block" else "access_log " + str(log_path)

    lines = [
        f"# HostHive WAF configuration for {domain}",
        f"# Mode: {mode}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}Z",
        "",
        "# Load default WAF rules",
        f"include {WAF_DEFAULT_RULES};",
        "",
    ]

    # Include custom rules if they exist
    if custom_path.exists():
        lines.extend([
            "# Custom rules",
            f"include {custom_path};",
            "",
        ])

    lines.extend([
        f"# WAF log for blocked/detected requests",
        f"set $waf_log_path {log_path};",
        f"set $waf_mode {mode};",
        "",
        "# Block requests matching WAF rules",
        "if ($waf_block = 1) {",
    ])

    if mode == "block":
        lines.append("    return 403;")
    else:
        lines.append(f"    access_log {log_path} waf_log;")
    lines.extend([
        "}",
        "",
    ])

    return "\n".join(lines)


def _add_waf_to_vhost(domain: str) -> bool:
    """Add WAF include directive to the domain's Nginx vhost config.

    Returns True if modified, False if already present.
    """
    conf_path = NGINX_SITES_AVAILABLE / domain
    if not conf_path.exists():
        raise FileNotFoundError(f"vhost config not found for {domain}")

    content = conf_path.read_text()

    # Check if WAF include is already present
    if _WAF_INCLUDE_MARKER in content:
        return False

    waf_conf = _domain_waf_conf(domain)

    # Insert WAF include inside the server block, after the first '{'
    # Find the first server { block
    insert_line = f"\n    {_WAF_INCLUDE_MARKER}\n    include {waf_conf};\n"

    # Insert after the first opening brace of the server block
    match = re.search(r"(server\s*\{)", content)
    if match:
        pos = match.end()
        content = content[:pos] + insert_line + content[pos:]
    else:
        raise ValueError(f"Could not find server block in vhost config for {domain}")

    atomic_write(conf_path, content)
    return True


def _remove_waf_from_vhost(domain: str) -> bool:
    """Remove WAF include directive from the domain's Nginx vhost config.

    Returns True if modified, False if not present.
    """
    conf_path = NGINX_SITES_AVAILABLE / domain
    if not conf_path.exists():
        raise FileNotFoundError(f"vhost config not found for {domain}")

    content = conf_path.read_text()

    if _WAF_INCLUDE_MARKER not in content:
        return False

    # Remove the WAF include lines
    new_lines = []
    skip_next = False
    for line in content.splitlines(keepends=True):
        if _WAF_INCLUDE_MARKER in line:
            skip_next = True
            continue
        if skip_next and "include" in line and "/etc/nginx/waf/" in line:
            skip_next = False
            continue
        skip_next = False
        new_lines.append(line)

    atomic_write(conf_path, "".join(new_lines))
    return True


def _reload_nginx() -> dict[str, Any]:
    """Test and reload Nginx."""
    test = subprocess.run(
        ["nginx", "-t"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if test.returncode != 0:
        raise ValueError(f"Nginx config test failed: {test.stderr}")

    result = subprocess.run(
        ["systemctl", "reload", "nginx"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enable_waf(domain: str) -> dict[str, Any]:
    """Enable WAF for a domain by adding WAF include to its Nginx vhost."""
    domain = safe_domain(domain)
    _ensure_waf_dirs()

    meta = _read_meta(domain)
    mode = meta.get("mode", "detect")

    # Generate WAF config
    waf_content = _generate_waf_conf(domain, mode)
    atomic_write(_domain_waf_conf(domain), waf_content)

    # Ensure custom rules file exists
    custom_path = _domain_custom_conf(domain)
    if not custom_path.exists():
        atomic_write(custom_path, f"# Custom WAF rules for {domain}\n")

    # Add WAF include to vhost
    modified = _add_waf_to_vhost(domain)

    # Update metadata
    meta["enabled"] = True
    meta["enabled_at"] = datetime.now(timezone.utc).isoformat() + "Z"
    _write_meta(domain, meta)

    # Reload Nginx
    reload_result = _reload_nginx()

    return {
        "domain": domain,
        "waf_enabled": True,
        "mode": mode,
        "vhost_modified": modified,
        "nginx_reload": reload_result,
    }


def disable_waf(domain: str) -> dict[str, Any]:
    """Disable WAF for a domain by removing WAF include from its Nginx vhost."""
    domain = safe_domain(domain)

    modified = _remove_waf_from_vhost(domain)

    # Update metadata
    meta = _read_meta(domain)
    meta["enabled"] = False
    meta["disabled_at"] = datetime.now(timezone.utc).isoformat() + "Z"
    _write_meta(domain, meta)

    # Reload Nginx
    reload_result = _reload_nginx()

    return {
        "domain": domain,
        "waf_enabled": False,
        "vhost_modified": modified,
        "nginx_reload": reload_result,
    }


def get_waf_status(domain: str) -> dict[str, Any]:
    """Return WAF status for a domain: enabled/disabled, mode, blocked count."""
    domain = safe_domain(domain)
    meta = _read_meta(domain)

    blocked_count = 0
    log_path = _domain_waf_log(domain)
    if log_path.exists():
        try:
            blocked_count = sum(1 for _ in log_path.open())
        except OSError:
            pass

    return {
        "domain": domain,
        "enabled": meta.get("enabled", False),
        "mode": meta.get("mode", "detect"),
        "blocked_requests": blocked_count,
        "enabled_at": meta.get("enabled_at"),
        "disabled_at": meta.get("disabled_at"),
    }


def get_waf_log(domain: str, lines: int = 100) -> dict[str, Any]:
    """Return recent WAF log entries for a domain."""
    domain = safe_domain(domain)

    if lines < 1:
        lines = 1
    if lines > 10000:
        lines = 10000

    log_path = _domain_waf_log(domain)
    if not log_path.exists():
        return {"domain": domain, "entries": [], "total": 0}

    # Read last N lines efficiently
    result = subprocess.run(
        ["tail", "-n", str(lines), str(log_path)],
        capture_output=True,
        text=True,
        timeout=15,
    )

    log_entries = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            log_entries.append(line.strip())

    return {
        "domain": domain,
        "entries": log_entries,
        "total": len(log_entries),
    }


def add_custom_rule(domain: str, rule: str) -> dict[str, Any]:
    """Add a custom WAF rule for a domain."""
    domain = safe_domain(domain)
    _ensure_waf_dirs()

    # Validate rule: must not contain dangerous characters
    if any(c in rule for c in ("`", "$(")):
        raise ValueError("Rule contains forbidden characters")

    custom_path = _domain_custom_conf(domain)
    existing = custom_path.read_text() if custom_path.exists() else f"# Custom WAF rules for {domain}\n"

    # Generate a simple rule ID based on line count
    rule_id = sum(1 for line in existing.splitlines() if line.strip() and not line.strip().startswith("#"))

    rule_line = f"# Rule ID: {rule_id}\n{rule}\n"
    atomic_write(custom_path, existing.rstrip("\n") + "\n" + rule_line + "\n")

    # Regenerate WAF config
    meta = _read_meta(domain)
    if meta.get("enabled"):
        waf_content = _generate_waf_conf(domain, meta.get("mode", "detect"))
        atomic_write(_domain_waf_conf(domain), waf_content)
        _reload_nginx()

    return {
        "domain": domain,
        "rule_id": rule_id,
        "rule": rule,
        "added": True,
    }


def delete_custom_rule(domain: str, rule_id: int) -> dict[str, Any]:
    """Delete a custom WAF rule by its ID."""
    domain = safe_domain(domain)

    custom_path = _domain_custom_conf(domain)
    if not custom_path.exists():
        raise FileNotFoundError(f"No custom rules found for {domain}")

    lines = custom_path.read_text().splitlines(keepends=True)
    new_lines = []
    skip_next = False
    found = False

    for line in lines:
        if f"# Rule ID: {rule_id}" in line:
            skip_next = True
            found = True
            continue
        if skip_next:
            skip_next = False
            continue
        new_lines.append(line)

    if not found:
        raise ValueError(f"Rule ID {rule_id} not found for {domain}")

    atomic_write(custom_path, "".join(new_lines))

    # Regenerate WAF config if enabled
    meta = _read_meta(domain)
    if meta.get("enabled"):
        waf_content = _generate_waf_conf(domain, meta.get("mode", "detect"))
        atomic_write(_domain_waf_conf(domain), waf_content)
        _reload_nginx()

    return {"domain": domain, "rule_id": rule_id, "deleted": True}


def list_rules(domain: str) -> dict[str, Any]:
    """List active WAF rules for a domain."""
    domain = safe_domain(domain)

    rules: list[dict[str, Any]] = []

    # Default rules
    if WAF_DEFAULT_RULES.exists():
        rule_id = 0
        for line in WAF_DEFAULT_RULES.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                rules.append({
                    "id": f"default-{rule_id}",
                    "type": "default",
                    "rule": line,
                })
                rule_id += 1

    # Custom rules
    custom_path = _domain_custom_conf(domain)
    if custom_path.exists():
        current_id: int | None = None
        for line in custom_path.read_text().splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("# Rule ID:"):
                try:
                    current_id = int(line_stripped.split(":")[-1].strip())
                except ValueError:
                    current_id = None
                continue
            if line_stripped and not line_stripped.startswith("#") and current_id is not None:
                rules.append({
                    "id": f"custom-{current_id}",
                    "type": "custom",
                    "rule": line_stripped,
                })
                current_id = None

    return {"domain": domain, "rules": rules, "total": len(rules)}


def set_waf_mode(domain: str, mode: str) -> dict[str, Any]:
    """Set WAF mode for a domain: 'detect' (log only) or 'block' (reject)."""
    domain = safe_domain(domain)

    if mode not in ("detect", "block"):
        raise ValueError(f"Invalid WAF mode: {mode!r}. Must be 'detect' or 'block'.")

    meta = _read_meta(domain)
    meta["mode"] = mode
    _write_meta(domain, meta)

    # Regenerate WAF config if enabled
    if meta.get("enabled"):
        _ensure_waf_dirs()
        waf_content = _generate_waf_conf(domain, mode)
        atomic_write(_domain_waf_conf(domain), waf_content)
        _reload_nginx()

    return {"domain": domain, "mode": mode}
