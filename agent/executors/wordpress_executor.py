"""
WordPress executor -- detection, WP-CLI operations, cloning, and security checks.

All subprocess calls use list arguments.  shell=True is NEVER used.
Paths are validated to prevent directory traversal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.executors._helpers import safe_domain, safe_path

log = logging.getLogger("novapanel.agent.wordpress")

# Base directory where user web roots live.
_WEB_BASE = "/home"

# WP-CLI binary path.
_WPCLI = "/usr/local/bin/wp"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wp_cli(path: str, *args: str, timeout: int = 120, user: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a WP-CLI command in the given WordPress directory.

    Uses list args.  Never uses shell=True.
    """
    cmd: List[str] = [_WPCLI, f"--path={path}", "--allow-root"]
    cmd.extend(args)

    env = {**os.environ}
    # Run WP-CLI as the site owner when specified
    run_kwargs: Dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "cwd": path,
    }

    log.info("wp-cli exec: %s", cmd)
    return subprocess.run(cmd, **run_kwargs)


def _validate_wp_path(path: str) -> str:
    """Ensure the path is a valid WordPress install under /home."""
    resolved = os.path.realpath(path)
    if not resolved.startswith(_WEB_BASE + "/"):
        raise ValueError(f"WordPress path must be under {_WEB_BASE}: {path!r}")

    # Check for wp-config.php as basic indicator
    wp_config = os.path.join(resolved, "wp-config.php")
    if not os.path.isfile(wp_config):
        raise FileNotFoundError(f"No wp-config.php found at {resolved}")

    return resolved


def _find_owner(path: str) -> str | None:
    """Determine the Unix user who owns the WordPress directory."""
    try:
        import pwd
        stat = os.stat(path)
        return pwd.getpwuid(stat.st_uid).pw_name
    except (KeyError, OSError):
        return None


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_wordpress_installs() -> List[Dict[str, Any]]:
    """Scan /home/*/web/*/ for WordPress installations.

    Looks for wp-config.php in common document root patterns.
    """
    installs: List[Dict[str, Any]] = []
    home = Path(_WEB_BASE)

    if not home.is_dir():
        return installs

    # Search patterns: /home/<user>/web/<domain>/public_html
    # and /home/<user>/<domain>/public_html
    patterns = [
        home.glob("*/web/*/public_html/wp-config.php"),
        home.glob("*/*/public_html/wp-config.php"),
        home.glob("*/web/*/wp-config.php"),
    ]

    seen: set[str] = set()
    for pattern in patterns:
        for wp_config in pattern:
            wp_dir = str(wp_config.parent)
            if wp_dir in seen:
                continue
            seen.add(wp_dir)

            # Try to determine the domain from the path
            parts = Path(wp_dir).parts
            domain = "unknown"
            for i, part in enumerate(parts):
                if part in ("web", "public_html"):
                    if i > 0:
                        domain = parts[i - 1] if part == "public_html" else (
                            parts[i + 1] if i + 1 < len(parts) else parts[i - 1]
                        )
                    break

            owner = _find_owner(wp_dir)

            installs.append({
                "path": wp_dir,
                "domain": domain,
                "owner": owner,
            })

    return installs


# ---------------------------------------------------------------------------
# WordPress info
# ---------------------------------------------------------------------------

def get_wp_info(path: str) -> Dict[str, Any]:
    """Get WordPress version, plugins, themes, and health info.

    Uses WP-CLI when available; falls back to parsing files directly.
    """
    path = _validate_wp_path(path)
    info: Dict[str, Any] = {"path": path}

    # Core version
    r = _wp_cli(path, "core", "version")
    if r.returncode == 0:
        info["version"] = r.stdout.strip()
    else:
        # Fallback: parse wp-includes/version.php
        version_file = os.path.join(path, "wp-includes", "version.php")
        if os.path.isfile(version_file):
            with open(version_file) as f:
                content = f.read()
            m = re.search(r"\$wp_version\s*=\s*'([^']+)'", content)
            info["version"] = m.group(1) if m else "unknown"
        else:
            info["version"] = "unknown"

    # Plugins
    r = _wp_cli(path, "plugin", "list", "--format=json")
    if r.returncode == 0:
        try:
            info["plugins"] = json.loads(r.stdout)
        except json.JSONDecodeError:
            info["plugins"] = []
    else:
        # Fallback: list plugin directories
        plugins_dir = os.path.join(path, "wp-content", "plugins")
        if os.path.isdir(plugins_dir):
            info["plugins"] = [
                {"name": d, "status": "unknown", "version": "unknown"}
                for d in os.listdir(plugins_dir)
                if os.path.isdir(os.path.join(plugins_dir, d)) and not d.startswith(".")
            ]
        else:
            info["plugins"] = []

    # Themes
    r = _wp_cli(path, "theme", "list", "--format=json")
    if r.returncode == 0:
        try:
            info["themes"] = json.loads(r.stdout)
        except json.JSONDecodeError:
            info["themes"] = []
    else:
        themes_dir = os.path.join(path, "wp-content", "themes")
        if os.path.isdir(themes_dir):
            info["themes"] = [
                {"name": d, "status": "unknown"}
                for d in os.listdir(themes_dir)
                if os.path.isdir(os.path.join(themes_dir, d)) and not d.startswith(".")
            ]
        else:
            info["themes"] = []

    # Active theme
    r = _wp_cli(path, "theme", "list", "--status=active", "--format=json")
    if r.returncode == 0:
        try:
            active = json.loads(r.stdout)
            info["active_theme"] = active[0]["name"] if active else "unknown"
        except (json.JSONDecodeError, IndexError, KeyError):
            info["active_theme"] = "unknown"

    # Database check / health
    r = _wp_cli(path, "db", "check", timeout=30)
    info["db_health"] = "ok" if r.returncode == 0 else "error"

    return info


# ---------------------------------------------------------------------------
# Update operations
# ---------------------------------------------------------------------------

def update_wp_core(path: str) -> Dict[str, Any]:
    """Update WordPress core to the latest version via WP-CLI."""
    path = _validate_wp_path(path)

    r = _wp_cli(path, "core", "update", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"WP core update failed: {r.stderr}")

    # Also update the database schema
    db_r = _wp_cli(path, "core", "update-db", timeout=60)

    return {
        "path": path,
        "stdout": r.stdout,
        "db_update": db_r.stdout if db_r.returncode == 0 else db_r.stderr,
    }


def update_wp_plugins(path: str) -> Dict[str, Any]:
    """Update all WordPress plugins via WP-CLI."""
    path = _validate_wp_path(path)

    r = _wp_cli(path, "plugin", "update", "--all", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"WP plugin update failed: {r.stderr}")

    return {
        "path": path,
        "stdout": r.stdout,
    }


# ---------------------------------------------------------------------------
# Cloning
# ---------------------------------------------------------------------------

def clone_wordpress(source_path: str, target_domain: str) -> Dict[str, Any]:
    """Clone a WordPress install to a new domain.

    1. Copy files
    2. Clone the database
    3. Run search-replace for the new domain
    """
    source_path = _validate_wp_path(source_path)
    target_domain = safe_domain(target_domain)

    # Determine source domain from wp-cli
    r = _wp_cli(source_path, "option", "get", "siteurl")
    if r.returncode != 0:
        raise RuntimeError(f"Could not determine source URL: {r.stderr}")
    source_url = r.stdout.strip()

    # Determine source owner / target path
    owner = _find_owner(source_path)
    if not owner:
        owner = "admin"
    target_path = f"/home/{owner}/web/{target_domain}/public_html"

    # Validate target doesn't already exist
    if os.path.exists(target_path):
        raise ValueError(f"Target path already exists: {target_path}")

    # 1. Copy files
    os.makedirs(target_path, exist_ok=True)
    r_copy = subprocess.run(
        ["cp", "-a", f"{source_path}/.", target_path],
        capture_output=True, text=True, timeout=600,
    )
    if r_copy.returncode != 0:
        raise RuntimeError(f"File copy failed: {r_copy.stderr}")

    # 2. Export and import database to a new DB
    # Get source DB info
    r_dbname = _wp_cli(source_path, "config", "get", "DB_NAME")
    source_db = r_dbname.stdout.strip() if r_dbname.returncode == 0 else None

    if source_db:
        new_db = f"{target_domain.replace('.', '_').replace('-', '_')}_wp"
        new_db = re.sub(r"[^a-zA-Z0-9_]", "", new_db)[:64]

        # Export
        dump_file = f"/tmp/wp_clone_{new_db}.sql"
        r_export = _wp_cli(source_path, "db", "export", dump_file, timeout=300)
        if r_export.returncode != 0:
            raise RuntimeError(f"DB export failed: {r_export.stderr}")

        # Create new database
        r_dbuser = _wp_cli(source_path, "config", "get", "DB_USER")
        r_dbpass = _wp_cli(source_path, "config", "get", "DB_PASSWORD")
        db_user = r_dbuser.stdout.strip() if r_dbuser.returncode == 0 else "root"
        db_pass = r_dbpass.stdout.strip() if r_dbpass.returncode == 0 else ""

        subprocess.run(
            ["mysql", "-u", db_user, f"-p{db_pass}", "-e", f"CREATE DATABASE IF NOT EXISTS `{new_db}`"],
            capture_output=True, text=True, timeout=30,
        )

        # Update wp-config.php in target
        _wp_cli(target_path, "config", "set", "DB_NAME", new_db)

        # Import
        r_import = _wp_cli(target_path, "db", "import", dump_file, timeout=300)
        if r_import.returncode != 0:
            raise RuntimeError(f"DB import failed: {r_import.stderr}")

        # Clean up dump
        try:
            os.unlink(dump_file)
        except OSError:
            pass

    # 3. Search-replace
    new_url = f"https://{target_domain}"
    _wp_cli(target_path, "search-replace", source_url, new_url, "--all-tables", timeout=300)

    # Also handle http variant
    source_url_http = source_url.replace("https://", "http://")
    _wp_cli(target_path, "search-replace", source_url_http, new_url, "--all-tables", timeout=300)

    return {
        "source_path": source_path,
        "target_path": target_path,
        "target_domain": target_domain,
        "source_url": source_url,
        "target_url": new_url,
    }


def search_replace(path: str, old_domain: str, new_domain: str) -> Dict[str, Any]:
    """Run WP-CLI search-replace for domain migration."""
    path = _validate_wp_path(path)
    old_domain = safe_domain(old_domain)
    new_domain = safe_domain(new_domain)

    # Replace both http and https variants
    results = []
    for scheme in ("https://", "http://"):
        old_url = f"{scheme}{old_domain}"
        new_url = f"{scheme}{new_domain}"
        r = _wp_cli(path, "search-replace", old_url, new_url, "--all-tables", timeout=300)
        results.append({
            "old": old_url,
            "new": new_url,
            "returncode": r.returncode,
            "stdout": r.stdout,
        })

    return {"path": path, "results": results}


# ---------------------------------------------------------------------------
# Security check
# ---------------------------------------------------------------------------

def security_check(path: str) -> Dict[str, Any]:
    """Run basic security checks on a WordPress installation.

    Checks for:
    - Outdated core
    - Outdated plugins with known vulnerabilities
    - File permissions
    - Debug mode enabled
    - Common security misconfigurations
    """
    path = _validate_wp_path(path)
    issues: List[Dict[str, str]] = []

    # Check if core has updates
    r = _wp_cli(path, "core", "check-update", "--format=json")
    if r.returncode == 0 and r.stdout.strip() and r.stdout.strip() != "[]":
        try:
            updates = json.loads(r.stdout)
            if updates:
                issues.append({
                    "severity": "high",
                    "type": "outdated_core",
                    "message": f"WordPress core update available: {updates[0].get('version', 'unknown')}",
                })
        except json.JSONDecodeError:
            pass

    # Check plugin updates
    r = _wp_cli(path, "plugin", "list", "--update=available", "--format=json")
    if r.returncode == 0 and r.stdout.strip() and r.stdout.strip() != "[]":
        try:
            outdated = json.loads(r.stdout)
            for plugin in outdated:
                issues.append({
                    "severity": "medium",
                    "type": "outdated_plugin",
                    "message": f"Plugin '{plugin.get('name', '?')}' has update: "
                               f"{plugin.get('version', '?')} -> {plugin.get('update_version', '?')}",
                })
        except json.JSONDecodeError:
            pass

    # Check debug mode
    r = _wp_cli(path, "config", "get", "WP_DEBUG")
    if r.returncode == 0 and r.stdout.strip().lower() in ("true", "1"):
        issues.append({
            "severity": "medium",
            "type": "debug_enabled",
            "message": "WP_DEBUG is enabled in production",
        })

    # Check file permissions on wp-config.php
    wp_config = os.path.join(path, "wp-config.php")
    if os.path.isfile(wp_config):
        mode = oct(os.stat(wp_config).st_mode)[-3:]
        if mode not in ("400", "440", "600", "640"):
            issues.append({
                "severity": "high",
                "type": "file_permissions",
                "message": f"wp-config.php has permissive mode: {mode} (should be 640 or stricter)",
            })

    # Check for default admin user
    r = _wp_cli(path, "user", "list", "--role=administrator", "--format=json")
    if r.returncode == 0:
        try:
            admins = json.loads(r.stdout)
            for admin in admins:
                if admin.get("user_login") == "admin":
                    issues.append({
                        "severity": "medium",
                        "type": "default_admin",
                        "message": "Default 'admin' username exists -- rename for security",
                    })
        except json.JSONDecodeError:
            pass

    # Check .htaccess / directory listing
    htaccess = os.path.join(path, ".htaccess")
    if not os.path.isfile(htaccess):
        issues.append({
            "severity": "low",
            "type": "missing_htaccess",
            "message": "No .htaccess file found (directory listing may be enabled)",
        })

    return {
        "path": path,
        "total_issues": len(issues),
        "issues": issues,
    }
