"""
Nginx virtual-host executor.

Manages vhost creation / deletion, SSL enablement, and service reloading.
All subprocess calls use list arguments -- shell=True is NEVER used.
All file writes are atomic (write to temp then rename).

Templates are loaded from the shared ``data/templates/nginx/`` directory
via ``nginx_service.render_vhost`` -- single source of truth.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from agent.executors._helpers import (
    atomic_write,
    safe_domain,
    safe_path,
)

# Import the shared rendering function -- single source of truth
from api.services.nginx_service import render_vhost, list_templates  # noqa: F401

SITES_AVAILABLE = Path("/etc/nginx/sites-available")
SITES_ENABLED = Path("/etc/nginx/sites-enabled")


def create_vhost(
    domain: str,
    document_root: str,
    php_version: str,
    ssl: bool = False,
    ssl_certificate: str | None = None,
    ssl_certificate_key: str | None = None,
    template_name: str = "default",
    custom_nginx_config: str | None = None,
    backend_port: int = 8080,
) -> dict[str, Any]:
    """Write an nginx vhost config and enable it."""
    domain = safe_domain(domain)
    document_root = safe_path(document_root, "/home")

    content = render_vhost(
        template_name=template_name,
        domain=domain,
        document_root=document_root,
        php_version=php_version,
        ssl=ssl,
        ssl_certificate=ssl_certificate,
        ssl_certificate_key=ssl_certificate_key,
        backend_port=backend_port,
        custom_nginx_config=custom_nginx_config,
    )

    conf_path = SITES_AVAILABLE / domain
    atomic_write(conf_path, content)

    link_path = SITES_ENABLED / domain
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(conf_path)

    return {"domain": domain, "config": str(conf_path), "enabled": True}


def enable_ssl(
    domain: str,
    cert_path: str,
    key_path: str,
    template_name: str = "default",
    custom_nginx_config: str | None = None,
) -> dict[str, Any]:
    """Re-render the vhost with SSL using the provided certificate paths."""
    domain = safe_domain(domain)
    cert_path = safe_path(cert_path, "/etc/ssl")
    key_path = safe_path(key_path, "/etc/ssl")

    conf_path = SITES_AVAILABLE / domain
    if not conf_path.exists():
        raise FileNotFoundError(f"vhost config not found for {domain}")

    # Read existing config to extract document_root and php_version
    existing = conf_path.read_text()
    root_match = re.search(r"root\s+(.+);", existing)
    php_match = re.search(r"php(\d+\.\d+)-fpm", existing)

    document_root = root_match.group(1).strip() if root_match else f"/home/{domain}/public_html"
    php_version = php_match.group(1) if php_match else "8.2"

    content = render_vhost(
        template_name=template_name,
        domain=domain,
        document_root=document_root,
        php_version=php_version,
        ssl=True,
        ssl_certificate=cert_path,
        ssl_certificate_key=key_path,
        custom_nginx_config=custom_nginx_config,
    )

    atomic_write(conf_path, content)
    return {"domain": domain, "ssl": True}


def delete_vhost(domain: str) -> dict[str, Any]:
    """Remove vhost config and symlink."""
    domain = safe_domain(domain)

    link_path = SITES_ENABLED / domain
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()

    conf_path = SITES_AVAILABLE / domain
    if conf_path.exists():
        conf_path.unlink()

    return {"domain": domain, "deleted": True}


def reload_nginx() -> dict[str, Any]:
    """Reload nginx service.  Never uses shell=True."""
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


def list_vhosts() -> list[str]:
    """Return list of enabled vhost names."""
    if not SITES_ENABLED.is_dir():
        return []
    return sorted(
        entry.name
        for entry in SITES_ENABLED.iterdir()
        if entry.name != "default"
    )


def get_nginx_status() -> dict[str, Any]:
    """Run nginx -t and return service status."""
    test = subprocess.run(
        ["nginx", "-t"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    status = subprocess.run(
        ["systemctl", "is-active", "nginx"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {
        "config_test_ok": test.returncode == 0,
        "config_test_output": test.stderr.strip(),
        "service_active": status.stdout.strip() == "active",
    }
