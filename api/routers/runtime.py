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
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Sequence, Union

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

# Default subprocess timeout (seconds) so a hung command never blocks the API.
_DEFAULT_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _run_sync(
    cmd: Union[str, Sequence[str]],
    *,
    shell: bool = False,
    timeout: int = _DEFAULT_TIMEOUT,
    cwd: Optional[str] = None,
) -> tuple[int, str, str]:
    """Synchronous subprocess runner -- intended for run_in_executor.

    Runs the command directly via subprocess.run (no proxying through any
    agent / network service). Prefers list-form arguments to avoid shell
    injection; only falls back to shell=True when explicitly requested.
    """
    try:
        completed = subprocess.run(
            cmd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"Command timed out after {timeout}s: {exc}"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except Exception as exc:  # noqa: BLE001 - surface any subprocess error
        return 1, "", str(exc)

    stdout = (completed.stdout or b"").decode(errors="replace").strip()
    stderr = (completed.stderr or b"").decode(errors="replace").strip()
    return completed.returncode, stdout, stderr


async def _run(
    cmd: Union[str, Sequence[str]],
    *,
    shell: bool = False,
    timeout: int = _DEFAULT_TIMEOUT,
    cwd: Optional[str] = None,
) -> tuple[int, str, str]:
    """Run a command off the event loop via run_in_executor.

    All blocking subprocess work happens in a thread pool so the FastAPI
    event loop stays responsive. This deliberately uses local subprocess --
    there is no remote agent / port 7080 proxy.
    """
    loop = asyncio.get_running_loop()
    # If a string is passed without shell=True, treat it as a shell command
    # for backwards compatibility with the original API.
    if isinstance(cmd, str) and not shell:
        shell = True
    return await loop.run_in_executor(
        None, lambda: _run_sync(cmd, shell=shell, timeout=timeout, cwd=cwd)
    )


async def _to_thread(func, *args, **kwargs):
    """Run a blocking callable in the default thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


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


def _path_owner(path: Path) -> Optional[str]:
    """Return the owning username of a filesystem path, or None on failure."""
    try:
        import pwd

        stat = path.stat()
        return pwd.getpwuid(stat.st_uid).pw_name
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Node.js helpers (PM2)
# ---------------------------------------------------------------------------

async def _setup_node_app(app: RuntimeApp, username: str) -> dict:
    """Set up a Node.js application directory with nvm and PM2."""
    warnings: list[str] = []
    app_root = Path(app.app_root)

    # Ensure app root exists
    try:
        await _to_thread(app_root.mkdir, parents=True, exist_ok=True)
        await _run(["chown", "-R", f"{username}:{username}", str(app_root)])
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
        await _to_thread(
            eco_path.write_text,
            json.dumps(ecosystem, indent=2),
            encoding="utf-8",
        )
        await _run(["chown", f"{username}:{username}", str(eco_path)])
    except Exception as exc:
        warnings.append(f"Could not write ecosystem file: {exc}")

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
        await _to_thread(LOG_DIR.mkdir, parents=True, exist_ok=True)
        await _to_thread(
            _service_file_path(app.id).write_text,
            service_content,
            encoding="utf-8",
        )
        await _run(["systemctl", "daemon-reload"])
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
        await _to_thread(app_root.mkdir, parents=True, exist_ok=True)
        await _run(["chown", "-R", f"{username}:{username}", str(app_root)])
    except Exception as exc:
        warnings.append(f"Could not create app root: {exc}")

    # Create virtualenv (direct subprocess, no agent proxy)
    python_bin = f"python{app.runtime_version}"
    venv_path = app_root / "venv"
    venv_exists = await _to_thread(venv_path.exists)
    if not venv_exists:
        rc, out, err = await _run(
            ["sudo", "-u", username, python_bin, "-m", "venv", str(venv_path)]
        )
        if rc != 0:
            # Try without minor version
            major = app.runtime_version.split(".")[0]
            rc, out, err = await _run(
                ["sudo", "-u", username, f"python{major}", "-m", "venv", str(venv_path)]
            )
            if rc != 0:
                warnings.append(f"Failed to create virtualenv: {err or out}")

    # Install gunicorn/uvicorn in venv via direct pip subprocess
    pip_bin = venv_path / "bin" / "pip"
    pip_exists = await _to_thread(pip_bin.exists)
    if pip_exists:
        rc, out, err = await _run(
            ["sudo", "-u", username, str(pip_bin), "install", "--quiet", "gunicorn", "uvicorn"]
        )
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
        await _to_thread(LOG_DIR.mkdir, parents=True, exist_ok=True)
        await _to_thread(
            _service_file_path(app.id).write_text,
            service_content,
            encoding="utf-8",
        )
        await _run(["systemctl", "daemon-reload"])
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
        await _to_thread(vhost_path.write_text, config, encoding="utf-8")
    except Exception as exc:
        warnings.append(f"Failed to write nginx proxy config: {exc}")

    def _make_symlink() -> None:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(vhost_path)

    try:
        await _to_thread(_make_symlink)
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

    # Stop via systemd (direct subprocess)
    await _run(["systemctl", "stop", svc])
    await _run(["systemctl", "disable", svc])

    # Also try PM2 cleanup for Node apps -- ignore errors if not present.
    if app.app_type == "node":
        await _run(["pm2", "delete", svc])

    # Remove service file
    svc_path = _service_file_path(app.id)

    def _unlink_if_exists(path: Path) -> None:
        if path.exists():
            path.unlink()

    try:
        await _to_thread(_unlink_if_exists, svc_path)
        await _run(["systemctl", "daemon-reload"])
    except Exception as exc:
        warnings.append(f"Could not remove service file: {exc}")

    # Clean up log files
    for suffix in (".log", ".stdout.log", ".stderr.log"):
        log_file = LOG_DIR / f"{app.id}{suffix}"
        try:
            await _to_thread(_unlink_if_exists, log_file)
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

    # Detect Node.js versions -- check system node directly via subprocess
    rc, out, _ = await _run(["node", "--version"])
    if rc == 0 and out:
        ver = out.lstrip("v").split(".")[0]
        if ver not in node_versions:
            node_versions.append(ver)

    # Check nvm-managed versions by scanning known directories on disk
    def _scan_nvm() -> list[str]:
        found: list[str] = []
        candidates: list[Path] = []
        home = Path("/home")
        if home.exists():
            for user_dir in home.iterdir():
                nvm_versions = user_dir / ".nvm" / "versions" / "node"
                if nvm_versions.is_dir():
                    candidates.append(nvm_versions)
        global_nvm = Path("/usr/local/nvm/versions/node")
        if global_nvm.is_dir():
            candidates.append(global_nvm)
        for c in candidates:
            try:
                for entry in c.iterdir():
                    v = entry.name.lstrip("v").split(".")[0]
                    if v.isdigit() and v not in found:
                        found.append(v)
            except Exception:
                continue
        return found

    for v in await _to_thread(_scan_nvm):
        if v not in node_versions:
            node_versions.append(v)

    # Common Node.js versions as fallback
    if not node_versions:
        node_versions = ["18", "20", "22"]

    # Detect Python versions -- direct subprocess per candidate
    for minor in range(8, 14):
        ver = f"3.{minor}"
        rc, _, _ = await _run([f"python{ver}", "--version"])
        if rc == 0:
            python_versions.append(ver)

    # Fallback
    if not python_versions:
        rc, out, _ = await _run(["python3", "--version"])
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
            await _run(["systemctl", "restart", svc])
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
        # Start via systemd unit (which wraps PM2)
        rc, out, err = await _run(["systemctl", "start", svc])
        if rc != 0:
            # Fallback: try PM2 directly as the file's owning user
            eco_path = Path(app.app_root) / "ecosystem.config.json"
            owner = await _to_thread(_path_owner, Path(app.app_root))
            if owner:
                rc2, out2, err2 = await _run(
                    ["sudo", "-u", owner, "pm2", "start", str(eco_path)]
                )
            else:
                rc2, out2, err2 = await _run(["pm2", "start", str(eco_path)])
            if rc2 != 0:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to start app: {err or err2}",
                )
    else:
        rc, out, err = await _run(["systemctl", "start", svc])
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start app: {err or out}",
            )

    # Get PID
    rc, pid_out, _ = await _run(["systemctl", "show", "-p", "MainPID", "--value", svc])
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
    rc, out, err = await _run(["systemctl", "stop", svc])

    # Also stop PM2 process for Node apps -- ignore failures.
    if app.app_type == "node":
        await _run(["pm2", "stop", svc])

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
        rc, out, err = await _run(["systemctl", "restart", svc])
        if rc != 0:
            # Fallback PM2 -- ignore errors if PM2 isn't available.
            await _run(["pm2", "restart", svc])
    else:
        rc, out, err = await _run(["systemctl", "restart", svc])
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restart app: {err or out}",
            )

    # Get PID
    rc, pid_out, _ = await _run(["systemctl", "show", "-p", "MainPID", "--value", svc])
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

    def _tail_file(path: Path, n: int) -> list[str]:
        try:
            if not path.exists():
                return []
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                # Read all lines then keep the last n. For very large files
                # this is fine because the API caps `lines` at 10000.
                content = fh.readlines()
            tail = content[-n:]
            return [line.rstrip("\n") for line in tail]
        except Exception:
            return []

    logs: dict[str, list[str]] = {}

    if log_type in ("stdout", "all"):
        stdout_path = LOG_DIR / f"{app.id}.stdout.log"
        logs["stdout"] = await _to_thread(_tail_file, stdout_path, lines)

    if log_type in ("stderr", "all"):
        stderr_path = LOG_DIR / f"{app.id}.stderr.log"
        logs["stderr"] = await _to_thread(_tail_file, stderr_path, lines)

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
        # Direct npm / yarn install -- no shell, no agent proxy.
        package_json = app_root / "package.json"
        yarn_lock = app_root / "yarn.lock"

        package_exists = await _to_thread(package_json.exists)
        yarn_exists = await _to_thread(yarn_lock.exists)

        if yarn_exists:
            cmd = ["sudo", "-u", username, "yarn", "install", "--production"]
        elif package_exists:
            cmd = ["sudo", "-u", username, "npm", "install", "--production"]
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No package.json found in app root.",
            )

        rc, out, err = await _run(cmd, cwd=str(app_root), timeout=900)
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"npm/yarn install failed: {err or out}",
            )

        _log(db, request, current_user.id, "runtime.install_deps", f"Installed Node.js dependencies for app {app_id}")
        return {"ok": True, "output": out, "type": "node"}

    else:  # Python -- direct pip subprocess.
        requirements = app_root / "requirements.txt"
        venv_pip = app_root / "venv" / "bin" / "pip"

        req_exists = await _to_thread(requirements.exists)
        if not req_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No requirements.txt found in app root.",
            )

        venv_pip_exists = await _to_thread(venv_pip.exists)
        pip = str(venv_pip) if venv_pip_exists else "pip3"
        cmd = ["sudo", "-u", username, pip, "install", "-r", str(requirements)]
        rc, out, err = await _run(cmd, cwd=str(app_root), timeout=900)
        if rc != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"pip install failed: {err or out}",
            )

        _log(db, request, current_user.id, "runtime.install_deps", f"Installed Python dependencies for app {app_id}")
        return {"ok": True, "output": out, "type": "python"}
