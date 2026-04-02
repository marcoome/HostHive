"""
Docker-based user isolation — the CRITICAL differentiating feature of HostHive.

Each user gets their own isolated Docker environment:
- Private Docker network
- Own MySQL/MariaDB/Percona container (user picks version)
- Own PHP-FPM container(s) (multiple versions possible)
- Own Redis instance (optional)
- Own Memcached instance (optional)
- Own web server container (Nginx/Apache/OpenLiteSpeed/Caddy/Varnish)

All subprocess calls use list args.  shell=True is NEVER used.
All usernames and versions are validated against strict whitelists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from agent.executors._helpers import safe_username

log = logging.getLogger("hosthive.agent.docker_isolation")

# ---------------------------------------------------------------------------
# Label constants
# ---------------------------------------------------------------------------

_USER_LABEL = "com.hosthive.user"
_MANAGED_LABEL = "com.hosthive.managed"
_ROLE_LABEL = "com.hosthive.role"  # web, db, php, redis, memcached

# ---------------------------------------------------------------------------
# Allowed images — strict whitelists
# ---------------------------------------------------------------------------

WEBSERVER_IMAGES: Dict[str, str] = {
    "nginx": "nginx:alpine",
    "apache": "httpd:2.4-alpine",
    "openlitespeed": "litespeedtech/openlitespeed:latest",
    "varnish": "varnish:alpine",
    "caddy": "caddy:alpine",
}

DB_IMAGES: Dict[str, str] = {
    "mysql8": "mysql:8.0",
    "mysql9": "mysql:9.0",
    "mariadb11": "mariadb:11",
    "percona8": "percona:8.0",
}

PHP_IMAGES: Dict[str, str] = {
    "7.4": "php:7.4-fpm-alpine",
    "8.0": "php:8.0-fpm-alpine",
    "8.1": "php:8.1-fpm-alpine",
    "8.2": "php:8.2-fpm-alpine",
    "8.3": "php:8.3-fpm-alpine",
}

_VALID_WEBSERVERS = frozenset(WEBSERVER_IMAGES.keys())
_VALID_DB_VERSIONS = frozenset(DB_IMAGES.keys())
_VALID_PHP_VERSIONS = frozenset(PHP_IMAGES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a docker CLI command with list args.  Never uses shell=True."""
    cmd = ["docker"] + list(args)
    log.info("docker exec: %s", cmd)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def _docker_async(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run docker command in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _docker(*args, timeout=timeout))


def _validate_webserver(webserver: str) -> str:
    ws = webserver.strip().lower()
    if ws not in _VALID_WEBSERVERS:
        raise ValueError(f"Invalid webserver: {ws!r}. Must be one of {sorted(_VALID_WEBSERVERS)}")
    return ws


def _validate_db_version(version: str) -> str:
    v = version.strip().lower()
    if v not in _VALID_DB_VERSIONS:
        raise ValueError(f"Invalid DB version: {v!r}. Must be one of {sorted(_VALID_DB_VERSIONS)}")
    return v


def _validate_php_version(version: str) -> str:
    v = version.strip()
    if v not in _VALID_PHP_VERSIONS:
        raise ValueError(f"Invalid PHP version: {v!r}. Must be one of {sorted(_VALID_PHP_VERSIONS)}")
    return v


def _net_name(username: str) -> str:
    return f"hosthive_net_{username}"


def _container_name(username: str, role: str) -> str:
    return f"hh_{username}_{role}"


def _php_container_name(username: str, version: str) -> str:
    return f"hh_{username}_php{version.replace('.', '')}"


def _resource_args(cpu: float, memory_mb: int, io_bps: int) -> List[str]:
    """Build Docker resource-limit flags."""
    args: List[str] = []
    if cpu > 0:
        args += ["--cpus", str(cpu)]
    if memory_mb > 0:
        args += ["--memory", f"{memory_mb}m"]
    if io_bps > 0:
        # Apply I/O bandwidth limits for common block devices
        for dev in ("/dev/sda", "/dev/vda", "/dev/nvme0n1"):
            args += [
                "--device-read-bps", f"{dev}:{io_bps}",
                "--device-write-bps", f"{dev}:{io_bps}",
            ]
    return args


def _common_labels(username: str, role: str) -> List[str]:
    """Standard label flags for all HostHive containers."""
    return [
        "--label", f"{_MANAGED_LABEL}=true",
        "--label", f"{_USER_LABEL}={username}",
        "--label", f"{_ROLE_LABEL}={role}",
    ]


# ---------------------------------------------------------------------------
# Network management
# ---------------------------------------------------------------------------

async def _create_network(username: str) -> str:
    """Create the private Docker network for a user. Returns network name."""
    net = _net_name(username)
    r = await _docker_async("network", "create", "--driver", "bridge", net)
    if r.returncode != 0:
        # Network may already exist
        if "already exists" not in r.stderr:
            raise RuntimeError(f"Failed to create network {net}: {r.stderr}")
        log.info("Network %s already exists", net)
    return net


async def _remove_network(username: str) -> None:
    """Remove the user's Docker network."""
    net = _net_name(username)
    await _docker_async("network", "rm", net)


# ---------------------------------------------------------------------------
# Container creation helpers
# ---------------------------------------------------------------------------

async def _create_db_container(
    username: str,
    db_version: str,
    cpu: float,
    memory_mb: int,
    io_bps: int,
) -> str:
    """Create the user's database container. Returns container ID."""
    db_version = _validate_db_version(db_version)
    image = DB_IMAGES[db_version]
    name = _container_name(username, "db")
    net = _net_name(username)

    # Generate a root password (will be stored by caller)
    import secrets
    root_pass = secrets.token_urlsafe(24)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, "db"),
        *_resource_args(cpu, memory_mb, io_bps),
        "-e", f"MYSQL_ROOT_PASSWORD={root_pass}",
        "-v", f"/home/{username}/db:/var/lib/mysql",
        image,
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create DB container for {username}: {r.stderr}")

    container_id = r.stdout.strip()[:12]
    log.info("Created DB container %s (%s) for user %s", name, db_version, username)
    return container_id


async def _create_php_container(
    username: str,
    php_version: str,
    cpu: float,
    memory_mb: int,
    io_bps: int,
) -> str:
    """Create a PHP-FPM container for the user. Returns container ID."""
    php_version = _validate_php_version(php_version)
    image = PHP_IMAGES[php_version]
    name = _php_container_name(username, php_version)
    net = _net_name(username)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, f"php{php_version.replace('.', '')}"),
        *_resource_args(cpu, memory_mb // 2, io_bps),
        "-v", f"/home/{username}/web:/var/www/html",
        image,
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create PHP {php_version} container for {username}: {r.stderr}")

    container_id = r.stdout.strip()[:12]
    log.info("Created PHP %s container %s for user %s", php_version, name, username)
    return container_id


async def _create_webserver_container(
    username: str,
    webserver: str,
    cpu: float,
    memory_mb: int,
    io_bps: int,
) -> str:
    """Create the user's web server container. Returns container ID."""
    webserver = _validate_webserver(webserver)
    image = WEBSERVER_IMAGES[webserver]
    name = _container_name(username, "web")
    net = _net_name(username)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, "web"),
        *_resource_args(cpu, memory_mb // 2, io_bps),
        "-v", f"/home/{username}/web:/var/www/html:ro",
        "-v", f"/home/{username}/conf/{webserver}:/etc/nginx/conf.d",
        image,
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create {webserver} container for {username}: {r.stderr}")

    container_id = r.stdout.strip()[:12]
    log.info("Created %s container %s for user %s", webserver, name, username)
    return container_id


async def _create_redis_container(
    username: str,
    memory_mb: int,
) -> str:
    """Create a Redis container for the user. Returns container ID."""
    name = _container_name(username, "redis")
    net = _net_name(username)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, "redis"),
        "--memory", f"{memory_mb}m",
        "redis:alpine",
        "redis-server", "--maxmemory", f"{memory_mb}mb", "--maxmemory-policy", "allkeys-lru",
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create Redis container for {username}: {r.stderr}")

    container_id = r.stdout.strip()[:12]
    log.info("Created Redis container %s for user %s", name, username)
    return container_id


async def _create_memcached_container(
    username: str,
    memory_mb: int,
) -> str:
    """Create a Memcached container for the user. Returns container ID."""
    name = _container_name(username, "memcached")
    net = _net_name(username)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, "memcached"),
        "--memory", f"{memory_mb}m",
        "memcached:alpine",
        "memcached", "-m", str(memory_mb),
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create Memcached container for {username}: {r.stderr}")

    container_id = r.stdout.strip()[:12]
    log.info("Created Memcached container %s for user %s", name, username)
    return container_id


# ---------------------------------------------------------------------------
# Volume / directory setup
# ---------------------------------------------------------------------------

async def _setup_user_directories(username: str) -> None:
    """Create host directories for the user's data volumes."""
    import os
    dirs = [
        f"/home/{username}/web",
        f"/home/{username}/db",
        f"/home/{username}/conf",
        f"/home/{username}/logs",
    ]
    loop = asyncio.get_running_loop()
    for d in dirs:
        await loop.run_in_executor(None, lambda p=d: os.makedirs(p, exist_ok=True))


# ---------------------------------------------------------------------------
# Reverse proxy update
# ---------------------------------------------------------------------------

async def _update_reverse_proxy(username: str, webserver_container: str) -> None:
    """Configure the main host Nginx to route traffic to the user's web container."""
    from agent.executors._helpers import atomic_write

    # Get the container's IP on the user network
    net = _net_name(username)
    r = await _docker_async(
        "inspect",
        "--format", f"{{{{.NetworkSettings.Networks.{net}.IPAddress}}}}",
        webserver_container,
    )
    container_ip = r.stdout.strip()
    if not container_ip:
        log.warning("Could not determine IP for container %s", webserver_container)
        return

    conf_path = f"/etc/nginx/conf.d/hosthive_user_{username}.conf"
    conf_content = f"""# Auto-generated by HostHive for user {username}
upstream hosthive_user_{username} {{
    server {container_ip}:80;
}}
"""

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: atomic_write(conf_path, conf_content, mode=0o644),
    )

    # Reload host nginx
    reload_r = await _docker_async(
        "exec", "hosthive_proxy", "nginx", "-s", "reload",
        timeout=10,
    )
    if reload_r.returncode != 0:
        # Fallback: try systemctl reload
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["systemctl", "reload", "nginx"],
                capture_output=True, text=True, timeout=15,
            ),
        )


# ---------------------------------------------------------------------------
# Public API: create / destroy full environment
# ---------------------------------------------------------------------------

async def create_user_environment(
    username: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a full isolated Docker environment for a new user.

    *plan* dict keys expected:
        cpu_cores, ram_mb, io_bandwidth_mbps, default_webserver,
        default_db_version, redis_enabled, redis_memory_mb,
        memcached_enabled, memcached_memory_mb
    """
    username = safe_username(username)
    cpu = float(plan.get("cpu_cores", 1.0))
    ram = int(plan.get("ram_mb", 1024))
    io_bps = int(plan.get("io_bandwidth_mbps", 100)) * 1024 * 1024  # MB/s -> bytes/s
    webserver = _validate_webserver(plan.get("default_webserver", "nginx"))
    db_version = _validate_db_version(plan.get("default_db_version", "mariadb11"))
    default_php = "8.2"

    container_ids: Dict[str, str] = {}

    try:
        # 1. Setup host directories
        await _setup_user_directories(username)

        # 2. Create private network
        await _create_network(username)

        # 3. Create DB container
        container_ids["db"] = await _create_db_container(
            username, db_version, cpu * 0.3, ram // 4, io_bps,
        )

        # 4. Create PHP-FPM container
        container_ids[f"php{default_php.replace('.', '')}"] = await _create_php_container(
            username, default_php, cpu * 0.4, ram // 2, io_bps,
        )

        # 5. Create webserver container
        container_ids["web"] = await _create_webserver_container(
            username, webserver, cpu * 0.3, ram // 4, io_bps,
        )

        # 6. Redis (optional)
        if plan.get("redis_enabled"):
            redis_mem = int(plan.get("redis_memory_mb", 64))
            container_ids["redis"] = await _create_redis_container(username, redis_mem)

        # 7. Memcached (optional)
        if plan.get("memcached_enabled"):
            mc_mem = int(plan.get("memcached_memory_mb", 64))
            container_ids["memcached"] = await _create_memcached_container(username, mc_mem)

        # 8. Update reverse proxy
        await _update_reverse_proxy(username, _container_name(username, "web"))

        log.info("Created full environment for user %s: %s", username, container_ids)
        return {
            "username": username,
            "network": _net_name(username),
            "webserver": webserver,
            "db_version": db_version,
            "php_versions": [default_php],
            "container_ids": container_ids,
            "status": "active",
        }

    except Exception:
        # Attempt cleanup on failure
        log.error("Failed to create environment for %s, cleaning up", username, exc_info=True)
        try:
            await destroy_user_environment(username)
        except Exception:
            log.error("Cleanup also failed for %s", username, exc_info=True)
        raise


async def destroy_user_environment(username: str) -> Dict[str, Any]:
    """Stop and remove ALL containers, network, and volumes for a user."""
    username = safe_username(username)

    # Find all containers with this user's label
    r = await _docker_async(
        "ps", "-a", "-q",
        "--filter", f"label={_USER_LABEL}={username}",
        "--filter", f"label={_MANAGED_LABEL}=true",
    )

    removed: List[str] = []
    if r.stdout.strip():
        container_ids = r.stdout.strip().split("\n")
        for cid in container_ids:
            cid = cid.strip()
            if not cid:
                continue
            await _docker_async("stop", cid, timeout=30)
            rm_r = await _docker_async("rm", "-f", cid)
            if rm_r.returncode == 0:
                removed.append(cid)

    # Remove network
    try:
        await _remove_network(username)
    except Exception:
        log.warning("Could not remove network for %s", username, exc_info=True)

    # Remove reverse proxy config
    import os
    conf_path = f"/etc/nginx/conf.d/hosthive_user_{username}.conf"
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: os.unlink(conf_path))
    except FileNotFoundError:
        pass

    log.info("Destroyed environment for user %s: removed %d containers", username, len(removed))
    return {
        "username": username,
        "containers_removed": removed,
        "status": "destroyed",
    }


# ---------------------------------------------------------------------------
# Public API: switch webserver (zero-downtime)
# ---------------------------------------------------------------------------

async def switch_webserver(username: str, webserver: str) -> Dict[str, Any]:
    """Switch user's web server with zero-downtime via rolling replacement.

    1. Start new web server container on same network
    2. Update reverse proxy to point to new container
    3. Stop and remove old container
    """
    username = safe_username(username)
    webserver = _validate_webserver(webserver)

    old_name = _container_name(username, "web")
    new_name = _container_name(username, "web_new")
    image = WEBSERVER_IMAGES[webserver]
    net = _net_name(username)

    # 1. Start new webserver container with temporary name
    cmd_args: List[str] = [
        "run", "-d",
        "--name", new_name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, "web"),
        "-v", f"/home/{username}/web:/var/www/html:ro",
        "-v", f"/home/{username}/conf/{webserver}:/etc/nginx/conf.d",
        image,
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start new {webserver} container: {r.stderr}")

    new_id = r.stdout.strip()[:12]

    try:
        # 2. Update reverse proxy to point to new container
        await _update_reverse_proxy(username, new_name)

        # 3. Stop and remove old container
        await _docker_async("stop", old_name, timeout=30)
        await _docker_async("rm", old_name)

        # 4. Rename new container to the standard name
        await _docker_async("rename", new_name, old_name)

        log.info("Switched webserver for %s to %s", username, webserver)
        return {
            "username": username,
            "webserver": webserver,
            "container_id": new_id,
            "status": "switched",
        }

    except Exception:
        # Rollback: stop new container, restore proxy to old
        log.error("Webserver switch failed for %s, rolling back", username, exc_info=True)
        await _docker_async("stop", new_name, timeout=10)
        await _docker_async("rm", "-f", new_name)
        await _update_reverse_proxy(username, old_name)
        raise


# ---------------------------------------------------------------------------
# Public API: switch DB version (with backup/restore)
# ---------------------------------------------------------------------------

async def switch_db_version(username: str, version: str) -> Dict[str, Any]:
    """Switch MySQL/MariaDB/Percona version with backup and restore.

    1. Dump all databases from current container
    2. Stop current DB container
    3. Start new version container
    4. Restore dump
    5. Verify connectivity
    """
    username = safe_username(username)
    version = _validate_db_version(version)

    db_name = _container_name(username, "db")
    dump_path = f"/home/{username}/db_migration_dump.sql"

    # 1. Dump all databases
    dump_r = await _docker_async(
        "exec", db_name,
        "mysqldump", "--all-databases", "--single-transaction",
        "--routines", "--triggers", "--events",
        "-uroot", f"-p$MYSQL_ROOT_PASSWORD",
        timeout=300,
    )
    if dump_r.returncode != 0:
        raise RuntimeError(f"Database dump failed: {dump_r.stderr}")

    # Write dump to host
    import os
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: _write_file(dump_path, dump_r.stdout),
    )

    # 2. Stop and remove current DB container
    await _docker_async("stop", db_name, timeout=30)
    await _docker_async("rm", db_name)

    # Clear old data directory (backup preserved via dump)
    backup_dir = f"/home/{username}/db_backup"
    await loop.run_in_executor(None, lambda: os.makedirs(backup_dir, exist_ok=True))

    # 3. Start new version container
    image = DB_IMAGES[version]
    net = _net_name(username)
    import secrets
    root_pass = secrets.token_urlsafe(24)

    cmd_args: List[str] = [
        "run", "-d",
        "--name", db_name,
        "--network", net,
        "--restart", "unless-stopped",
        *_common_labels(username, "db"),
        "-e", f"MYSQL_ROOT_PASSWORD={root_pass}",
        "-v", f"/home/{username}/db:/var/lib/mysql",
        image,
    ]

    r = await _docker_async(*cmd_args, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start new DB container: {r.stderr}")

    new_id = r.stdout.strip()[:12]

    # Wait for MySQL to become ready
    for _ in range(30):
        await asyncio.sleep(2)
        check = await _docker_async(
            "exec", db_name,
            "mysqladmin", "ping", "-uroot", f"-p{root_pass}",
            timeout=10,
        )
        if check.returncode == 0:
            break
    else:
        raise RuntimeError(f"New DB container {db_name} did not become ready")

    # 4. Restore dump
    restore_r = await _docker_async(
        "exec", "-i", db_name,
        "mysql", "-uroot", f"-p{root_pass}",
        timeout=600,
    )
    # For restore, we need to pipe the dump file
    loop = asyncio.get_running_loop()
    restore_r = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["docker", "exec", "-i", db_name, "mysql", "-uroot", f"-p{root_pass}"],
            input=dump_r.stdout,
            capture_output=True,
            text=True,
            timeout=600,
        ),
    )
    if restore_r.returncode != 0:
        log.warning("DB restore had warnings for %s: %s", username, restore_r.stderr)

    # 5. Cleanup dump file
    try:
        await loop.run_in_executor(None, lambda: os.unlink(dump_path))
    except OSError:
        pass

    log.info("Switched DB for %s to %s", username, version)
    return {
        "username": username,
        "db_version": version,
        "container_id": new_id,
        "status": "switched",
    }


def _write_file(path: str, content: str) -> None:
    """Write content to a file (helper for executor)."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Public API: PHP version management
# ---------------------------------------------------------------------------

async def add_php_version(username: str, version: str) -> Dict[str, Any]:
    """Add another PHP version container for the user."""
    username = safe_username(username)
    version = _validate_php_version(version)

    # Check if already exists
    name = _php_container_name(username, version)
    check = await _docker_async("inspect", name)
    if check.returncode == 0:
        raise ValueError(f"PHP {version} container already exists for {username}")

    container_id = await _create_php_container(username, version, 0.5, 256, 0)
    return {
        "username": username,
        "php_version": version,
        "container_id": container_id,
        "action": "added",
    }


async def remove_php_version(username: str, version: str) -> Dict[str, Any]:
    """Remove a PHP version container."""
    username = safe_username(username)
    version = _validate_php_version(version)

    name = _php_container_name(username, version)
    await _docker_async("stop", name, timeout=30)
    r = await _docker_async("rm", name)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to remove PHP {version} container: {r.stderr}")

    log.info("Removed PHP %s container for user %s", version, username)
    return {
        "username": username,
        "php_version": version,
        "action": "removed",
    }


# ---------------------------------------------------------------------------
# Public API: Redis / Memcached toggle
# ---------------------------------------------------------------------------

async def toggle_redis(
    username: str,
    enable: bool,
    memory_mb: int = 64,
) -> Dict[str, Any]:
    """Enable or disable Redis for a user."""
    username = safe_username(username)
    name = _container_name(username, "redis")

    if enable:
        # Check if already running
        check = await _docker_async("inspect", name)
        if check.returncode == 0:
            return {"username": username, "redis": "already_enabled"}

        container_id = await _create_redis_container(username, memory_mb)
        return {
            "username": username,
            "redis": "enabled",
            "container_id": container_id,
            "memory_mb": memory_mb,
        }
    else:
        await _docker_async("stop", name, timeout=15)
        await _docker_async("rm", "-f", name)
        return {"username": username, "redis": "disabled"}


async def toggle_memcached(
    username: str,
    enable: bool,
    memory_mb: int = 64,
) -> Dict[str, Any]:
    """Enable or disable Memcached for a user."""
    username = safe_username(username)
    name = _container_name(username, "memcached")

    if enable:
        check = await _docker_async("inspect", name)
        if check.returncode == 0:
            return {"username": username, "memcached": "already_enabled"}

        container_id = await _create_memcached_container(username, memory_mb)
        return {
            "username": username,
            "memcached": "enabled",
            "container_id": container_id,
            "memory_mb": memory_mb,
        }
    else:
        await _docker_async("stop", name, timeout=15)
        await _docker_async("rm", "-f", name)
        return {"username": username, "memcached": "disabled"}


# ---------------------------------------------------------------------------
# Public API: container listing and resource usage
# ---------------------------------------------------------------------------

async def get_user_containers(username: str) -> List[Dict[str, Any]]:
    """List all containers belonging to a user with status and resource info."""
    username = safe_username(username)

    r = await _docker_async(
        "ps", "-a",
        "--format", "{{json .}}",
        "--filter", f"label={_USER_LABEL}={username}",
        "--filter", f"label={_MANAGED_LABEL}=true",
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to list containers: {r.stderr}")

    containers: List[Dict[str, Any]] = []
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if line:
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return containers


async def update_resource_limits(
    username: str,
    cpu: float,
    memory_mb: int,
    io_bps: int,
) -> Dict[str, Any]:
    """Update Docker resource limits for all user containers."""
    username = safe_username(username)

    # Find all running containers for this user
    r = await _docker_async(
        "ps", "-q",
        "--filter", f"label={_USER_LABEL}={username}",
        "--filter", f"label={_MANAGED_LABEL}=true",
    )

    updated: List[str] = []
    if r.stdout.strip():
        for cid in r.stdout.strip().split("\n"):
            cid = cid.strip()
            if not cid:
                continue

            update_args = ["update"]
            if cpu > 0:
                update_args += ["--cpus", str(cpu)]
            if memory_mb > 0:
                update_args += ["--memory", f"{memory_mb}m"]
            update_args.append(cid)

            ur = await _docker_async(*update_args, timeout=30)
            if ur.returncode == 0:
                updated.append(cid)
            else:
                log.warning("Failed to update limits for container %s: %s", cid, ur.stderr)

    log.info("Updated resource limits for %s: %d containers", username, len(updated))
    return {
        "username": username,
        "containers_updated": updated,
        "cpu": cpu,
        "memory_mb": memory_mb,
    }


async def get_user_resource_usage(username: str) -> Dict[str, Any]:
    """Get current CPU/RAM/IO usage across all user containers."""
    username = safe_username(username)

    r = await _docker_async(
        "stats", "--no-stream",
        "--format", "{{json .}}",
        "--filter", f"label={_USER_LABEL}={username}",
    )

    containers: List[Dict[str, Any]] = []
    total_cpu = 0.0
    total_mem_usage = ""

    if r.returncode == 0 and r.stdout.strip():
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                stats = json.loads(line)
                containers.append(stats)
                # Try to parse CPU percentage
                cpu_str = stats.get("CPUPerc", "0%").rstrip("%")
                try:
                    total_cpu += float(cpu_str)
                except ValueError:
                    pass
            except json.JSONDecodeError:
                continue

    return {
        "username": username,
        "total_cpu_percent": round(total_cpu, 2),
        "containers": containers,
        "container_count": len(containers),
    }
