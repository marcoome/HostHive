"""Direct nginx & SSL management -- no agent required.

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
NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
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


async def _nginx_test_and_reload() -> tuple[bool, str]:
    """Run ``nginx -t`` then ``systemctl reload nginx``.

    Returns (success, message).
    """
    rc, out, err = await _run("nginx -t")
    if rc != 0:
        msg = f"nginx config test failed: {err or out}"
        logger.error(msg)
        return False, msg

    rc, out, err = await _run("systemctl reload nginx")
    if rc != 0:
        msg = f"nginx reload failed: {err or out}"
        logger.error(msg)
        return False, msg

    return True, "nginx reloaded successfully"


# ---------------------------------------------------------------------------
# Nginx vhost config templates
# ---------------------------------------------------------------------------
def _build_http_vhost(
    domain: str,
    document_root: str,
    php_version: str,
) -> str:
    """Return an HTTP-only nginx server block."""
    return f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain} www.{domain};
    root {document_root};
    index index.html index.php;

    location / {{
        try_files $uri $uri/ /index.php?$args;
    }}

    location ~ \\.php$ {{
        fastcgi_pass unix:/run/php/php{php_version}-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    access_log /var/log/nginx/{domain}.access.log;
    error_log /var/log/nginx/{domain}.error.log;
}}
"""


def _build_ssl_vhost(
    domain: str,
    document_root: str,
    php_version: str,
    cert_path: str,
    key_path: str,
) -> str:
    """Return a combined HTTP-redirect + HTTPS nginx server block."""
    return f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain} www.{domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name {domain} www.{domain};
    root {document_root};
    index index.html index.php;

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {{
        try_files $uri $uri/ /index.php?$args;
    }}

    location ~ \\.php$ {{
        fastcgi_pass unix:/run/php/php{php_version}-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    access_log /var/log/nginx/{domain}.access.log;
    error_log /var/log/nginx/{domain}.error.log;
}}
"""


# ---------------------------------------------------------------------------
# Public API -- Domains
# ---------------------------------------------------------------------------
async def create_vhost(
    domain: str,
    username: str,
    document_root: str,
    php_version: str = "8.2",
) -> dict:
    """Create nginx vhost, document root, symlink, and reload nginx.

    Returns ``{"ok": True, "warnings": []}`` on success or raises.
    """
    warnings: list[str] = []

    # 1. Create document root
    doc_root = Path(document_root)
    try:
        doc_root.mkdir(parents=True, exist_ok=True)
        # Set ownership so the user can write
        await _run(f"chown -R {username}:{username} /home/{username}/web")
    except Exception as exc:
        warnings.append(f"Could not create document root: {exc}")

    # 2. Create basic index.html
    index_path = doc_root / "index.html"
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

    # 3. Write nginx vhost config
    vhost_path = NGINX_SITES_AVAILABLE / domain
    try:
        vhost_path.write_text(
            _build_http_vhost(domain, document_root, php_version),
            encoding="utf-8",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to write nginx config: {exc}") from exc

    # 4. Create symlink in sites-enabled
    symlink_path = NGINX_SITES_ENABLED / domain
    try:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(vhost_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to create symlink: {exc}") from exc

    # 5. Test & reload nginx
    ok, msg = await _nginx_test_and_reload()
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
    """Rewrite the nginx vhost with a new PHP version and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    vhost_path = NGINX_SITES_AVAILABLE / domain

    if not vhost_path.exists():
        raise RuntimeError(f"Nginx config for {domain} does not exist.")

    if ssl_enabled and cert_path and key_path:
        config = _build_ssl_vhost(domain, document_root, new_php_version, cert_path, key_path)
    else:
        config = _build_http_vhost(domain, document_root, new_php_version)

    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write nginx config: {exc}") from exc

    ok, msg = await _nginx_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def delete_vhost(domain: str) -> dict:
    """Remove nginx config, symlink, and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []

    # Remove symlink
    symlink_path = NGINX_SITES_ENABLED / domain
    try:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
    except Exception as exc:
        warnings.append(f"Could not remove symlink: {exc}")

    # Remove config
    vhost_path = NGINX_SITES_AVAILABLE / domain
    try:
        if vhost_path.exists():
            vhost_path.unlink()
    except Exception as exc:
        warnings.append(f"Could not remove config: {exc}")

    # Reload nginx
    ok, msg = await _nginx_test_and_reload()
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
async def issue_letsencrypt(domain: str, email: str) -> dict:
    """Run certbot to obtain a Let's Encrypt certificate.

    Returns ``{"cert_path": ..., "key_path": ...}`` on success.
    """
    cmd = (
        f"certbot certonly --nginx -d {domain} "
        f"--non-interactive --agree-tos -m {email}"
    )
    rc, out, err = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"certbot failed: {err or out}")

    cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"

    return {"cert_path": cert_path, "key_path": key_path}


async def apply_ssl_to_nginx(
    domain: str,
    document_root: str,
    php_version: str,
    cert_path: str,
    key_path: str,
) -> dict:
    """Rewrite the nginx vhost with SSL and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    vhost_path = NGINX_SITES_AVAILABLE / domain

    config = _build_ssl_vhost(domain, document_root, php_version, cert_path, key_path)
    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write SSL nginx config: {exc}") from exc

    ok, msg = await _nginx_test_and_reload()
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

    # If chain is provided, concatenate it with the certificate
    cert_content = certificate
    if chain:
        cert_content = certificate.rstrip("\n") + "\n" + chain

    cert_path.write_text(cert_content, encoding="utf-8")
    key_path.write_text(private_key, encoding="utf-8")

    # Secure permissions
    os.chmod(cert_path, 0o644)
    os.chmod(key_path, 0o600)

    return {"cert_path": str(cert_path), "key_path": str(key_path)}
