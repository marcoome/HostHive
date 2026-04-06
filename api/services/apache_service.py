"""Apache2 virtual host management service.

Mirrors the nginx_service API but targets Apache2 with mod_proxy_fcgi for PHP-FPM.
All file-system and process operations happen locally via asyncio.subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APACHE_SITES_AVAILABLE = Path("/etc/apache2/sites-available")
APACHE_SITES_ENABLED = Path("/etc/apache2/sites-enabled")
SSL_BASE_DIR = Path("/etc/ssl/hosthive")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


async def _apache_test_and_reload() -> tuple[bool, str]:
    """Run ``apachectl configtest`` then ``systemctl reload apache2``.

    Returns (success, message).
    """
    rc, out, err = await _run("apachectl configtest")
    if rc != 0:
        msg = f"Apache config test failed: {err or out}"
        logger.error(msg)
        return False, msg

    rc, out, err = await _run("systemctl reload apache2")
    if rc != 0:
        msg = f"Apache reload failed: {err or out}"
        logger.error(msg)
        return False, msg

    return True, "Apache reloaded successfully"


async def _ensure_modules(*modules: str) -> list[str]:
    """Enable required Apache modules if not already enabled.

    Returns a list of warnings (empty on full success).
    """
    warnings: list[str] = []
    for mod in modules:
        rc, _, err = await _run(f"a2query -m {mod} 2>/dev/null")
        if rc != 0:
            rc2, _, err2 = await _run(f"a2enmod {mod}")
            if rc2 != 0:
                warnings.append(f"Could not enable module {mod}: {err2}")
    return warnings


APACHE_PROXY_PORT = 8080


# ---------------------------------------------------------------------------
# Apache vhost config templates
# ---------------------------------------------------------------------------
def _build_http_vhost_proxy(
    domain: str,
    document_root: str,
    php_version: str,
    listen_port: int = APACHE_PROXY_PORT,
) -> str:
    """Return an Apache vhost that listens on *listen_port* (behind Nginx)."""
    return f"""<VirtualHost *:{listen_port}>
    ServerName {domain}
    ServerAlias www.{domain}
    DocumentRoot {document_root}

    <Directory {document_root}>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    <FilesMatch \\.php$>
        SetHandler "proxy:unix:/run/php/php{php_version}-fpm.sock|fcgi://localhost"
    </FilesMatch>

    ErrorLog /var/log/apache2/{domain}.error.log
    CustomLog /var/log/apache2/{domain}.access.log combined
</VirtualHost>
"""


def _build_http_vhost(
    domain: str,
    document_root: str,
    php_version: str,
) -> str:
    """Return an HTTP-only Apache virtual host."""
    return f"""<VirtualHost *:80>
    ServerName {domain}
    ServerAlias www.{domain}
    DocumentRoot {document_root}

    <Directory {document_root}>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    <FilesMatch \\.php$>
        SetHandler "proxy:unix:/run/php/php{php_version}-fpm.sock|fcgi://localhost"
    </FilesMatch>

    ErrorLog /var/log/apache2/{domain}.error.log
    CustomLog /var/log/apache2/{domain}.access.log combined
</VirtualHost>
"""


def _build_ssl_vhost(
    domain: str,
    document_root: str,
    php_version: str,
    cert_path: str,
    key_path: str,
) -> str:
    """Return a combined HTTP-redirect + HTTPS Apache virtual host."""
    return f"""<VirtualHost *:80>
    ServerName {domain}
    ServerAlias www.{domain}
    RewriteEngine On
    RewriteCond %{{HTTPS}} off
    RewriteRule ^(.*)$ https://%{{HTTP_HOST}}$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName {domain}
    ServerAlias www.{domain}
    DocumentRoot {document_root}

    SSLEngine on
    SSLCertificateFile {cert_path}
    SSLCertificateKeyFile {key_path}
    SSLProtocol -all +TLSv1.2 +TLSv1.3
    SSLCipherSuite HIGH:!aNULL:!MD5

    <Directory {document_root}>
        Options -Indexes +FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    <FilesMatch \\.php$>
        SetHandler "proxy:unix:/run/php/php{php_version}-fpm.sock|fcgi://localhost"
    </FilesMatch>

    ErrorLog /var/log/apache2/{domain}.ssl.error.log
    CustomLog /var/log/apache2/{domain}.ssl.access.log combined
</VirtualHost>
"""


# ---------------------------------------------------------------------------
# Public API -- Domains
# ---------------------------------------------------------------------------
async def create_vhost(
    domain: str,
    username: str,
    document_root: Optional[str] = None,
    php_version: str = "8.2",
) -> dict:
    """Create Apache vhost, document root, enable site, and reload.

    Returns ``{"ok": True, "warnings": []}`` on success or raises.
    """
    warnings: list[str] = []
    doc_root = document_root or f"/home/{username}/web/{domain}/public_html"

    # 0. Ensure required modules
    mod_warnings = await _ensure_modules(
        "proxy_fcgi", "rewrite", "headers", "ssl", "setenvif",
    )
    warnings.extend(mod_warnings)

    # 1. Create document root
    doc_root_path = Path(doc_root)
    try:
        doc_root_path.mkdir(parents=True, exist_ok=True)
        await _run(f"chown -R {username}:{username} /home/{username}/web")
    except Exception as exc:
        warnings.append(f"Could not create document root: {exc}")

    # 2. Create basic index.html
    index_path = doc_root_path / "index.html"
    if not index_path.exists():
        try:
            index_path.write_text(
                f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to {domain}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
        }}
        .card {{
            text-align: center; padding: 3rem;
            background: rgba(255,255,255,0.05);
            border-radius: 1rem; border: 1px solid rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
        }}
        h1 {{ margin-bottom: 0.5rem; }}
        p {{ color: #94a3b8; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{domain}</h1>
        <p>Your website is ready. Upload your files to get started.</p>
    </div>
</body>
</html>
""",
                encoding="utf-8",
            )
            await _run(f"chown {username}:{username} {index_path}")
        except Exception as exc:
            warnings.append(f"Could not create index.html: {exc}")

    # 3. Write Apache vhost config
    vhost_path = APACHE_SITES_AVAILABLE / f"{domain}.conf"
    try:
        vhost_path.write_text(
            _build_http_vhost(domain, doc_root, php_version),
            encoding="utf-8",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to write Apache config: {exc}") from exc

    # 4. Enable the site
    rc, _, err = await _run(f"a2ensite {domain}.conf")
    if rc != 0:
        warnings.append(f"a2ensite failed: {err}")

    # 5. Test & reload Apache
    ok, msg = await _apache_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def update_vhost_php(
    domain: str,
    document_root: str,
    new_php_version: str,
    ssl_enabled: bool = False,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
) -> dict:
    """Rewrite the Apache vhost with a new PHP version and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    vhost_path = APACHE_SITES_AVAILABLE / f"{domain}.conf"

    if not vhost_path.exists():
        raise RuntimeError(f"Apache config for {domain} does not exist.")

    if ssl_enabled and cert_path and key_path:
        config = _build_ssl_vhost(domain, document_root, new_php_version, cert_path, key_path)
    else:
        config = _build_http_vhost(domain, document_root, new_php_version)

    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write Apache config: {exc}") from exc

    ok, msg = await _apache_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def delete_vhost(domain: str) -> dict:
    """Disable and remove Apache vhost, then reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []

    # Disable the site
    rc, _, err = await _run(f"a2dissite {domain}.conf")
    if rc != 0:
        warnings.append(f"a2dissite failed (site may not exist): {err}")

    # Remove config file
    vhost_path = APACHE_SITES_AVAILABLE / f"{domain}.conf"
    try:
        if vhost_path.exists():
            vhost_path.unlink()
    except Exception as exc:
        warnings.append(f"Could not remove config: {exc}")

    # Reload Apache
    ok, msg = await _apache_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def read_log_file(path: str, lines: int = 100) -> str:
    """Read the last *lines* of a log file."""
    rc, out, err = await _run(f"tail -n {lines} {path}")
    if rc != 0:
        raise RuntimeError(f"Failed to read log: {err or out}")
    return out


# ---------------------------------------------------------------------------
# Public API -- SSL
# ---------------------------------------------------------------------------
async def apply_ssl(
    domain: str,
    document_root: str,
    php_version: str,
    cert_path: str,
    key_path: str,
) -> dict:
    """Rewrite the Apache vhost with SSL and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []

    # Ensure SSL module is enabled
    mod_warnings = await _ensure_modules("ssl", "rewrite")
    warnings.extend(mod_warnings)

    vhost_path = APACHE_SITES_AVAILABLE / f"{domain}.conf"
    config = _build_ssl_vhost(domain, document_root, php_version, cert_path, key_path)
    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write SSL Apache config: {exc}") from exc

    ok, msg = await _apache_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def install_custom_ssl(
    domain: str,
    certificate: str,
    private_key: str,
    chain: Optional[str] = None,
) -> dict:
    """Save uploaded cert/key to disk.

    Returns ``{"cert_path": ..., "key_path": ...}``.
    """
    cert_dir = SSL_BASE_DIR / domain
    cert_dir.mkdir(parents=True, exist_ok=True)

    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    cert_content = certificate
    if chain:
        cert_content = certificate.rstrip("\n") + "\n" + chain

    cert_path.write_text(cert_content, encoding="utf-8")
    key_path.write_text(private_key, encoding="utf-8")

    os.chmod(cert_path, 0o644)
    os.chmod(key_path, 0o600)

    return {"cert_path": str(cert_path), "key_path": str(key_path)}


async def issue_letsencrypt(domain: str, email: str) -> dict:
    """Run certbot to obtain a Let's Encrypt certificate for Apache.

    Returns ``{"cert_path": ..., "key_path": ...}`` on success.
    """
    cmd = (
        f"certbot certonly --apache -d {domain} "
        f"--non-interactive --agree-tos -m {email}"
    )
    rc, out, err = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"certbot failed: {err or out}")

    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"

    return {"cert_path": cert_path, "key_path": key_path}


async def create_vhost_proxy_mode(
    domain: str,
    username: str,
    document_root: Optional[str] = None,
    php_version: str = "8.2",
) -> dict:
    """Create Apache vhost on port 8080 (behind Nginx reverse proxy).

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    doc_root = document_root or f"/home/{username}/web/{domain}/public_html"

    # Ensure required modules
    mod_warnings = await _ensure_modules(
        "proxy_fcgi", "rewrite", "headers", "ssl", "setenvif",
    )
    warnings.extend(mod_warnings)

    # Ensure Apache listens on the proxy port
    port_warnings = await _ensure_listen_port(APACHE_PROXY_PORT)
    warnings.extend(port_warnings)

    # Create document root
    doc_root_path = Path(doc_root)
    try:
        doc_root_path.mkdir(parents=True, exist_ok=True)
        await _run(f"chown -R {username}:{username} /home/{username}/web")
    except Exception as exc:
        warnings.append(f"Could not create document root: {exc}")

    # Write Apache vhost config on proxy port
    vhost_path = APACHE_SITES_AVAILABLE / f"{domain}.conf"
    try:
        vhost_path.write_text(
            _build_http_vhost_proxy(domain, doc_root, php_version, APACHE_PROXY_PORT),
            encoding="utf-8",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to write Apache proxy config: {exc}") from exc

    # Enable the site
    rc, _, err = await _run(f"a2ensite {domain}.conf")
    if rc != 0:
        warnings.append(f"a2ensite failed: {err}")

    # Test & reload Apache
    ok, msg = await _apache_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def _ensure_listen_port(port: int) -> list[str]:
    """Make sure Apache has a ``Listen {port}`` directive in ports.conf."""
    warnings: list[str] = []
    ports_conf = Path("/etc/apache2/ports.conf")
    try:
        if ports_conf.exists():
            content = ports_conf.read_text(encoding="utf-8")
            if f"Listen {port}" not in content:
                content += f"\nListen {port}\n"
                ports_conf.write_text(content, encoding="utf-8")
        else:
            ports_conf.write_text(f"Listen {port}\n", encoding="utf-8")
    except Exception as exc:
        warnings.append(f"Could not update ports.conf for port {port}: {exc}")
    return warnings


async def get_status() -> dict:
    """Return Apache2 service status information."""
    rc, out, _ = await _run("systemctl is-active apache2")
    active = out.strip() == "active"

    rc2, version_out, _ = await _run("apache2 -v 2>/dev/null || apachectl -v 2>/dev/null")
    version = version_out.split("\n")[0] if version_out else "unknown"

    rc3, modules_out, _ = await _run("apachectl -M 2>/dev/null")
    modules = [
        line.strip().split()[0]
        for line in modules_out.split("\n")
        if line.strip() and not line.startswith("Loaded")
    ] if modules_out else []

    return {
        "active": active,
        "version": version,
        "loaded_modules": modules,
    }
