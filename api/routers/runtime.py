"""Runtime apps router -- /api/v1/runtime.

Manage Node.js and Python applications directly on the system (no Docker).
Similar to cPanel's "Setup Node.js App" / "Setup Python App".

Node.js apps: managed via PM2
Python apps: managed via systemd service + gunicorn/uvicorn
Nginx reverse proxy configured for each app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.runtime_app import RuntimeApp
from api.models.users import User
from api.schemas.runtime_app import (
    RuntimeAppCreate,
    RuntimeAppResponse,
    RuntimeAppUpdate,
    RuntimeVersionsResponse,
)
from api.services import nginx_service

router = APIRouter()
logger = logging.getLogger(__name__)

SYSTEMD_DIR = Path("/etc/systemd/system")
LOG_DIR = Path("/var/log/hosthive/runtime")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _get_app_or_404(
    app_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> RuntimeApp:
    result = await db.execute(select(RuntimeApp).where(RuntimeApp.id == app_id))
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime app not found.")
    if not _is_admin(current_user) and app.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return app


def _service_name(app_id: uuid.UUID) -> str:
    """Systemd service name for a runtime app."""
    return f"hosthive-app-{app_id}"


def _service_file_path(app_id: uuid.UUID) -> Path:
    return SYSTEMD_DIR / f"{_service_name(app_id)}.service"


# ---------------------------------------------------------------------------
# Node.js helpers (PM2)
# ---------------------------------------------------------------------------

async def _setup_node_app(app: RuntimeApp, username: str) -> dict:
    """Set up a Node.js application directory with nvm and PM2."""
    warnings: list[str] = []
    app_root = Path(app.app_root)

    # Ensure app root exists
    try:
        app_root.mkdir(parents=True, exist_ok=True)
        await _run(f"chown -R {username}:{username} {app_root}")
    except Exception as exc:
        warnings.append(f"Could not create app root: {exc}")

    # Create a PM2 ecosystem file
    env_block = app.env_vars or {}
    env_block["PORT"] = str(app.port)
    env_block["NODE_ENV"] = env_block.get("NODE_ENV", "production")

    startup_cmd = app.startup_command or None
    ecosystem = {
        "apps": [{
            "name": _service_name(app.id),
            "script": app.entry_point if not startup_cmd else startup_cmd,
            "cwd": str(app_root),
            "instances": 1,
            "autorestart": True,
            "watch": False,
            "env": env_block,
            "log_file": str(LOG_DIR / f"{app.id}.log"),
            "out_file": str(LOG_DIR / f"{app.id}.stdout.log"),
            "error_file": str(LOG_DIR / f"{app.id}.stderr.log"),
        }]
    }

    eco_path = app_root / "ecosystem.config.json"
    try:
        eco_path.write_text(json.dumps(ecosystem, indent=2), encoding="utf-8")
        await _run(f"chown {username}:{username} {eco_path}")
    except Exception as exc:
        warnings.append(f"Could not write ecosystem file: {exc}")

    # Also create a systemd service as a fallback / wrapper for PM2
    node_bin = f"/usr/bin/node"
    # Try to use nvm-installed node if available
    nvm_node = f"/home/{username}/.nvm/versions/node/v{app.runtime_version}/bin/node"
    pm2_bin = "/usr/bin/pm2"
    nvm_pm2 = f"/home/{username}/.nvm/versions/node/v{app.runtime_version}/bin/pm2"

    service_content = f"""[Unit]
Description=HostHive Node.js App {app.id}
After=network.target

[Service]
Type=forking
User={username}
Group={username}
WorkingDirectory={app.app_root}
Environment=HOME=/home/{username}
Environment=PORT={app.port}
"""
    for k, v in (app.env_vars or {}).items():
        service_content += f"Environment={k}={v}\n"

    service_content += f"""ExecStart=/bin/bash -lc 'pm2 start {eco_path} --name {_service_name(app.id)}'
ExecStop=/bin/bash -lc 'pm2 stop {_service_name(app.id)}'
ExecReload=/bin/bash -lc 'pm2 restart {_service_name(app.id)}'
PIDFile=/home/{username}/.pm2/pids/{_service_name(app.id)}-0.pid
Restart=on-failure
RestartSec=5
StandardOutput=append:{LOG_DIR}/{app.id}.stdout.log
StandardError=append:{LOG_DIR}/{app.id}.stderr.log

[Install]
WantedBy=multi-user.target
"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _service_file_path(app.id).write_text(service_content, encoding="utf-8")
        await _run("systemctl daemon-reload")
    except Exception as exc:
        warnings.append(f"Could not create systemd service: {exc}")

    return {"ok": True, "warnings": warnings}


# ---------------------------------------------------------------------------
# Python helpers (virtualenv + gunicorn/uvicorn)
# ---------------------------------------------------------------------------

async def _setup_python_app(app: RuntimeApp, username: str) -> dict:
    """Set up a Python application with virtualenv."""
    warnings: list[str] = []
    app_root = Path(app.app_root)

    # Ensure app root exists
    try:
        app_root.mkdir(parents=True, exist_ok=True)
        await _run(f"chown -R {username}:{username} {app_root}")
    except Exception as exc:
        warnings.append(f"Could not create app root: {exc}")

    # Create virtualenv
    python_bin = f"python{app.runtime_version}"
    venv_path = app_root / "venv"
    if not venv_path.exists():
        rc, out, err = await _run(f"sudo -u {username} {python_bin} -m venv {venv_path}")
        if rc != 0:
            # Try without minor version
            major = app.runtime_version.split(".")[0]
            rc, out, err = await _run(f"sudo -u {username} python{major} -m venv {venv_path}")
            if rc != 0:
                warnings.append(f"Failed to create virtualenv: {err or out}")

    # Install gunicorn/uvicorn in venv
    pip_bin = venv_path / "bin" / "pip"
    if pip_bin.exists():
        rc, out, err = await _run(f"sudo -u {username} {pip_bin} install --quiet gunicorn uvicorn")
        if rc != 0:
            warnings.append(f"Failed to install gunicorn/uvicorn: {err or out}")

    # Determine startup command
    entry = app.entry_point or "app.py"
    if app.startup_command:
        exec_start = f"{venv_path}/bin/{app.startup_command}"
    elif entry.endswith(".py"):
        # Default: gunicorn with uvicorn workers
        module = entry.replace(".py", "").replace("/", ".")
        exec_start = (
            f"{venv_path}/bin/gunicorn {module}:app "
            f"--bind 127.0.0.1:{app.port} "
            f"--workers 2 "
            f"--worker-class uvicorn.workers.UvicornWorker"
        )
    else:
        exec_start = f"{venv_path}/bin/python {entry}"

    # Build env vars string
    env_lines = f"Environment=PORT={app.port}\n"
    env_lines += f"Environment=VIRTUAL_ENV={venv_path}\n"
    env_lines += f"Environment=PATH={venv_path}/bin:/usr/local/bin:/usr/bin:/bin\n"
    for k, v in (app.env_vars or {}).items():
        env_lines += f"Environment={k}={v}\n"

    service_content = f"""[Unit]
Description=HostHive Python App {app.id}
After=network.target

[Service]
Type=simple
User={username}
Group={username}
WorkingDirectory={app.app_root}
{env_lines}ExecStart={exec_start}
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=append:{LOG_DIR}/{app.id}.stdout.log
StandardError=append:{LOG_DIR}/{app.id}.stderr.log

[Install]
WantedBy=multi-user.target
"""

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _service_file_path(app.id).write_text(service_content, encoding="utf-8")
        await _run("systemctl daemon-reload")
    except Exception as exc:
        warnings.append(f"Could not create systemd service: {exc}")

    return {"ok": True, "warnings": warnings}


# ---------------------------------------------------------------------------
# Nginx reverse proxy helper
# ---------------------------------------------------------------------------

async def _configure_reverse_proxy(domain_name: str, port: int) -> dict:
    """Write an nginx reverse proxy config for the runtime app."""
    warnings: list[str] = []

    # Use the existing proxy template to generate config with WebSocket support
    from api.services.nginx_service import (
        NGINX_SITES_AVAILABLE,
        NGINX_SITES_ENABLED,
        render_vhost,
        _nginx_test_and_reload,
    )

    config = render_vhost(
        template_name="proxy",
        domain=domain_name,
        backend_port=port,
    )

    vhost_path = NGINX_SITES_AVAILABLE / domain_name
    symlink_path = NGINX_SITES_ENABLED / domain_name

    try:
        vhost_path.write_text(config, encoding="utf-8")
    except Exception as exc:
        warnings.append(f"Failed to write nginx proxy config: {exc}")

    try:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(vhost_path)
    except Exception as exc:
        warnings.append(f"Failed to create symlink: {exc}")

    ok, msg = await _nginx_test_and_reload()
    if not ok:
        warnings.append(msg)

    return {"ok": True, "warnings": warnings}


async def _remove_service(app: RuntimeApp) -> list[str]:
    """Stop and remove the systemd service and PM2 process for an app."""
    warnings: list[str] = []
    svc = _service_name(app.id)

    # Stop via systemd
    await _run(f"systemctl stop {svc}")
    await _run(f"systemctl disable {svc}")

    # Also try PM2 cleanup for Node apps
    if app.app_type == "node":
        await _run(f"pm2 delete {svc} 2>/dev/null || true")

    # Remove service file
    svc_path = _service_file_path(app.id)
    try:
        if svc_path.exists():
            svc_path.unlink()
        await _run("systemctl daemon-reload")
    except Exception as exc:
        warnings.append(f"Could not remove service file: {exc}")

    # Clean up log files
    for suffix in (".log", ".stdout.log", ".stderr.log"):
        log_file = LOG_DIR / f"{app.id}{suffix}"
        try:
            if log_file.exists():
                log_file.unlink()
        except Exception:
            pass

    return warnings


# ---------------------------------------------------------------------------
# GET /versions -- list available Node.js and Python versions
# ---------------------------------------------------------------------------

@router.get("/versions", response_model=RuntimeVersionsResponse)
async def list_runtime_versions(
    current_user: User = Depends(get_current_user),
):
    """Return available Node.js and Python versions installed on the system."""
    node_versions: list[str] = []
    python_versions: list[str] = []

    # Detect Node.js versions
    # Check system node
    rc, out, _ = await _run("node --version 2>/dev/null")
    if rc == 0 and out:
        ver = out.lstrip("v").split(".")[0]
        if ver not in node_versions:
            node_versions.append(ver)

    # Check nvm-managed versions
    rc, out, _ = await _run("ls /home/*/\.nvm/versions/node/ 2>/dev/null || ls /usr/local/nvm/versions/node/ 2>/dev/null || echo ''")
    if rc == 0 and out:
        for line in out.split("\n"):
            v = line.strip().lstrip("v").split(".")[0]
            if v and v.isdigit() and v not in node_versions:
                node_versions.append(v)

    # Common Node.js versions as fallback
    if not node_versions:
        node_versions = ["18", "20", "22"]

    # Detect Python versions
    for minor in range(8, 14):
        ver = f"3.{minor}"
        rc, _, _ = await _run(f"python{ver} --version 2>/dev/null")
        if rc == 0:
            python_versions.append(ver)

    # Fallback
    if not python_versions:
        rc, out, _ = await _run("python3 --version 2>/dev/null")
        if rc == 0 and out:
            parts = out.split()[-1].split(".")
            if len(parts) >= 2:
                python_versions.append(f"{parts[0]}.{parts[1]}")

    if not python_versions:
        python_versions = ["3.11", "3.12"]

    return RuntimeVersionsResponse(
        node=sorted(node_versions, key=lambda x: int(x) if x.isdigit() else 0),
        python=sorted(python_versions),
    )


# ---------------------------------------------------------------------------
# GET /apps -- list user's runtime apps
# ---------------------------------------------------------------------------

@router.get("/apps", status_code=status.HTTP_200_OK)
async def list_runtime_apps(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(RuntimeApp)
    if not _is_admin(current_user):
        query = query.where(RuntimeApp.user_id == current_user.id)

    results = (
        await db.execute(query.order_by(RuntimeApp.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    # Enrich with domain names
    items = []
    for app in results:
        resp = RuntimeAppResponse.model_validate(app)
        # Fetch domain name
        domain_result = await db.execute(select(Domain.domain_name).where(Domain.id == app.domain_id))
        domain_name = domain_result.scalar_one_or_none()
        resp.domain_name = domain_name or "unknown"
        items.append(resp)

    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# POST /apps -- create runtime app
# ---------------------------------------------------------------------------

@router.post("/apps", response_model=RuntimeAppResponse, status_code=status.HTTP_201_CREATED)
async def create_runtime_app(
    body: RuntimeAppCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify domain exists and belongs to user
    result = await db.execute(select(Domain).where(Domain.id == body.domain_id))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and domain.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Check port is not already in use by another runtime app
    existing = await db.execute(select(RuntimeApp).where(RuntimeApp.port == body.port))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Port {body.port} is already in use.")

    # Set sensible defaults
    entry_point = body.entry_point
    if not entry_point or entry_point == "app.js":
        entry_point = "app.js" if body.app_type == "node" else "app.py"

    app = RuntimeApp(
        domain_id=body.domain_id,
        user_id=current_user.id,
        app_type=body.app_type,
        app_name=body.app_name or domain.domain_name,
        app_root=body.app_root,
        entry_point=entry_point,
        runtime_version=body.runtime_version,
        port=body.port,
        env_vars=body.env_vars,
        startup_command=body.startup_command,
        is_running=False,
        pid=None,
    )
    db.add(app)
    await db.flush()

    # Set up the app environment
    system_warning: str | None = None
    try:
        if body.app_type == "node":
            setup_result = await _setup_node_app(app, current_user.username)
        else:
            setup_result = await _setup_python_app(app, current_user.username)

        setup_warnings = setup_result.get("warnings", [])

        # Configure nginx reverse proxy
        proxy_result = await _configure_reverse_proxy(domain.domain_name, body.port)
        setup_warnings.extend(proxy_result.get("warnings", []))

        if setup_warnings:
            system_warning = "; ".join(setup_warnings)
    except Exception as exc:
        system_warning = f"App saved to DB but system setup failed: {exc}"

    _log(db, request, current_user.id, "runtime.create", f"Created {body.app_type} app on {domain.domain_name}")

    resp = RuntimeAppResponse.model_validate(app)
    resp.domain_name = domain.domain_name
    return resp


# ---------------------------------------------------------------------------
# PUT /apps/{id} -- update runtime app settings
# ---------------------------------------------------------------------------

@router.put("/apps/{app_id}", response_model=RuntimeAppResponse)
async def update_runtime_app(
    app_id: uuid.UUID,
    body: RuntimeAppUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)
    update_data = body.model_dump(exclude_unset=True)

    # If port changed, check it's not in use
    if "port" in update_data and update_data["port"] != app.port:
        existing = await db.execute(
            select(RuntimeApp).where(
                RuntimeApp.port == update_data["port"],
                RuntimeApp.id != app_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Port {update_data['port']} is already in use.",
            )

    was_running = app.is_running
    old_port = app.port

    for field, value in update_data.items():
        setattr(app, field, value)
    db.add(app)
    await db.flush()

    # Regenerate service file and nginx proxy if needed
    try:
        # Get domain info
        domain_result = await db.execute(select(Domain).where(Domain.id == app.domain_id))
        domain = domain_result.scalar_one_or_none()
        username = current_user.username

        if app.app_type == "node":
            await _setup_node_app(app, username)
        else:
            await _setup_python_app(app, username)

        # Update nginx proxy if port changed
        if "port" in update_data and update_data["port"] != old_port and domain:
            await _configure_reverse_proxy(domain.domain_name, app.port)

        # Restart if was running
        if was_running:
            svc = _service_name(app.id)
            await _run(f"systemctl restart {svc}")
    except Exception as exc:
        logger.warning("Failed to update runtime app system config: %s", exc)

    _log(db, request, current_user.id, "runtime.update", f"Updated runtime app {app_id}")

    resp = RuntimeAppResponse.model_validate(app)
    if domain:
        resp.domain_name = domain.domain_name
    return resp


# ---------------------------------------------------------------------------
# DELETE /apps/{id} -- remove runtime app
# ---------------------------------------------------------------------------

@router.delete("/apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_runtime_app(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)

    # Stop and remove service
    try:
        warnings = await _remove_service(app)
        if warnings:
            logger.warning("Warnings removing runtime app %s: %s", app_id, warnings)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"System error removing app: {exc}",
        )

    _log(db, request, current_user.id, "runtime.delete", f"Deleted runtime app {app_id}")
    await db.delete(app)
    await db.flush()


# ---------------------------------------------------------------------------
# POST /apps/{id}/start
# ---------------------------------------------------------------------------

@router.post("/apps/{app_id}/start")
async def start_runtime_app(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)

    svc = _service_name(app.id)

    if app.app_type == "node":
        # Start via PM2 through systemd
        rc, out, err = await _run(f"systemctl start {svc}")
        if rc != 0:
            # Fallback: try PM2 directly
            eco_path = Path(app.app_root) / "ecosystem.config.json"
            rc2, out2, err2 = await _run(f"sudo -u $(stat -c '%U' {app.app_root}) pm2 start {eco_path}")
            if rc2 != 0:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to start app: {err or err2}",
                )
    else:
        rc, out, err = await _run(f"systemctl start {svc}")
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start app: {err or out}",
            )

    # Get PID
    rc, pid_out, _ = await _run(f"systemctl show -p MainPID --value {svc}")
    pid = int(pid_out) if pid_out.isdigit() and int(pid_out) > 0 else None

    app.is_running = True
    app.pid = pid
    db.add(app)
    await db.flush()

    _log(db, request, current_user.id, "runtime.start", f"Started runtime app {app_id}")
    return {"ok": True, "app_id": str(app_id), "action": "start", "pid": pid}


# ---------------------------------------------------------------------------
# POST /apps/{id}/stop
# ---------------------------------------------------------------------------

@router.post("/apps/{app_id}/stop")
async def stop_runtime_app(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)

    svc = _service_name(app.id)
    rc, out, err = await _run(f"systemctl stop {svc}")

    # Also stop PM2 process for Node apps
    if app.app_type == "node":
        await _run(f"pm2 stop {svc} 2>/dev/null || true")

    if rc != 0:
        logger.warning("systemctl stop %s returned %d: %s", svc, rc, err)

    app.is_running = False
    app.pid = None
    db.add(app)
    await db.flush()

    _log(db, request, current_user.id, "runtime.stop", f"Stopped runtime app {app_id}")
    return {"ok": True, "app_id": str(app_id), "action": "stop"}


# ---------------------------------------------------------------------------
# POST /apps/{id}/restart
# ---------------------------------------------------------------------------

@router.post("/apps/{app_id}/restart")
async def restart_runtime_app(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)

    svc = _service_name(app.id)

    if app.app_type == "node":
        rc, out, err = await _run(f"systemctl restart {svc}")
        if rc != 0:
            # Fallback PM2
            await _run(f"pm2 restart {svc} 2>/dev/null || true")
    else:
        rc, out, err = await _run(f"systemctl restart {svc}")
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restart app: {err or out}",
            )

    # Get PID
    rc, pid_out, _ = await _run(f"systemctl show -p MainPID --value {svc}")
    pid = int(pid_out) if pid_out.isdigit() and int(pid_out) > 0 else None

    app.is_running = True
    app.pid = pid
    db.add(app)
    await db.flush()

    _log(db, request, current_user.id, "runtime.restart", f"Restarted runtime app {app_id}")
    return {"ok": True, "app_id": str(app_id), "action": "restart", "pid": pid}


# ---------------------------------------------------------------------------
# GET /apps/{id}/logs
# ---------------------------------------------------------------------------

@router.get("/apps/{app_id}/logs")
async def get_runtime_app_logs(
    app_id: uuid.UUID,
    lines: int = Query(200, ge=1, le=10000),
    log_type: str = Query("stdout", pattern="^(stdout|stderr|all)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)

    logs: dict[str, list[str]] = {}

    if log_type in ("stdout", "all"):
        stdout_path = LOG_DIR / f"{app.id}.stdout.log"
        try:
            rc, out, _ = await _run(f"tail -n {lines} {stdout_path} 2>/dev/null")
            logs["stdout"] = out.split("\n") if out else []
        except Exception:
            logs["stdout"] = []

    if log_type in ("stderr", "all"):
        stderr_path = LOG_DIR / f"{app.id}.stderr.log"
        try:
            rc, out, _ = await _run(f"tail -n {lines} {stderr_path} 2>/dev/null")
            logs["stderr"] = out.split("\n") if out else []
        except Exception:
            logs["stderr"] = []

    return {"app_id": str(app_id), "logs": logs}


# ---------------------------------------------------------------------------
# POST /apps/{id}/install-deps
# ---------------------------------------------------------------------------

@router.post("/apps/{app_id}/install-deps")
async def install_runtime_deps(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_app_or_404(app_id, db, current_user)
    username = current_user.username
    app_root = Path(app.app_root)

    if app.app_type == "node":
        # npm install or yarn install
        package_json = app_root / "package.json"
        yarn_lock = app_root / "yarn.lock"

        if yarn_lock.exists():
            cmd = f"sudo -u {username} bash -lc 'cd {app_root} && yarn install --production'"
        elif package_json.exists():
            cmd = f"sudo -u {username} bash -lc 'cd {app_root} && npm install --production'"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No package.json found in app root.",
            )

        rc, out, err = await _run(cmd)
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"npm/yarn install failed: {err or out}",
            )

        _log(db, request, current_user.id, "runtime.install_deps", f"Installed Node.js dependencies for app {app_id}")
        return {"ok": True, "output": out, "type": "node"}

    else:  # Python
        requirements = app_root / "requirements.txt"
        venv_pip = app_root / "venv" / "bin" / "pip"

        if not requirements.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No requirements.txt found in app root.",
            )

        pip = str(venv_pip) if venv_pip.exists() else "pip3"
        cmd = f"sudo -u {username} {pip} install -r {requirements}"
        rc, out, err = await _run(cmd)
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"pip install failed: {err or out}",
            )

        _log(db, request, current_user.id, "runtime.install_deps", f"Installed Python dependencies for app {app_id}")
        return {"ok": True, "output": out, "type": "python"}
