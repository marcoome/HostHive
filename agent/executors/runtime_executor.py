"""
Runtime executor -- deploy and manage Node.js / Python applications.

Manages PM2 (Node.js) and gunicorn/uvicorn (Python) processes alongside
Nginx reverse-proxy configuration.

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

from agent.executors._helpers import atomic_write, safe_domain, safe_path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
APPS_META_DIR = Path("/opt/hosthive/data/apps")
APPS_LOG_DIR = Path("/var/log/hosthive/apps")
SYSTEMD_DIR = Path("/etc/systemd/system")
PM2_BIN = "/usr/local/bin/pm2"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_dirs() -> None:
    APPS_META_DIR.mkdir(parents=True, exist_ok=True)
    APPS_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _app_meta_path(domain: str) -> Path:
    return APPS_META_DIR / f"{domain}.json"


def _read_meta(domain: str) -> dict[str, Any]:
    path = _app_meta_path(domain)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _write_meta(domain: str, meta: dict[str, Any]) -> None:
    _ensure_dirs()
    atomic_write(_app_meta_path(domain), json.dumps(meta, indent=2))


def _generate_reverse_proxy(domain: str, port: int, ssl: bool = False) -> str:
    """Generate an Nginx reverse proxy config for an app."""
    upstream = f"app_{domain.replace('.', '_')}"

    config = f"""# HostHive managed reverse proxy for {domain}
# Generated: {datetime.now(timezone.utc).isoformat()}Z

upstream {upstream} {{
    server 127.0.0.1:{port};
    keepalive 32;
}}

server {{
    listen 80;
    server_name {domain};

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }}

    # Static files (if present)
    location /static/ {{
        alias /home/{domain}/public/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    access_log /var/log/nginx/{domain}.access.log;
    error_log /var/log/nginx/{domain}.error.log;
}}
"""
    return config


def _create_systemd_unit(domain: str, command: list[str], env_file: str, user: str = "www-data") -> str:
    """Create a systemd service unit for a managed app."""
    service_name = f"hosthive-app-{domain.replace('.', '-')}"
    exec_start = " ".join(command)

    unit_content = f"""[Unit]
Description=HostHive managed app: {domain}
After=network.target

[Service]
Type=simple
User={user}
Group={user}
WorkingDirectory=/home/{domain}
EnvironmentFile={env_file}
ExecStart={exec_start}
Restart=always
RestartSec=5
StandardOutput=append:{APPS_LOG_DIR}/{domain}.stdout.log
StandardError=append:{APPS_LOG_DIR}/{domain}.stderr.log

# Resource limits
LimitNOFILE=65536
MemoryMax=512M

[Install]
WantedBy=multi-user.target
"""

    unit_path = SYSTEMD_DIR / f"{service_name}.service"
    atomic_write(unit_path, unit_content)

    # Reload systemd
    subprocess.run(
        ["systemctl", "daemon-reload"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    return service_name


def _service_name(domain: str) -> str:
    return f"hosthive-app-{domain.replace('.', '-')}"


def _manage_service(service_name: str, action: str) -> dict[str, Any]:
    """Start / stop / restart a systemd service."""
    if action not in ("start", "stop", "restart", "enable", "disable"):
        raise ValueError(f"Invalid action: {action}")

    r = subprocess.run(
        ["systemctl", action, f"{service_name}.service"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "service": service_name,
        "action": action,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


def _reload_nginx() -> dict[str, Any]:
    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=15)
    if test.returncode != 0:
        raise ValueError(f"Nginx config test failed: {test.stderr}")
    result = subprocess.run(
        ["systemctl", "reload", "nginx"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"returncode": result.returncode, "stderr": result.stderr}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def deploy_nodejs_app(
    domain: str,
    path: str,
    port: int,
    node_version: str = "20",
) -> dict[str, Any]:
    """Deploy a Node.js application with PM2 process management + Nginx reverse proxy.

    Args:
        domain: Domain name for the app.
        path: Path to the application directory.
        port: Port the app will listen on.
        node_version: Node.js version.
    """
    domain = safe_domain(domain)
    path = safe_path(path, "/home")
    _ensure_dirs()

    app_dir = Path(path)
    if not app_dir.exists():
        raise FileNotFoundError(f"Application directory not found: {path}")

    # Ensure .env file exists
    env_file = app_dir / ".env"
    if not env_file.exists():
        atomic_write(env_file, f"PORT={port}\nNODE_ENV=production\n", mode=0o600)

    # Create systemd unit (more reliable than PM2 for server management)
    node_bin = f"/usr/bin/node"
    entry_point = "index.js"

    # Detect entry point from package.json
    pkg_json = app_dir / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            entry_point = pkg.get("main", "index.js")
            if "scripts" in pkg and "start" in pkg["scripts"]:
                start_script = pkg["scripts"]["start"]
                # Simple extraction: "node server.js" -> "server.js"
                parts = start_script.split()
                if len(parts) >= 2 and parts[0] == "node":
                    entry_point = parts[1]
        except (json.JSONDecodeError, OSError):
            pass

    command = [node_bin, str(app_dir / entry_point)]
    service_name = _create_systemd_unit(domain, command, str(env_file))

    # Write Nginx reverse proxy config
    proxy_conf = _generate_reverse_proxy(domain, port)
    conf_path = NGINX_SITES_AVAILABLE / domain
    atomic_write(conf_path, proxy_conf)

    link_path = NGINX_SITES_ENABLED / domain
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(conf_path)

    # Start the service
    _manage_service(service_name, "enable")
    _manage_service(service_name, "start")

    # Reload Nginx
    _reload_nginx()

    # Save metadata
    meta = {
        "domain": domain,
        "runtime": "nodejs",
        "node_version": node_version,
        "path": path,
        "port": port,
        "entry_point": entry_point,
        "service_name": service_name,
        "deployed_at": datetime.now(timezone.utc).isoformat() + "Z",
    }
    _write_meta(domain, meta)

    return meta


def deploy_python_app(
    domain: str,
    path: str,
    port: int,
    python_version: str = "3.11",
) -> dict[str, Any]:
    """Deploy a Python application with gunicorn/uvicorn + Nginx reverse proxy.

    Args:
        domain: Domain name for the app.
        path: Path to the application directory.
        port: Port the app will listen on.
        python_version: Python version.
    """
    domain = safe_domain(domain)
    path = safe_path(path, "/home")
    _ensure_dirs()

    app_dir = Path(path)
    if not app_dir.exists():
        raise FileNotFoundError(f"Application directory not found: {path}")

    # Ensure .env file exists
    env_file = app_dir / ".env"
    if not env_file.exists():
        atomic_write(env_file, f"PORT={port}\n", mode=0o600)

    # Install venv + dependencies if requirements.txt exists
    venv_dir = app_dir / "venv"
    python_bin = f"python{python_version}"

    if not venv_dir.exists():
        subprocess.run(
            [python_bin, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )

    req_file = app_dir / "requirements.txt"
    if req_file.exists():
        subprocess.run(
            [str(venv_dir / "bin" / "pip"), "install", "--quiet", "-r", str(req_file)],
            capture_output=True,
            text=True,
            timeout=300,
        )

    # Ensure gunicorn is installed
    subprocess.run(
        [str(venv_dir / "bin" / "pip"), "install", "--quiet", "gunicorn", "uvicorn"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Detect app module
    app_module = "app:app"
    wsgi_file = app_dir / "wsgi.py"
    asgi_file = app_dir / "asgi.py"

    if asgi_file.exists():
        app_module = "asgi:app"
        worker_class = "uvicorn.workers.UvicornWorker"
    elif wsgi_file.exists():
        app_module = "wsgi:app"
        worker_class = "sync"
    else:
        # Default: try uvicorn worker for modern Python apps
        worker_class = "uvicorn.workers.UvicornWorker"

    gunicorn_bin = str(venv_dir / "bin" / "gunicorn")
    command = [
        gunicorn_bin,
        "--bind", f"127.0.0.1:{port}",
        "--workers", "2",
        "--worker-class", worker_class,
        "--timeout", "120",
        "--access-logfile", str(APPS_LOG_DIR / f"{domain}.access.log"),
        "--error-logfile", str(APPS_LOG_DIR / f"{domain}.error.log"),
        app_module,
    ]

    service_name = _create_systemd_unit(domain, command, str(env_file))

    # Write Nginx reverse proxy config
    proxy_conf = _generate_reverse_proxy(domain, port)
    conf_path = NGINX_SITES_AVAILABLE / domain
    atomic_write(conf_path, proxy_conf)

    link_path = NGINX_SITES_ENABLED / domain
    if link_path.is_symlink() or link_path.exists():
        link_path.unlink()
    link_path.symlink_to(conf_path)

    # Start the service
    _manage_service(service_name, "enable")
    _manage_service(service_name, "start")

    # Reload Nginx
    _reload_nginx()

    meta = {
        "domain": domain,
        "runtime": "python",
        "python_version": python_version,
        "path": path,
        "port": port,
        "app_module": app_module,
        "service_name": service_name,
        "deployed_at": datetime.now(timezone.utc).isoformat() + "Z",
    }
    _write_meta(domain, meta)

    return meta


def stop_app(domain: str) -> dict[str, Any]:
    """Stop the application for a domain."""
    domain = safe_domain(domain)
    meta = _read_meta(domain)
    if not meta:
        raise FileNotFoundError(f"No app found for {domain}")

    service_name = meta.get("service_name", _service_name(domain))
    result = _manage_service(service_name, "stop")

    meta["status"] = "stopped"
    _write_meta(domain, meta)

    return {"domain": domain, "stopped": True, "service": result}


def restart_app(domain: str) -> dict[str, Any]:
    """Restart the application for a domain."""
    domain = safe_domain(domain)
    meta = _read_meta(domain)
    if not meta:
        raise FileNotFoundError(f"No app found for {domain}")

    service_name = meta.get("service_name", _service_name(domain))
    result = _manage_service(service_name, "restart")

    meta["status"] = "running"
    _write_meta(domain, meta)

    return {"domain": domain, "restarted": True, "service": result}


def get_app_status(domain: str) -> dict[str, Any]:
    """Return app status: running/stopped, PID, uptime, CPU, RAM."""
    domain = safe_domain(domain)
    meta = _read_meta(domain)
    if not meta:
        raise FileNotFoundError(f"No app found for {domain}")

    service_name = meta.get("service_name", _service_name(domain))

    # Check systemd status
    r = subprocess.run(
        ["systemctl", "show", f"{service_name}.service",
         "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp,MemoryCurrent"],
        capture_output=True,
        text=True,
        timeout=15,
    )

    status_info: dict[str, Any] = {"domain": domain, "runtime": meta.get("runtime", "unknown")}

    for line in r.stdout.strip().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "ActiveState":
                status_info["status"] = value
            elif key == "SubState":
                status_info["sub_state"] = value
            elif key == "MainPID":
                status_info["pid"] = int(value) if value.isdigit() else 0
            elif key == "ExecMainStartTimestamp":
                status_info["started_at"] = value
            elif key == "MemoryCurrent":
                if value.isdigit():
                    status_info["memory_bytes"] = int(value)
                    status_info["memory_mb"] = round(int(value) / (1024 * 1024), 1)

    status_info["port"] = meta.get("port")
    status_info["path"] = meta.get("path")

    return status_info


def get_app_logs(domain: str, lines: int = 200) -> dict[str, Any]:
    """Return app stdout/stderr logs."""
    domain = safe_domain(domain)
    _ensure_dirs()

    if lines < 1:
        lines = 1
    if lines > 10000:
        lines = 10000

    logs: dict[str, str] = {}

    for log_type in ("stdout", "stderr"):
        log_path = APPS_LOG_DIR / f"{domain}.{log_type}.log"
        if log_path.exists():
            r = subprocess.run(
                ["tail", "-n", str(lines), str(log_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            logs[log_type] = r.stdout
        else:
            logs[log_type] = ""

    return {"domain": domain, "logs": logs}


def list_apps() -> list[dict[str, Any]]:
    """Return all deployed apps with their status."""
    _ensure_dirs()
    apps = []

    for meta_file in sorted(APPS_META_DIR.glob("*.json")):
        try:
            meta = json.loads(meta_file.read_text())
            domain = meta.get("domain", meta_file.stem)

            # Quick status check
            service_name = meta.get("service_name", _service_name(domain))
            r = subprocess.run(
                ["systemctl", "is-active", f"{service_name}.service"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            meta["status"] = r.stdout.strip()
            apps.append(meta)
        except (json.JSONDecodeError, OSError):
            pass

    return apps


def set_env_vars(domain: str, env_dict: dict[str, str]) -> dict[str, Any]:
    """Update .env file for an app and restart it."""
    domain = safe_domain(domain)
    meta = _read_meta(domain)
    if not meta:
        raise FileNotFoundError(f"No app found for {domain}")

    app_path = meta.get("path")
    if not app_path:
        raise ValueError(f"No path configured for {domain}")

    env_file = Path(app_path) / ".env"

    # Read existing env vars
    existing: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            existing[key.strip()] = value.strip()

    # Merge new vars
    existing.update(env_dict)

    # Write back
    content = "\n".join(f"{k}={v}" for k, v in sorted(existing.items())) + "\n"
    atomic_write(env_file, content, mode=0o600)

    # Restart the app
    service_name = meta.get("service_name", _service_name(domain))
    _manage_service(service_name, "restart")

    return {"domain": domain, "env_vars_updated": list(env_dict.keys()), "restarted": True}
