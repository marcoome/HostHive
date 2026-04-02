"""
Docker executor -- container lifecycle, compose deployments, and stats.

All subprocess calls use list arguments.  shell=True is NEVER used.
Containers are isolated per user via Docker labels.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.executors._helpers import safe_path

log = logging.getLogger("novapanel.agent.docker")

# Label used to associate containers with panel users.
_USER_LABEL = "com.hosthive.user"
_MANAGED_LABEL = "com.hosthive.managed"

# Allowed image name pattern -- prevent injection.
_IMAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_./:@-]{0,255}$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a docker CLI command with list args.  Never uses shell=True."""
    cmd = ["docker"] + list(args)
    log.info("docker exec: %s", cmd)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _validate_image(image: str) -> str:
    image = image.strip()
    if not _IMAGE_RE.match(image):
        raise ValueError(f"Invalid Docker image name: {image!r}")
    return image


def _validate_name(name: str) -> str:
    name = name.strip()
    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid container name: {name!r}")
    return name


def _parse_container_json(raw: str) -> List[Dict[str, Any]]:
    """Parse docker inspect / docker ps JSON output."""
    if not raw.strip():
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _container_belongs_to_user(container_id: str, user: str) -> bool:
    """Check that a container is labelled with the given user."""
    r = _docker("inspect", "--format", "{{index .Config.Labels \"" + _USER_LABEL + "\"}}", container_id)
    return r.stdout.strip() == user


# ---------------------------------------------------------------------------
# Container listing
# ---------------------------------------------------------------------------

def list_containers(user: Optional[str] = None) -> List[Dict[str, Any]]:
    """List containers.  If *user* is given, filter to that user's containers."""
    filter_args: List[str] = ["--filter", f"label={_MANAGED_LABEL}=true"]
    if user:
        filter_args += ["--filter", f"label={_USER_LABEL}={user}"]

    r = _docker(
        "ps", "-a",
        "--format", "{{json .}}",
        *filter_args,
    )
    if r.returncode != 0:
        raise RuntimeError(f"docker ps failed: {r.stderr}")

    containers = []
    for line in r.stdout.strip().splitlines():
        if line.strip():
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return containers


# ---------------------------------------------------------------------------
# Container deploy
# ---------------------------------------------------------------------------

def deploy_container(
    image: str,
    name: str,
    ports: Optional[Dict[str, str]] = None,
    env: Optional[Dict[str, str]] = None,
    volumes: Optional[Dict[str, str]] = None,
    user: str = "admin",
) -> Dict[str, Any]:
    """Deploy a new Docker container.

    *ports* maps host_port -> container_port (e.g. ``{"8080": "80"}``).
    *env* maps env var name -> value.
    *volumes* maps host_path -> container_path.
    """
    image = _validate_image(image)
    name = _validate_name(name)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", name,
        "--label", f"{_MANAGED_LABEL}=true",
        "--label", f"{_USER_LABEL}={user}",
        "--restart", "unless-stopped",
    ]

    # Port mappings
    if ports:
        for host_port, container_port in ports.items():
            cmd_args += ["-p", f"{host_port}:{container_port}"]

    # Environment variables
    if env:
        for key, value in env.items():
            cmd_args += ["-e", f"{key}={value}"]

    # Volume mounts
    if volumes:
        for host_path, container_path in volumes.items():
            # Validate host path is within allowed directories
            resolved = os.path.realpath(host_path)
            if not any(resolved.startswith(p) for p in ("/home/", "/opt/", "/var/", "/tmp/")):
                raise PermissionError(f"Volume host path not allowed: {host_path!r}")
            cmd_args += ["-v", f"{resolved}:{container_path}"]

    cmd_args.append(image)

    r = _docker(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"docker run failed: {r.stderr}")

    container_id = r.stdout.strip()[:12]

    # Retrieve container info
    info = _docker("inspect", container_id)
    data = _parse_container_json(info.stdout)

    return {
        "container_id": container_id,
        "name": name,
        "image": image,
        "status": "running",
        "ports": ports or {},
        "inspect": data[0] if data else {},
    }


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------

def start_container(container_id: str, user: Optional[str] = None) -> Dict[str, Any]:
    """Start a stopped container."""
    if user and not _container_belongs_to_user(container_id, user):
        raise PermissionError("Container does not belong to this user")
    r = _docker("start", container_id)
    if r.returncode != 0:
        raise RuntimeError(f"docker start failed: {r.stderr}")
    return {"container_id": container_id, "action": "started"}


def stop_container(container_id: str, user: Optional[str] = None) -> Dict[str, Any]:
    """Stop a running container."""
    if user and not _container_belongs_to_user(container_id, user):
        raise PermissionError("Container does not belong to this user")
    r = _docker("stop", container_id)
    if r.returncode != 0:
        raise RuntimeError(f"docker stop failed: {r.stderr}")
    return {"container_id": container_id, "action": "stopped"}


def restart_container(container_id: str, user: Optional[str] = None) -> Dict[str, Any]:
    """Restart a container."""
    if user and not _container_belongs_to_user(container_id, user):
        raise PermissionError("Container does not belong to this user")
    r = _docker("restart", container_id)
    if r.returncode != 0:
        raise RuntimeError(f"docker restart failed: {r.stderr}")
    return {"container_id": container_id, "action": "restarted"}


def remove_container(container_id: str, user: Optional[str] = None) -> Dict[str, Any]:
    """Remove (delete) a container.  Stops it first if running."""
    if user and not _container_belongs_to_user(container_id, user):
        raise PermissionError("Container does not belong to this user")
    # Force stop + remove
    _docker("stop", container_id)
    r = _docker("rm", container_id)
    if r.returncode != 0:
        raise RuntimeError(f"docker rm failed: {r.stderr}")
    return {"container_id": container_id, "action": "removed"}


# ---------------------------------------------------------------------------
# Logs and stats
# ---------------------------------------------------------------------------

def get_container_logs(container_id: str, lines: int = 200, user: Optional[str] = None) -> str:
    """Return the last *lines* of container logs."""
    if user and not _container_belongs_to_user(container_id, user):
        raise PermissionError("Container does not belong to this user")
    r = _docker("logs", "--tail", str(lines), container_id)
    if r.returncode != 0:
        raise RuntimeError(f"docker logs failed: {r.stderr}")
    return r.stdout + r.stderr


def get_container_stats(container_id: str, user: Optional[str] = None) -> Dict[str, Any]:
    """Return CPU and memory usage for a container (single snapshot)."""
    if user and not _container_belongs_to_user(container_id, user):
        raise PermissionError("Container does not belong to this user")
    r = _docker(
        "stats", "--no-stream",
        "--format", "{{json .}}",
        container_id,
    )
    if r.returncode != 0:
        raise RuntimeError(f"docker stats failed: {r.stderr}")

    try:
        return json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return {"raw": r.stdout.strip()}


# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

def validate_compose(compose_yaml: str) -> List[str]:
    """Validate a docker-compose YAML string.  Returns a list of errors (empty = valid)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", prefix="compose_", delete=False,
    ) as f:
        f.write(compose_yaml)
        tmp_path = f.name

    try:
        r = _docker("compose", "-f", tmp_path, "config", "--quiet", timeout=30)
        if r.returncode != 0:
            return [line for line in r.stderr.strip().splitlines() if line.strip()]
        return []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def deploy_compose(
    compose_yaml: str,
    project_name: str,
    user: str = "admin",
) -> List[Dict[str, Any]]:
    """Deploy services from a docker-compose YAML string.

    All created containers are labelled with the user.
    """
    project_name = _validate_name(project_name)

    # Write compose file to temp location
    compose_dir = Path(tempfile.mkdtemp(prefix="compose_"))
    compose_file = compose_dir / "docker-compose.yml"
    compose_file.write_text(compose_yaml)

    try:
        # Validate first
        errors = validate_compose(compose_yaml)
        if errors:
            raise ValueError(f"Invalid compose file: {'; '.join(errors)}")

        # Deploy
        r = subprocess.run(
            [
                "docker", "compose",
                "-f", str(compose_file),
                "-p", project_name,
                "up", "-d",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "COMPOSE_PROJECT_NAME": project_name},
        )
        if r.returncode != 0:
            raise RuntimeError(f"docker compose up failed: {r.stderr}")

        # Label all containers in the project
        ps_result = subprocess.run(
            [
                "docker", "compose",
                "-f", str(compose_file),
                "-p", project_name,
                "ps", "--format", "{{json .}}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        containers = []
        for line in ps_result.stdout.strip().splitlines():
            if line.strip():
                try:
                    c = json.loads(line)
                    container_id = c.get("ID", "")
                    if container_id:
                        # Apply user labels
                        _docker(
                            "container", "update",
                            "--label-add", f"{_MANAGED_LABEL}=true",
                            "--label-add", f"{_USER_LABEL}={user}",
                            container_id,
                        )
                    containers.append(c)
                except json.JSONDecodeError:
                    continue

        return containers

    finally:
        # Clean up temp compose file
        try:
            compose_file.unlink()
            compose_dir.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Nginx reverse proxy helper
# ---------------------------------------------------------------------------

_PROXY_TEMPLATE = """
server {{
    listen 80;
    server_name {domain};

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
}}
"""


def setup_nginx_proxy(domain: str, port: int | str) -> Dict[str, Any]:
    """Create an nginx reverse-proxy config for a container's web port.

    The config is written to /etc/nginx/conf.d/{domain}.conf and nginx is
    reloaded.
    """
    from agent.executors._helpers import safe_domain, atomic_write

    domain = safe_domain(domain)
    port = str(int(port))  # validate numeric

    conf_path = f"/etc/nginx/conf.d/{domain}.conf"
    content = _PROXY_TEMPLATE.format(domain=domain, port=port)
    atomic_write(conf_path, content, mode=0o644)

    # Reload nginx
    r = subprocess.run(
        ["systemctl", "reload", "nginx"],
        capture_output=True,
        text=True,
        timeout=15,
    )

    return {
        "domain": domain,
        "port": port,
        "config_path": conf_path,
        "nginx_reload": r.returncode == 0,
    }
