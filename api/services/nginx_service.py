"""Direct nginx & SSL management -- no agent required.

All file-system and process operations happen locally via asyncio.subprocess.
Vhost configs are rendered from Jinja2 templates in data/templates/nginx/.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
SSL_BASE_DIR = Path("/etc/ssl/hosthive")
HTPASSWD_DIR = Path("/etc/nginx/htpasswd")
NGINX_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "templates" / "nginx"

# ---------------------------------------------------------------------------
# Jinja2 environment -- single source of truth shared with nginx_executor
# ---------------------------------------------------------------------------
_jinja = Environment(
    loader=FileSystemLoader(str(NGINX_TEMPLATE_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)

AVAILABLE_TEMPLATES = ("default", "wordpress", "proxy", "static")


def list_templates() -> list[dict[str, str]]:
    """Return the list of available nginx templates with descriptions."""
    descriptions = {
        "default": "Standard PHP-FPM site with security headers and static caching",
        "wordpress": "WordPress-optimized with permalinks, upload limits, and xmlrpc protection",
        "proxy": "Reverse proxy to a backend service (Node.js, Python, etc.)",
        "static": "Static files only -- no PHP, aggressive caching and gzip",
    }
    return [
        {"name": name, "description": descriptions.get(name, "")}
        for name in AVAILABLE_TEMPLATES
    ]


def render_vhost(
    *,
    template_name: str = "default",
    domain: str,
    document_root: str = "",
    php_version: str = "8.2",
    ssl: bool = False,
    ssl_certificate: Optional[str] = None,
    ssl_certificate_key: Optional[str] = None,
    backend_port: int = 8080,
    custom_nginx_config: Optional[str] = None,
    cache_enabled: bool = False,
    cache_type: str = "fastcgi",
    cache_ttl: int = 3600,
    cache_bypass_cookie: str = "wordpress_logged_in",
    geo_enabled: bool = False,
    hotlink_protection: bool = False,
    hotlink_allowed_domains: Optional[str] = None,
    hotlink_extensions: str = "jpg,jpeg,png,gif,webp,svg,mp4,mp3",
    hotlink_redirect_url: Optional[str] = None,
    custom_error_pages: Optional[dict] = None,
) -> str:
    """Render an nginx vhost config from a Jinja2 template.

    This is the single rendering function used by both the API service
    and the agent executor.
    """
    if template_name not in AVAILABLE_TEMPLATES:
        raise ValueError(
            f"Unknown template {template_name!r}. "
            f"Available: {', '.join(AVAILABLE_TEMPLATES)}"
        )

    # Build the pipe-separated extension regex and space-separated allowed
    # referers list for the nginx valid_referers directive.
    hotlink_ext_regex = hotlink_extensions.replace(",", "|") if hotlink_extensions else ""
    hotlink_allowed = ""
    if hotlink_allowed_domains:
        # Convert comma-separated or newline-separated list to space-separated
        raw = hotlink_allowed_domains.replace("\n", ",").replace("\r", "")
        hotlink_allowed = " ".join(
            d.strip() for d in raw.split(",") if d.strip()
        )

    template = _jinja.get_template(f"{template_name}.j2")
    return template.render(
        domain=domain,
        document_root=document_root,
        php_version=php_version,
        ssl=ssl,
        ssl_certificate=ssl_certificate,
        ssl_certificate_key=ssl_certificate_key,
        backend_port=backend_port,
        custom_nginx_config=custom_nginx_config,
        cache_enabled=cache_enabled,
        cache_type=cache_type,
        cache_ttl=cache_ttl,
        cache_bypass_cookie=cache_bypass_cookie,
        geo_enabled=geo_enabled,
        hotlink_protection=hotlink_protection,
        hotlink_extensions=hotlink_ext_regex,
        hotlink_allowed_domains=hotlink_allowed,
        hotlink_redirect_url=hotlink_redirect_url,
        custom_error_pages=custom_error_pages,
    )


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


async def _validate_custom_config(domain: str, full_config: str) -> tuple[bool, str]:
    """Write config to sites-available, run ``nginx -t``, then restore.

    Returns (valid, message).
    """
    vhost_path = NGINX_SITES_AVAILABLE / domain
    backup = None
    if vhost_path.exists():
        backup = vhost_path.read_text(encoding="utf-8")

    try:
        vhost_path.write_text(full_config, encoding="utf-8")
        rc, out, err = await _run("nginx -t")

        if rc != 0:
            return False, f"nginx config validation failed: {err or out}"
        return True, "ok"
    finally:
        # Restore original config
        if backup is not None:
            vhost_path.write_text(backup, encoding="utf-8")
        elif vhost_path.exists():
            vhost_path.unlink()


# ---------------------------------------------------------------------------
# Public API -- Domains
# ---------------------------------------------------------------------------
async def create_vhost(
    domain: str,
    username: str,
    document_root: str,
    php_version: str = "8.2",
    template_name: str = "default",
    custom_nginx_config: Optional[str] = None,
    backend_port: int = 8080,
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

    # 3. Render nginx vhost config from Jinja2 template
    config = render_vhost(
        template_name=template_name,
        domain=domain,
        document_root=document_root,
        php_version=php_version,
        ssl=False,
        backend_port=backend_port,
        custom_nginx_config=custom_nginx_config,
    )

    # 4. If custom config is present, validate before applying
    if custom_nginx_config:
        valid, msg = await _validate_custom_config(domain, config)
        if not valid:
            raise RuntimeError(f"Custom nginx config is invalid: {msg}")

    # 5. Write nginx vhost config
    vhost_path = NGINX_SITES_AVAILABLE / domain
    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write nginx config: {exc}") from exc

    # 6. Create symlink in sites-enabled
    symlink_path = NGINX_SITES_ENABLED / domain
    try:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(vhost_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to create symlink: {exc}") from exc

    # 7. Test & reload nginx
    ok, msg = await _nginx_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def update_vhost(
    domain: str,
    document_root: str,
    php_version: str = "8.2",
    ssl_enabled: bool = False,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    template_name: str = "default",
    custom_nginx_config: Optional[str] = None,
    backend_port: int = 8080,
    cache_enabled: bool = False,
    cache_type: str = "fastcgi",
    cache_ttl: int = 3600,
    cache_bypass_cookie: str = "wordpress_logged_in",
    hotlink_protection: bool = False,
    hotlink_allowed_domains: Optional[str] = None,
    hotlink_extensions: str = "jpg,jpeg,png,gif,webp,svg,mp4,mp3",
    hotlink_redirect_url: Optional[str] = None,
    custom_error_pages: Optional[dict] = None,
) -> dict:
    """Rewrite the nginx vhost from the template and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    vhost_path = NGINX_SITES_AVAILABLE / domain

    if not vhost_path.exists():
        raise RuntimeError(f"Nginx config for {domain} does not exist.")

    config = render_vhost(
        template_name=template_name,
        domain=domain,
        document_root=document_root,
        php_version=php_version,
        ssl=ssl_enabled and bool(cert_path and key_path),
        ssl_certificate=cert_path,
        ssl_certificate_key=key_path,
        backend_port=backend_port,
        custom_nginx_config=custom_nginx_config,
        cache_enabled=cache_enabled,
        cache_type=cache_type,
        cache_ttl=cache_ttl,
        cache_bypass_cookie=cache_bypass_cookie,
        hotlink_protection=hotlink_protection,
        hotlink_allowed_domains=hotlink_allowed_domains,
        hotlink_extensions=hotlink_extensions,
        hotlink_redirect_url=hotlink_redirect_url,
        custom_error_pages=custom_error_pages,
    )

    # Validate custom config before applying
    if custom_nginx_config:
        valid, msg = await _validate_custom_config(domain, config)
        if not valid:
            raise RuntimeError(f"Custom nginx config is invalid: {msg}")

    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write nginx config: {exc}") from exc

    ok, msg = await _nginx_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


# Backward-compatible alias
async def update_vhost_php(
    domain: str,
    document_root: str,
    new_php_version: str,
    ssl_enabled: bool = False,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    template_name: str = "default",
    custom_nginx_config: Optional[str] = None,
    backend_port: int = 8080,
) -> dict:
    """Backward-compatible wrapper around ``update_vhost``."""
    return await update_vhost(
        domain=domain,
        document_root=document_root,
        php_version=new_php_version,
        ssl_enabled=ssl_enabled,
        cert_path=cert_path,
        key_path=key_path,
        template_name=template_name,
        custom_nginx_config=custom_nginx_config,
        backend_port=backend_port,
    )


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
    template_name: str = "default",
    custom_nginx_config: Optional[str] = None,
    backend_port: int = 8080,
) -> dict:
    """Rewrite the nginx vhost with SSL and reload.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    vhost_path = NGINX_SITES_AVAILABLE / domain

    config = render_vhost(
        template_name=template_name,
        domain=domain,
        document_root=document_root,
        php_version=php_version,
        ssl=True,
        ssl_certificate=cert_path,
        ssl_certificate_key=key_path,
        backend_port=backend_port,
        custom_nginx_config=custom_nginx_config,
    )

    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to write SSL nginx config: {exc}") from exc

    ok, msg = await _nginx_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


def _install_custom_ssl_blocking(
    domain: str,
    certificate: str,
    private_key: str,
    chain: Optional[str],
) -> dict:
    """Synchronous, blocking implementation of install_custom_ssl.

    Designed to run inside ``loop.run_in_executor()`` so the event loop
    is never blocked by file-system I/O.
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


async def install_custom_ssl(
    domain: str,
    certificate: str,
    private_key: str,
    chain: Optional[str] = None,
) -> dict:
    """Save uploaded cert/key to disk.

    Blocking file-system operations are executed in the default thread-pool
    executor via ``asyncio.get_running_loop().run_in_executor()`` so the
    FastAPI event loop stays responsive.

    Returns ``{"cert_path": ..., "key_path": ...}``.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _install_custom_ssl_blocking,
        domain,
        certificate,
        private_key,
        chain,
    )


async def parse_cert_expiry(cert_path: str) -> Optional["datetime"]:
    """Return the ``notAfter`` date of an X.509 certificate.

    Uses ``openssl x509 -enddate -noout`` directly (no agent). Returns
    ``None`` if the file does not exist or openssl cannot parse it.
    """
    from datetime import datetime, timezone

    if not Path(cert_path).is_file():
        return None

    rc, out, err = await _run(f"openssl x509 -enddate -noout -in {cert_path}")
    if rc != 0 or "notAfter=" not in out:
        logger.warning("openssl x509 failed for %s: %s", cert_path, err or out)
        return None

    # Output format: "notAfter=Mar 15 12:00:00 2027 GMT"
    raw = out.split("notAfter=", 1)[1].strip()
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc,
        )
    except ValueError as exc:
        logger.warning("Could not parse openssl date %r: %s", raw, exc)
        return None


# ---------------------------------------------------------------------------
# Public API -- Cache
# ---------------------------------------------------------------------------
async def purge_cache(domain: str) -> dict:
    """Purge the nginx cache directory for the given domain.

    Returns ``{"ok": True, "warnings": []}`` on success.
    """
    warnings: list[str] = []
    cache_dir = Path(f"/var/cache/nginx/{domain}")

    if cache_dir.exists():
        rc, out, err = await _run(f"rm -rf {cache_dir}")
        if rc != 0:
            warnings.append(f"Failed to remove cache directory: {err or out}")
        else:
            # Recreate empty dir so nginx doesn't complain
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                await _run(f"chown www-data:www-data {cache_dir}")
            except Exception as exc:
                warnings.append(f"Cache purged but could not recreate directory: {exc}")
    else:
        warnings.append("Cache directory does not exist (nothing to purge).")

    # Reload nginx to clear any in-memory cache references
    ok, msg = await _nginx_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


# ---------------------------------------------------------------------------
# Public API -- Directory Privacy (.htpasswd)
# ---------------------------------------------------------------------------

def _htpasswd_filename(domain: str, path: str) -> str:
    """Generate a safe htpasswd filename from domain + path.

    e.g. domain.com + /admin -> domain.com_admin
    """
    safe_path = path.strip("/").replace("/", "_") or "root"
    return f"{domain}_{safe_path}"


def generate_htpasswd_hash(password: str) -> str:
    """Generate a password hash compatible with nginx/htpasswd.

    Uses the standard htpasswd-compatible {SHA} format.
    """
    import base64
    sha1_digest = hashlib.sha1(password.encode("utf-8")).digest()
    return "{SHA}" + base64.b64encode(sha1_digest).decode("ascii")


async def write_htpasswd_file(domain: str, path: str, users: list[dict]) -> Path:
    """Write a .htpasswd file for the given domain/path.

    *users* is a list of ``{"username": ..., "password_hash": ...}``.
    Returns the path to the htpasswd file.
    """
    HTPASSWD_DIR.mkdir(parents=True, exist_ok=True)

    filename = _htpasswd_filename(domain, path)
    htpasswd_path = HTPASSWD_DIR / filename

    lines = [f"{u['username']}:{u['password_hash']}" for u in users]
    htpasswd_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Secure permissions
    os.chmod(htpasswd_path, 0o644)

    return htpasswd_path


async def remove_htpasswd_file(domain: str, path: str) -> None:
    """Remove the .htpasswd file for the given domain/path."""
    filename = _htpasswd_filename(domain, path)
    htpasswd_path = HTPASSWD_DIR / filename
    if htpasswd_path.exists():
        htpasswd_path.unlink()


def _build_auth_basic_directives(domain: str, rules: list[dict]) -> str:
    """Build nginx auth_basic location blocks for directory privacy rules.

    Each rule is ``{"path": "/admin", "auth_name": "Restricted Area", "users": [...]}``.
    Returns a string of nginx location blocks to inject into the vhost.
    """
    blocks = []
    for rule in rules:
        path = rule["path"]
        auth_name = rule["auth_name"]
        filename = _htpasswd_filename(domain, path)
        htpasswd_path = HTPASSWD_DIR / filename

        location_path = path if path != "/" else "= /"

        block = (
            f"location {location_path} {{\n"
            f"    auth_basic \"{auth_name}\";\n"
            f"    auth_basic_user_file {htpasswd_path};\n"
            f"    try_files $uri $uri/ /index.php?$query_string;\n"
            f"}}"
        )
        blocks.append(block)

    return "\n\n".join(blocks)


async def sync_directory_privacy(
    domain: str,
    rules: list[dict],
    document_root: str,
    php_version: str = "8.2",
    ssl_enabled: bool = False,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    template_name: str = "default",
    custom_nginx_config: Optional[str] = None,
    webserver: str = "nginx",
    cache_enabled: bool = False,
    cache_type: str = "fastcgi",
    cache_ttl: int = 3600,
    cache_bypass_cookie: str = "wordpress_logged_in",
) -> dict:
    """Sync all .htpasswd files and regenerate the nginx vhost with auth directives.

    *rules* is a list of active rules, each with path, auth_name, and users.
    Returns ``{"ok": True, "warnings": []}``.
    """
    import re

    warnings: list[str] = []

    # 1. Write htpasswd files for each active rule
    for rule in rules:
        try:
            await write_htpasswd_file(domain, rule["path"], rule["users"])
        except Exception as exc:
            warnings.append(f"Failed to write htpasswd for {rule['path']}: {exc}")

    # 2. Build auth_basic directives
    auth_directives = _build_auth_basic_directives(domain, rules)

    # 3. Combine with existing custom_nginx_config
    # Strip any previously auto-generated directory privacy blocks
    base_custom = custom_nginx_config or ""
    base_custom = re.sub(
        r"\n?# --- Directory Privacy \(auto-generated\) ---.*?# --- End Directory Privacy ---\n?",
        "",
        base_custom,
        flags=re.DOTALL,
    ).strip()

    combined_custom = base_custom
    if auth_directives:
        if combined_custom:
            combined_custom += "\n\n"
        combined_custom += (
            "# --- Directory Privacy (auto-generated) ---\n"
            + auth_directives
            + "\n# --- End Directory Privacy ---"
        )
    combined_custom = combined_custom.strip() or None

    # 4. Regenerate vhost
    if webserver in ("nginx", "nginx_apache"):
        vhost_path = NGINX_SITES_AVAILABLE / domain
        if not vhost_path.exists():
            warnings.append("Nginx config does not exist yet; skipping vhost regeneration.")
            return {"ok": True, "warnings": warnings}

        tpl = template_name if webserver == "nginx" else "proxy"
        config = render_vhost(
            template_name=tpl,
            domain=domain,
            document_root=document_root,
            php_version=php_version,
            ssl=ssl_enabled and bool(cert_path and key_path),
            ssl_certificate=cert_path,
            ssl_certificate_key=key_path,
            backend_port=8080,
            custom_nginx_config=combined_custom,
            cache_enabled=cache_enabled,
            cache_type=cache_type,
            cache_ttl=cache_ttl,
            cache_bypass_cookie=cache_bypass_cookie,
        )

        try:
            vhost_path.write_text(config, encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(f"Failed to write nginx config: {exc}") from exc

        ok, msg = await _nginx_test_and_reload()
        if not ok:
            warnings.append(msg)

    return {"ok": True, "warnings": warnings}
