"""PHP version and configuration management router -- /api/v1/php.

Manages PHP installations, php.ini configuration, and extensions on Debian 12.

This router executes PHP management commands directly via subprocess
(phpenmod, phpdismod, php -m, systemctl, apt-get) on the local host.
It does NOT proxy to any external agent. All blocking calls are dispatched
through asyncio.get_running_loop().run_in_executor() so the event loop
remains responsive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.core.security import get_current_user
from api.models.users import User

router = APIRouter()
logger = logging.getLogger(__name__)

PHP_ETC_BASE = Path("/etc/php")
PHP_ETC_BASE_STR = "/etc/php/"

# Allowed PHP config directives that users may update (whitelist approach)
SAFE_PHP_DIRECTIVES = {
    "memory_limit",
    "upload_max_filesize",
    "post_max_size",
    "max_execution_time",
    "max_input_time",
    "max_input_vars",
    "date.timezone",
    "display_errors",
    "error_reporting",
    "log_errors",
    "session.gc_maxlifetime",
    "session.cookie_lifetime",
    "opcache.enable",
    "opcache.memory_consumption",
    "opcache.interned_strings_buffer",
    "opcache.max_accelerated_files",
    "opcache.revalidate_freq",
    "opcache.validate_timestamps",
    "short_open_tag",
    "file_uploads",
    "allow_url_fopen",
    "allow_url_include",
    "realpath_cache_size",
    "realpath_cache_ttl",
    "output_buffering",
    "zlib.output_compression",
    "expose_php",
    "disable_functions",
}


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


# ---------------------------------------------------------------------------
# Subprocess helpers (direct local execution, no agent proxy)
# ---------------------------------------------------------------------------
def _run_blocking(argv: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Synchronously run a command with arg list (no shell). Returns (rc, stdout, stderr).

    Intended to be wrapped by asyncio.get_running_loop().run_in_executor().
    """
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s: {' '.join(argv)}"
    except FileNotFoundError as exc:
        return 127, "", f"Executable not found: {exc}"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"Subprocess error: {exc}"


async def _run(argv: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a command directly on this host via subprocess in a worker thread.

    Uses an explicit argv list (no shell interpolation) and dispatches the
    blocking call onto the default executor so the asyncio event loop is
    not blocked.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_blocking, argv, timeout)


async def _run_in_executor(func, *args):
    """Generic wrapper to run any blocking callable in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


def _validate_php_version(version: str) -> str:
    """Ensure version string looks like '8.2', '8.3', '7.4', etc."""
    if not re.match(r"^\d+\.\d+$", version):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid PHP version format: {version}. Expected e.g. '8.2'.",
        )
    return version


def _get_php_ini_path(version: str, sapi: str = "fpm") -> Path:
    """Return the path to php.ini for a given version and SAPI."""
    path = PHP_ETC_BASE / version / sapi / "php.ini"
    if not path.exists():
        # Try cli as fallback
        alt = PHP_ETC_BASE / version / "cli" / "php.ini"
        if alt.exists():
            return alt
        raise HTTPException(
            status_code=404,
            detail=f"php.ini not found for PHP {version} ({sapi}). Path: {path}",
        )
    return path


def _parse_php_ini(content: str) -> dict[str, str]:
    """Parse php.ini content into a flat dict of directive -> value."""
    directives: dict[str, str] = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("["):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().rstrip(";").strip()
            # Strip inline comments
            if ";" in value:
                value = value[: value.index(";")].strip()
            directives[key] = value
    return directives


def _update_php_ini(content: str, updates: dict[str, str]) -> str:
    """Update directives in php.ini content. Uncomments lines if necessary."""
    lines = content.split("\n")
    updated_keys: set[str] = set()

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Match both active and commented-out directives
        for key, value in updates.items():
            # Active directive
            pattern_active = re.compile(rf"^\s*{re.escape(key)}\s*=")
            # Commented directive
            pattern_commented = re.compile(rf"^\s*;\s*{re.escape(key)}\s*=")

            if pattern_active.match(stripped):
                lines[i] = f"{key} = {value}"
                updated_keys.add(key)
                break
            elif pattern_commented.match(stripped) and key not in updated_keys:
                lines[i] = f"{key} = {value}"
                updated_keys.add(key)
                break

    # Append any directives that were not found
    for key, value in updates.items():
        if key not in updated_keys:
            lines.append(f"{key} = {value}")

    return "\n".join(lines)


def _list_php_versions_blocking() -> list[str]:
    """List PHP version directories under /etc/php/ using os.listdir.

    Returns sorted version strings like ['7.4', '8.1', '8.2', '8.3'].
    """
    if not os.path.isdir(PHP_ETC_BASE_STR):
        return []
    entries = os.listdir(PHP_ETC_BASE_STR)
    versions = [
        name for name in entries
        if re.match(r"^\d+\.\d+$", name)
        and os.path.isdir(os.path.join(PHP_ETC_BASE_STR, name))
    ]
    return sorted(versions)


def _list_dir_blocking(path: str) -> list[str]:
    """Return entries in a directory, or [] if it does not exist."""
    if not os.path.isdir(path):
        return []
    return os.listdir(path)


def _read_text_blocking(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write_text_blocking(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class PhpConfigUpdate(BaseModel):
    directives: dict[str, str] = Field(
        ...,
        description="Map of php.ini directive names to values.",
        json_schema_extra={"example": {"memory_limit": "512M", "upload_max_filesize": "128M"}},
    )
    sapi: str = Field(default="fpm", description="SAPI context: fpm, cli, or apache2")


class PhpExtensionToggle(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="Extension name, e.g. 'redis'")
    enable: bool = Field(default=True, description="True to enable, False to disable")
    sapi: Optional[str] = Field(default=None, description="Restrict to a SAPI (fpm, cli, apache2). None = all SAPIs.")


class PhpInstallRequest(BaseModel):
    version: str = Field(..., pattern=r"^\d+\.\d+$", description="PHP version, e.g. '8.3'")
    extensions: list[str] = Field(
        default=[
            "common", "cli", "fpm", "mysql", "pgsql", "sqlite3", "curl",
            "gd", "mbstring", "xml", "zip", "bcmath", "intl", "soap",
            "redis", "imagick", "opcache",
        ],
        description="Extensions to install alongside.",
    )


# ---------------------------------------------------------------------------
# GET /versions -- list installed PHP versions
# ---------------------------------------------------------------------------
@router.get("/versions")
async def list_php_versions(
    current_user: User = Depends(get_current_user),
):
    """List all installed PHP versions with their status.

    Discovery is performed by listing /etc/php/ via os.listdir, executed
    in a worker thread to avoid blocking the event loop.
    """
    _require_admin(current_user)

    version_names = await _run_in_executor(_list_php_versions_blocking)
    if not version_names:
        return {"versions": []}

    versions: list[dict[str, Any]] = []
    for name in version_names:
        # Check FPM service status via direct systemctl call
        _, out, _ = await _run(["systemctl", "is-active", f"php{name}-fpm"])
        fpm_active = out.strip() == "active"

        # Get full version string via direct php<ver> -v call
        _, ver_out, _ = await _run([f"php{name}", "-v"])
        full_version = ver_out.split("\n")[0] if ver_out else f"PHP {name}"

        # Check installed SAPIs by listing /etc/php/<ver>/
        sapi_entries = await _run_in_executor(_list_dir_blocking, str(PHP_ETC_BASE / name))
        sapis = sorted(
            d for d in sapi_entries
            if os.path.isdir(os.path.join(PHP_ETC_BASE_STR, name, d))
        )

        versions.append({
            "version": name,
            "full_version": full_version,
            "fpm_active": fpm_active,
            "sapis": sapis,
            "config_path": str(PHP_ETC_BASE / name),
        })

    return {"versions": versions}


# ---------------------------------------------------------------------------
# GET /{version}/config -- get php.ini settings
# ---------------------------------------------------------------------------
@router.get("/{version}/config")
async def get_php_config(
    version: str,
    sapi: str = Query(default="fpm", description="SAPI context: fpm, cli, apache2"),
    current_user: User = Depends(get_current_user),
):
    """Return the parsed php.ini configuration for a given version and SAPI."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    ini_path = _get_php_ini_path(version, sapi)
    content = await _run_in_executor(_read_text_blocking, str(ini_path))
    directives = _parse_php_ini(content)

    # Return only the commonly interesting directives plus full dump
    common_keys = [
        "memory_limit", "upload_max_filesize", "post_max_size",
        "max_execution_time", "max_input_time", "max_input_vars",
        "display_errors", "error_reporting", "log_errors",
        "date.timezone", "short_open_tag", "expose_php",
        "disable_functions", "file_uploads",
        "opcache.enable", "opcache.memory_consumption",
    ]
    common = {k: directives.get(k, "") for k in common_keys if k in directives}

    return {
        "version": version,
        "sapi": sapi,
        "ini_path": str(ini_path),
        "common": common,
        "all_directives": directives,
    }


# ---------------------------------------------------------------------------
# PUT /{version}/config -- update php.ini settings
# ---------------------------------------------------------------------------
@router.put("/{version}/config")
async def update_php_config(
    version: str,
    body: PhpConfigUpdate,
    current_user: User = Depends(get_current_user),
):
    """Update php.ini directives for a given PHP version and SAPI.

    Only whitelisted directives may be updated for safety.
    """
    _require_admin(current_user)
    version = _validate_php_version(version)

    # Validate directives against whitelist
    disallowed = set(body.directives.keys()) - SAFE_PHP_DIRECTIVES
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsafe or unknown directives: {', '.join(sorted(disallowed))}. "
                   f"Allowed: {', '.join(sorted(SAFE_PHP_DIRECTIVES))}",
        )

    ini_path = _get_php_ini_path(version, body.sapi)
    content = await _run_in_executor(_read_text_blocking, str(ini_path))

    # Create backup
    backup_path = ini_path.with_suffix(".ini.bak.hosthive")
    await _run_in_executor(_write_text_blocking, str(backup_path), content)

    new_content = _update_php_ini(content, body.directives)
    await _run_in_executor(_write_text_blocking, str(ini_path), new_content)

    # Restart PHP-FPM if editing fpm config (direct systemctl call)
    warnings: list[str] = []
    if body.sapi == "fpm":
        rc, _, err = await _run(["systemctl", "restart", f"php{version}-fpm"])
        if rc != 0:
            warnings.append(f"PHP-FPM restart failed: {err}")

    logger.info(
        "PHP %s %s config updated by %s: %s",
        version, body.sapi, current_user.username, list(body.directives.keys()),
    )

    return {
        "detail": f"PHP {version} ({body.sapi}) configuration updated.",
        "updated_directives": body.directives,
        "ini_path": str(ini_path),
        "backup_path": str(backup_path),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# GET /{version}/extensions -- list extensions
# ---------------------------------------------------------------------------
@router.get("/{version}/extensions")
async def list_php_extensions(
    version: str,
    current_user: User = Depends(get_current_user),
):
    """List installed PHP extensions for a given version using `php<ver> -m`."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    rc, out, err = await _run([f"php{version}", "-m"])
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Failed to list extensions: {err or out}")

    # Parse module list (sections separated by [section_name])
    modules: dict[str, list[str]] = {"core": [], "additional": []}
    current_section = "core"
    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("["):
            section_name = line.strip("[]").lower()
            if "zend" in section_name:
                current_section = "zend"
            else:
                current_section = "additional"
            modules.setdefault(current_section, [])
            continue
        modules.setdefault(current_section, []).append(line)

    # Also check available .ini files in mods-available
    mods_dir_str = str(PHP_ETC_BASE / version / "mods-available")
    mods_entries = await _run_in_executor(_list_dir_blocking, mods_dir_str)
    available = sorted(
        os.path.splitext(name)[0]
        for name in mods_entries
        if name.endswith(".ini")
    )

    return {
        "version": version,
        "loaded": modules,
        "available": available,
        "total_loaded": sum(len(v) for v in modules.values()),
        "total_available": len(available),
    }


# ---------------------------------------------------------------------------
# POST /{version}/extensions -- enable/disable an extension
# ---------------------------------------------------------------------------
@router.post("/{version}/extensions")
async def toggle_php_extension(
    version: str,
    body: PhpExtensionToggle,
    current_user: User = Depends(get_current_user),
):
    """Enable or disable a PHP extension using phpenmod/phpdismod directly."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    # Sanitise extension name
    ext_name = re.sub(r"[^a-zA-Z0-9_-]", "", body.name)
    if not ext_name:
        raise HTTPException(status_code=400, detail="Invalid extension name.")

    # Optional SAPI restriction must also be sanitised
    sapi: Optional[str] = None
    if body.sapi:
        if not re.match(r"^[a-zA-Z0-9_-]+$", body.sapi):
            raise HTTPException(status_code=400, detail="Invalid SAPI name.")
        sapi = body.sapi

    if body.enable:
        argv = ["phpenmod", "-v", version]
        action = "enabled"
    else:
        argv = ["phpdismod", "-v", version]
        action = "disabled"

    if sapi:
        argv += ["-s", sapi]
    argv.append(ext_name)

    rc, out, err = await _run(argv)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to {action.rstrip('d')} extension {ext_name}: {err or out}",
        )

    # Restart PHP-FPM (direct systemctl call)
    warnings: list[str] = []
    rc2, _, err2 = await _run(["systemctl", "restart", f"php{version}-fpm"])
    if rc2 != 0:
        warnings.append(f"PHP-FPM restart failed: {err2}")

    logger.info(
        "PHP %s extension '%s' %s by %s", version, ext_name, action, current_user.username,
    )

    return {
        "detail": f"Extension '{ext_name}' {action} for PHP {version}.",
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# POST /install/{version} -- install new PHP version
# ---------------------------------------------------------------------------
@router.post("/install/{version}")
async def install_php_version(
    version: str,
    body: PhpInstallRequest = None,
    current_user: User = Depends(get_current_user),
):
    """Install a new PHP version with common extensions from the Sury repository.

    This is a long-running operation executed via direct apt-get subprocess
    calls (no agent proxy). All blocking work is dispatched to the default
    executor.
    """
    _require_admin(current_user)
    version = _validate_php_version(version)

    # Check if already installed via os.path.isdir on /etc/php/<ver>
    already_installed = await _run_in_executor(
        os.path.isdir, os.path.join(PHP_ETC_BASE_STR, version)
    )
    if already_installed:
        raise HTTPException(
            status_code=409,
            detail=f"PHP {version} is already installed.",
        )

    extensions = body.extensions if body else [
        "common", "cli", "fpm", "mysql", "pgsql", "sqlite3", "curl",
        "gd", "mbstring", "xml", "zip", "bcmath", "intl", "soap",
        "redis", "imagick", "opcache",
    ]

    # Sanitise extension names so they can never inject extra apt args
    safe_extensions: list[str] = []
    for ext in extensions:
        if not re.match(r"^[a-zA-Z0-9_+-]+$", ext):
            raise HTTPException(status_code=400, detail=f"Invalid extension name: {ext}")
        safe_extensions.append(ext)

    # Build package list
    packages = [f"php{version}"] + [f"php{version}-{ext}" for ext in safe_extensions]

    # Ensure the Sury PHP repository is available
    sury_present = await _run_in_executor(
        os.path.exists, "/etc/apt/sources.list.d/sury-php.list"
    )
    php_list_present = await _run_in_executor(
        os.path.exists, "/etc/apt/sources.list.d/php.list"
    )
    if not (sury_present or php_list_present):
        logger.info("Adding Sury PHP repository...")
        # Each step issued as a direct subprocess call
        rc, _, err = await _run(["apt-get", "update", "-qq"], timeout=120)
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"apt-get update failed: {err}")

        rc, _, err = await _run(
            ["apt-get", "install", "-y", "-qq",
             "apt-transport-https", "lsb-release", "ca-certificates", "curl"],
            timeout=180,
        )
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"apt-get install prereqs failed: {err}")

        rc, _, err = await _run(
            ["curl", "-sSL", "https://packages.sury.org/php/apt.gpg",
             "-o", "/etc/apt/trusted.gpg.d/php.gpg"],
            timeout=60,
        )
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"Sury GPG fetch failed: {err}")

        # lsb_release -sc to discover codename
        rc, codename, err = await _run(["lsb_release", "-sc"], timeout=10)
        if rc != 0 or not codename:
            raise HTTPException(status_code=500, detail=f"lsb_release failed: {err}")
        codename = codename.strip()
        if not re.match(r"^[a-z]+$", codename):
            raise HTTPException(status_code=500, detail=f"Unexpected codename: {codename}")

        sury_line = f"deb https://packages.sury.org/php/ {codename} main\n"
        await _run_in_executor(
            _write_text_blocking, "/etc/apt/sources.list.d/sury-php.list", sury_line
        )

        rc, _, err = await _run(["apt-get", "update", "-qq"], timeout=120)
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"apt-get update (post-Sury) failed: {err}")

    # Install packages -- direct subprocess call, env via subprocess.run
    logger.info("Installing PHP %s: %s", version, " ".join(packages))

    def _install_packages_blocking() -> tuple[int, str, str]:
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        try:
            proc = subprocess.run(
                ["apt-get", "install", "-y", "-qq", *packages],
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
                check=False,
            )
            return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return 1, "", "apt-get install timed out"

    rc, out, err = await _run_in_executor(_install_packages_blocking)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"PHP {version} installation failed: {err or out}",
        )

    # Enable and start PHP-FPM via direct systemctl calls
    warnings: list[str] = []
    rc2, _, err2 = await _run(["systemctl", "enable", f"php{version}-fpm"])
    if rc2 != 0:
        warnings.append(f"PHP-FPM enable failed: {err2}")
    rc3, _, err3 = await _run(["systemctl", "restart", f"php{version}-fpm"])
    if rc3 != 0:
        warnings.append(f"PHP-FPM restart failed: {err3}")

    logger.info("PHP %s installed by %s", version, current_user.username)

    return {
        "detail": f"PHP {version} installed successfully.",
        "packages_installed": packages,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# DELETE /{version} -- uninstall PHP version
# ---------------------------------------------------------------------------
@router.delete("/{version}")
async def uninstall_php_version(
    version: str,
    current_user: User = Depends(get_current_user),
):
    """Uninstall a PHP version. Refuses to remove the last installed version."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    target_path = os.path.join(PHP_ETC_BASE_STR, version)
    exists = await _run_in_executor(os.path.isdir, target_path)
    if not exists:
        raise HTTPException(status_code=404, detail=f"PHP {version} is not installed.")

    # Safety: don't remove the last version (use os.listdir for discovery)
    installed = await _run_in_executor(_list_php_versions_blocking)
    if len(installed) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the last installed PHP version.",
        )

    # Stop & disable FPM via direct systemctl calls
    await _run(["systemctl", "stop", f"php{version}-fpm"])
    await _run(["systemctl", "disable", f"php{version}-fpm"])

    # Purge packages -- glob is shell-syntax so we resolve the package list first
    def _purge_blocking() -> tuple[int, str, str]:
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        # Discover installed php<ver>-* packages via dpkg-query
        try:
            list_proc = subprocess.run(
                ["dpkg-query", "-W", "-f=${Package}\n", f"php{version}-*"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 1, "", "dpkg-query timed out"

        pkgs = [
            line.strip() for line in (list_proc.stdout or "").splitlines() if line.strip()
        ]
        # Always include the base package as well
        base_pkg = f"php{version}"
        if base_pkg not in pkgs:
            pkgs.append(base_pkg)

        try:
            purge_proc = subprocess.run(
                ["apt-get", "purge", "-y", "-qq", *pkgs],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
                check=False,
            )
            return (
                purge_proc.returncode,
                (purge_proc.stdout or "").strip(),
                (purge_proc.stderr or "").strip(),
            )
        except subprocess.TimeoutExpired:
            return 1, "", "apt-get purge timed out"

    rc, out, err = await _run_in_executor(_purge_blocking)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"PHP {version} removal failed: {err or out}",
        )

    logger.info("PHP %s uninstalled by %s", version, current_user.username)
    return {"detail": f"PHP {version} uninstalled."}


# ---------------------------------------------------------------------------
# GET /{version}/fpm/status -- PHP-FPM pool status
# ---------------------------------------------------------------------------
@router.get("/{version}/fpm/status")
async def php_fpm_status(
    version: str,
    current_user: User = Depends(get_current_user),
):
    """Return PHP-FPM service and pool status for a given version."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    _, out, _ = await _run(["systemctl", "is-active", f"php{version}-fpm"])
    active = out.strip() == "active"

    # List pool configs via os.listdir wrapped in executor
    pool_dir_str = str(PHP_ETC_BASE / version / "fpm" / "pool.d")
    pool_entries = await _run_in_executor(_list_dir_blocking, pool_dir_str)
    pools: list[dict[str, str]] = []
    for name in sorted(pool_entries):
        if name.endswith(".conf"):
            pools.append({
                "name": os.path.splitext(name)[0],
                "path": os.path.join(pool_dir_str, name),
            })

    # Get process count via direct pgrep call
    rc2, ps_out, _ = await _run(["pgrep", "-c", "-f", "php-fpm: pool"])
    process_count = int(ps_out.strip()) if ps_out.strip().isdigit() else 0

    return {
        "version": version,
        "fpm_active": active,
        "pools": pools,
        "process_count": process_count,
    }
