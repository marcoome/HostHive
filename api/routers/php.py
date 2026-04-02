"""PHP version and configuration management router -- /api/v1/php.

Manages PHP installations, php.ini configuration, and extensions on Debian 12.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.core.security import get_current_user
from api.models.users import User

router = APIRouter()
logger = logging.getLogger(__name__)

PHP_ETC_BASE = Path("/etc/php")

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
# Helpers
# ---------------------------------------------------------------------------
async def _run(cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "Command timed out"
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


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
                value = value[:value.index(";")].strip()
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
    """List all installed PHP versions with their status."""
    _require_admin(current_user)

    versions: list[dict[str, Any]] = []

    if not PHP_ETC_BASE.exists():
        return {"versions": []}

    for entry in sorted(PHP_ETC_BASE.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if not re.match(r"^\d+\.\d+$", name):
            continue

        # Check FPM service status
        rc, out, _ = await _run(f"systemctl is-active php{name}-fpm")
        fpm_active = out.strip() == "active"

        # Get full version string
        rc2, ver_out, _ = await _run(f"php{name} -v 2>/dev/null")
        full_version = ver_out.split("\n")[0] if ver_out else f"PHP {name}"

        # Check installed SAPIs
        sapis = [d.name for d in entry.iterdir() if d.is_dir()]

        versions.append({
            "version": name,
            "full_version": full_version,
            "fpm_active": fpm_active,
            "sapis": sapis,
            "config_path": str(entry),
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
    content = ini_path.read_text(encoding="utf-8")
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
    content = ini_path.read_text(encoding="utf-8")

    # Create backup
    backup_path = ini_path.with_suffix(f".ini.bak.hosthive")
    backup_path.write_text(content, encoding="utf-8")

    new_content = _update_php_ini(content, body.directives)
    ini_path.write_text(new_content, encoding="utf-8")

    # Reload PHP-FPM if editing fpm config
    warnings: list[str] = []
    if body.sapi == "fpm":
        rc, _, err = await _run(f"systemctl reload php{version}-fpm")
        if rc != 0:
            warnings.append(f"PHP-FPM reload failed: {err}")

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
    """List installed PHP extensions for a given version."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    rc, out, err = await _run(f"php{version} -m 2>/dev/null")
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
    mods_dir = PHP_ETC_BASE / version / "mods-available"
    available: list[str] = []
    if mods_dir.exists():
        available = sorted(
            f.stem for f in mods_dir.iterdir() if f.suffix == ".ini"
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
    """Enable or disable a PHP extension using phpenmod/phpdismod."""
    _require_admin(current_user)
    version = _validate_php_version(version)

    # Sanitise extension name
    ext_name = re.sub(r"[^a-zA-Z0-9_-]", "", body.name)
    if not ext_name:
        raise HTTPException(status_code=400, detail="Invalid extension name.")

    if body.enable:
        sapi_flag = f"-s {body.sapi}" if body.sapi else ""
        cmd = f"phpenmod -v {version} {sapi_flag} {ext_name}"
        action = "enabled"
    else:
        sapi_flag = f"-s {body.sapi}" if body.sapi else ""
        cmd = f"phpdismod -v {version} {sapi_flag} {ext_name}"
        action = "disabled"

    rc, out, err = await _run(cmd)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to {action.rstrip('d')} extension {ext_name}: {err or out}",
        )

    # Reload PHP-FPM
    warnings: list[str] = []
    rc2, _, err2 = await _run(f"systemctl reload php{version}-fpm")
    if rc2 != 0:
        warnings.append(f"PHP-FPM reload failed: {err2}")

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

    This is a long-running operation.
    """
    _require_admin(current_user)
    version = _validate_php_version(version)

    # Check if already installed
    if (PHP_ETC_BASE / version).exists():
        raise HTTPException(
            status_code=409,
            detail=f"PHP {version} is already installed.",
        )

    extensions = body.extensions if body else [
        "common", "cli", "fpm", "mysql", "pgsql", "sqlite3", "curl",
        "gd", "mbstring", "xml", "zip", "bcmath", "intl", "soap",
        "redis", "imagick", "opcache",
    ]

    # Build package list
    packages = [f"php{version}-{ext}" for ext in extensions]
    # Always include the base package
    packages.insert(0, f"php{version}")
    packages_str = " ".join(packages)

    # Ensure the Sury PHP repository is available
    rc, _, _ = await _run("test -f /etc/apt/sources.list.d/php.list || test -f /etc/apt/sources.list.d/sury-php.list")
    if rc != 0:
        logger.info("Adding Sury PHP repository...")
        setup_cmds = [
            "apt-get update -qq",
            "apt-get install -y -qq apt-transport-https lsb-release ca-certificates curl",
            "curl -sSL https://packages.sury.org/php/apt.gpg -o /etc/apt/trusted.gpg.d/php.gpg",
            'echo "deb https://packages.sury.org/php/ $(lsb_release -sc) main" > /etc/apt/sources.list.d/sury-php.list',
            "apt-get update -qq",
        ]
        for cmd in setup_cmds:
            rc, _, err = await _run(cmd, timeout=120)
            if rc != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to set up Sury repository: {err}",
                )

    # Install packages
    logger.info("Installing PHP %s: %s", version, packages_str)
    rc, out, err = await _run(
        f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {packages_str}",
        timeout=300,
    )
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"PHP {version} installation failed: {err or out}",
        )

    # Enable and start PHP-FPM
    warnings: list[str] = []
    rc2, _, err2 = await _run(f"systemctl enable php{version}-fpm && systemctl start php{version}-fpm")
    if rc2 != 0:
        warnings.append(f"PHP-FPM start failed: {err2}")

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

    if not (PHP_ETC_BASE / version).exists():
        raise HTTPException(status_code=404, detail=f"PHP {version} is not installed.")

    # Safety: don't remove the last version
    installed = [
        d.name for d in PHP_ETC_BASE.iterdir()
        if d.is_dir() and re.match(r"^\d+\.\d+$", d.name)
    ]
    if len(installed) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the last installed PHP version.",
        )

    # Stop FPM
    await _run(f"systemctl stop php{version}-fpm")
    await _run(f"systemctl disable php{version}-fpm")

    # Purge packages
    rc, out, err = await _run(
        f"DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq 'php{version}-*'",
        timeout=120,
    )
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

    rc, out, _ = await _run(f"systemctl is-active php{version}-fpm")
    active = out.strip() == "active"

    # List pool configs
    pool_dir = PHP_ETC_BASE / version / "fpm" / "pool.d"
    pools: list[dict[str, str]] = []
    if pool_dir.exists():
        for conf in sorted(pool_dir.iterdir()):
            if conf.suffix == ".conf":
                pools.append({
                    "name": conf.stem,
                    "path": str(conf),
                })

    # Get process count
    rc2, ps_out, _ = await _run(f"pgrep -c -f 'php-fpm: pool' 2>/dev/null || echo 0")
    process_count = int(ps_out.strip()) if ps_out.strip().isdigit() else 0

    return {
        "version": version,
        "fpm_active": active,
        "pools": pools,
        "process_count": process_count,
    }
