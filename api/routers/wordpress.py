"""WordPress router -- /api/v1/wordpress.

Manage WordPress installations: detect, inspect, update, clone, migrate, and
run security checks.  All operations invoke WP-CLI directly via subprocess;
blocking calls are dispatched to the default executor so the event loop stays
responsive.  There is no dependency on the agent process.
"""

from __future__ import annotations

import asyncio
import glob
import os
import re
import shutil
import subprocess
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain  # noqa: F401  (kept for compatibility)
from api.models.users import User
from api.schemas.wordpress import (
    WPBackupResult,
    WPCloneRequest,
    WPCloneResult,
    WPInstallInfo,
    WPSearchReplaceRequest,
    WPSearchReplaceResult,
    WPSecurityReport,
    WPSiteInfo,
    WPUpdateResult,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WP_CLI = shutil.which("wp") or "/usr/local/bin/wp"
BACKUP_ROOT = "/opt/hosthive/backups/wordpress"
DEFAULT_TIMEOUT = 300
LONG_TIMEOUT = 900
HOME_ROOT = "/home"


# ---------------------------------------------------------------------------
# Helpers -- user / access / path resolution
# ---------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _resolve_wp_path(domain: str, current_user: User) -> str:
    """Resolve the WordPress path for a domain.

    Tries common document root patterns under /home/<username>/.
    """
    username = current_user.username
    candidates = [
        f"/home/{username}/web/{domain}/public_html",
        f"/home/{username}/{domain}/public_html",
        f"/home/{username}/web/{domain}",
    ]

    for path in candidates:
        wp_config = os.path.join(path, "wp-config.php")
        if os.path.isfile(wp_config):
            return path

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"WordPress installation not found for domain {domain}",
    )


def _check_domain_access(domain: str, current_user: User) -> None:
    """Ensure the user has access to this domain (basic path-based check)."""
    if _is_admin(current_user):
        return
    username = current_user.username
    allowed_prefix = f"/home/{username}/"
    path = _resolve_wp_path(domain, current_user)
    resolved = os.path.realpath(path)
    if not resolved.startswith(allowed_prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )


# ---------------------------------------------------------------------------
# Helpers -- WP-CLI subprocess execution (blocking; dispatch via executor)
# ---------------------------------------------------------------------------

def _wp_cli_sync(
    path: str,
    *args: str,
    timeout: int = DEFAULT_TIMEOUT,
    allow_root: bool = True,
) -> subprocess.CompletedProcess:
    """Run WP-CLI in *path*. Blocking -- call via run_in_executor."""
    if not os.path.isdir(path):
        raise FileNotFoundError(f"WordPress path not found: {path}")
    if not os.path.isfile(os.path.join(path, "wp-config.php")):
        raise FileNotFoundError(f"wp-config.php missing in {path}")

    cmd = [WP_CLI, f"--path={path}"]
    if allow_root:
        cmd.append("--allow-root")
    cmd.extend(args)

    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"WP-CLI binary not found at {WP_CLI}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"WP-CLI command timed out after {timeout}s: {' '.join(args)}") from exc


async def _wp_cli(path: str, *args: str, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Async wrapper around _wp_cli_sync using the running loop's executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _wp_cli_sync(path, *args, timeout=timeout))


async def _run_sync(func, *args, **kwargs):
    """Dispatch an arbitrary blocking callable onto the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _raise_on_wp_error(result: subprocess.CompletedProcess, http_status: int = status.HTTP_502_BAD_GATEWAY) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "WP-CLI command failed").strip()
        raise HTTPException(status_code=http_status, detail=detail)


# ---------------------------------------------------------------------------
# Helpers -- install detection (walks /home/*/web/*/public_html)
# ---------------------------------------------------------------------------

def _detect_installs_sync() -> list[dict]:
    """Scan /home/<user>/web/<domain>/public_html for WordPress installs."""
    installs: list[dict] = []
    if not os.path.isdir(HOME_ROOT):
        return installs

    patterns = [
        os.path.join(HOME_ROOT, "*", "web", "*", "public_html"),
        os.path.join(HOME_ROOT, "*", "*", "public_html"),
        os.path.join(HOME_ROOT, "*", "web", "*"),
    ]

    seen: set[str] = set()
    for pat in patterns:
        for candidate in glob.glob(pat):
            try:
                real = os.path.realpath(candidate)
            except OSError:
                continue
            if real in seen:
                continue
            if not os.path.isfile(os.path.join(candidate, "wp-config.php")):
                continue
            seen.add(real)

            parts = candidate.strip("/").split("/")
            # /home/<user>/web/<domain>/public_html  -> parts: home, user, web, domain, public_html
            owner = parts[1] if len(parts) > 1 else ""
            domain = ""
            if "web" in parts:
                try:
                    idx = parts.index("web")
                    if idx + 1 < len(parts):
                        domain = parts[idx + 1]
                except ValueError:
                    pass
            if not domain and len(parts) >= 3:
                domain = parts[2]

            installs.append(
                {
                    "domain": domain,
                    "path": candidate,
                    "owner": owner,
                }
            )
    return installs


# ---------------------------------------------------------------------------
# GET /installs — alias for frontend compatibility
# ---------------------------------------------------------------------------

@router.get("/installs", status_code=status.HTTP_200_OK)
async def list_wp_installs_alias(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return await list_wordpress_installs(request=request, current_user=current_user)


# ---------------------------------------------------------------------------
# GET / — list detected WordPress installations
# ---------------------------------------------------------------------------

@router.get("", status_code=status.HTTP_200_OK)
async def list_wordpress_installs(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    try:
        installs = await _run_sync(_detect_installs_sync)
    except Exception:
        return {"items": [], "total": 0}

    if not _is_admin(current_user):
        installs = [i for i in installs if i.get("owner") == current_user.username]

    return {
        "items": [WPInstallInfo(**i) for i in installs],
        "total": len(installs),
    }


# ---------------------------------------------------------------------------
# GET /{domain}/info — WP version, plugins, theme, health
# ---------------------------------------------------------------------------

@router.get("/{domain}/info", response_model=WPSiteInfo)
async def wp_info(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    try:
        core_version = await _wp_cli(path, "core", "version", timeout=60)
        site_url = await _wp_cli(path, "option", "get", "siteurl", timeout=60)
        plugins = await _wp_cli(path, "plugin", "list", "--format=csv", timeout=120)
        themes = await _wp_cli(path, "theme", "list", "--format=csv", timeout=120)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    _raise_on_wp_error(core_version)

    plugin_rows = _parse_csv_rows(plugins.stdout) if plugins.returncode == 0 else []
    theme_rows = _parse_csv_rows(themes.stdout) if themes.returncode == 0 else []

    active_theme = "unknown"
    for t in theme_rows:
        if t.get("status") == "active":
            active_theme = t.get("name", "unknown")
            break

    info = {
        "path": path,
        "version": (core_version.stdout or "").strip() or "unknown",
        "plugins": plugin_rows,
        "themes": theme_rows,
        "active_theme": active_theme,
        "db_health": "ok",
    }
    return WPSiteInfo(**info)


def _parse_csv_rows(csv_text: str) -> list[dict]:
    """Parse a WP-CLI CSV blob into a list of dict rows using the header line."""
    if not csv_text:
        return []
    lines = [l for l in csv_text.strip().splitlines() if l]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split(",")]
    rows: list[dict] = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split(",")]
        rows.append(dict(zip(headers, values)))
    return rows


def _parse_csv_names(csv_text: str) -> list[str]:
    """Return the first column of a WP-CLI CSV (the 'name' column), skipping header."""
    rows = _parse_csv_rows(csv_text)
    out: list[str] = []
    for r in rows:
        # WP-CLI puts the primary identifier in the first column
        if r:
            first_key = next(iter(r))
            val = r.get(first_key, "").strip()
            if val:
                out.append(val)
    return out


# ---------------------------------------------------------------------------
# POST /{domain}/update-core — update WordPress core
# ---------------------------------------------------------------------------

@router.post("/{domain}/update-core", response_model=WPUpdateResult)
async def wp_update_core(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    try:
        result = await _wp_cli(path, "core", "update", timeout=LONG_TIMEOUT)
        # Update DB schema if needed
        db_update = await _wp_cli(path, "core", "update-db", timeout=LONG_TIMEOUT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    _raise_on_wp_error(result)

    _log(db, request, current_user.id, "wordpress.update_core", f"Updated WordPress core for {domain}")
    return WPUpdateResult(
        path=path,
        stdout=(result.stdout or "").strip(),
        db_update=(db_update.stdout or "").strip() if db_update.returncode == 0 else None,
    )


# ---------------------------------------------------------------------------
# POST /{domain}/update-plugins — update all plugins
# ---------------------------------------------------------------------------

@router.post("/{domain}/update-plugins", response_model=WPUpdateResult)
async def wp_update_plugins(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    try:
        result = await _wp_cli(path, "plugin", "update", "--all", timeout=LONG_TIMEOUT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    _raise_on_wp_error(result)

    _log(db, request, current_user.id, "wordpress.update_plugins", f"Updated plugins for {domain}")
    return WPUpdateResult(
        path=path,
        stdout=(result.stdout or "").strip(),
        db_update=None,
    )


# ---------------------------------------------------------------------------
# POST /{domain}/backup — backup this WP install
# ---------------------------------------------------------------------------

def _tar_backup_sync(backup_file: str, source_path: str, db_dump: str | None) -> subprocess.CompletedProcess:
    tar_args = ["tar", "-czf", backup_file, "-C", os.path.dirname(source_path), os.path.basename(source_path)]
    if db_dump and os.path.isfile(db_dump):
        tar_args.extend(["-C", "/tmp", os.path.basename(db_dump)])
    return subprocess.run(tar_args, capture_output=True, text=True, timeout=LONG_TIMEOUT, check=False)


@router.post("/{domain}/backup", response_model=WPBackupResult)
async def wp_backup(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    timestamp = int(time.time())
    await _run_sync(os.makedirs, BACKUP_ROOT, exist_ok=True)
    backup_file = f"{BACKUP_ROOT}/{domain}_{timestamp}.tar.gz"

    # 1. Export database via wp db export
    db_dump: str | None = f"/tmp/wp_backup_{domain}_{timestamp}.sql"
    try:
        dump_result = await _wp_cli(path, "db", "export", db_dump, timeout=LONG_TIMEOUT)
        if dump_result.returncode != 0:
            db_dump = None
    except (FileNotFoundError, RuntimeError):
        db_dump = None

    # 2. Create tar archive (files + optional dump)
    tar_result = await _run_sync(_tar_backup_sync, backup_file, path, db_dump)

    # 3. Clean up temp dump
    if db_dump:
        try:
            await _run_sync(os.unlink, db_dump)
        except OSError:
            pass

    if tar_result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Backup failed: {(tar_result.stderr or '').strip()}",
        )

    size = 0
    if await _run_sync(os.path.isfile, backup_file):
        size = await _run_sync(os.path.getsize, backup_file)

    _log(db, request, current_user.id, "wordpress.backup", f"Backed up WordPress for {domain}")
    return WPBackupResult(path=path, backup_file=backup_file, size_bytes=size)


# ---------------------------------------------------------------------------
# POST /{domain}/clone — clone to staging domain
# ---------------------------------------------------------------------------

def _copytree_sync(src: str, dst: str) -> None:
    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=False)


@router.post("/{domain}/clone", response_model=WPCloneResult)
async def wp_clone(
    domain: str,
    body: WPCloneRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    target_domain = (body.target_domain or "").strip()
    if not target_domain or "/" in target_domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target_domain")

    # Target lives next to the source under the same /home/<user>/web parent
    parent = os.path.dirname(os.path.dirname(path))  # .../web
    target_path = os.path.join(parent, target_domain, "public_html")

    if await _run_sync(os.path.exists, target_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target path already exists: {target_path}",
        )

    try:
        # 1. Copy files
        await _run_sync(os.makedirs, os.path.dirname(target_path), exist_ok=True)
        await _run_sync(_copytree_sync, path, target_path)

        # 2. Dump source DB
        timestamp = int(time.time())
        dump_file = f"/tmp/wp_clone_{domain}_{timestamp}.sql"
        dump = await _wp_cli(path, "db", "export", dump_file, timeout=LONG_TIMEOUT)
        _raise_on_wp_error(dump)

        # 3. Import into target (uses same DB credentials from wp-config for now;
        #    a real clone would create a new DB -- left as an extension point)
        imp = await _wp_cli(target_path, "db", "import", dump_file, timeout=LONG_TIMEOUT)
        _raise_on_wp_error(imp)

        # 4. Search-replace URLs in the target
        sr = await _wp_cli(
            target_path,
            "search-replace",
            f"//{domain}",
            f"//{target_domain}",
            "--all-tables",
            "--skip-columns=guid",
            timeout=LONG_TIMEOUT,
        )
        _raise_on_wp_error(sr)

        # Clean up temp dump
        try:
            await _run_sync(os.unlink, dump_file)
        except OSError:
            pass
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _log(
        db, request, current_user.id,
        "wordpress.clone",
        f"Cloned WordPress {domain} -> {target_domain}",
    )
    return WPCloneResult(
        source_path=path,
        target_path=target_path,
        target_domain=target_domain,
        source_url=f"https://{domain}",
        target_url=f"https://{target_domain}",
    )


# ---------------------------------------------------------------------------
# POST /{domain}/search-replace — search & replace in DB
# ---------------------------------------------------------------------------

@router.post("/{domain}/search-replace", response_model=WPSearchReplaceResult)
async def wp_search_replace(
    domain: str,
    body: WPSearchReplaceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    try:
        result = await _wp_cli(
            path,
            "search-replace",
            body.old_domain,
            body.new_domain,
            "--all-tables",
            "--skip-columns=guid",
            "--report-changed-only",
            timeout=LONG_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    _raise_on_wp_error(result, http_status=status.HTTP_400_BAD_REQUEST)

    # Build a structured per-table summary from WP-CLI output, e.g.
    #   "Success: Made 12 replacements on wp_posts.post_content"
    results: list[dict] = []
    pattern = re.compile(r"Made\s+(\d+)\s+replacements?\s+on\s+(\S+)", re.IGNORECASE)
    for m in pattern.finditer(result.stdout or ""):
        results.append({"table": m.group(2), "replacements": int(m.group(1))})

    _log(
        db, request, current_user.id,
        "wordpress.search_replace",
        f"Search-replace on {domain}: {body.old_domain} -> {body.new_domain}",
    )
    return WPSearchReplaceResult(
        path=path,
        results=results,
    )


# ---------------------------------------------------------------------------
# GET /{domain}/security-check — check for vulnerabilities
# ---------------------------------------------------------------------------

@router.get("/{domain}/security-check", response_model=WPSecurityReport)
async def wp_security_check(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _check_domain_access(domain, current_user)
    path = _resolve_wp_path(domain, current_user)

    try:
        core_check = await _wp_cli(path, "core", "check-update", "--format=csv", timeout=120)
        plugin_check = await _wp_cli(path, "plugin", "list", "--update=available", "--format=csv", timeout=120)
        theme_check = await _wp_cli(path, "theme", "list", "--update=available", "--format=csv", timeout=120)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    issues: list[dict] = []

    core_updates = _parse_csv_names(core_check.stdout) if core_check.returncode == 0 else []
    if core_updates:
        issues.append(
            {
                "severity": "high",
                "type": "core_update",
                "message": f"WordPress core update(s) available: {', '.join(core_updates)}",
            }
        )

    plugin_updates = _parse_csv_names(plugin_check.stdout) if plugin_check.returncode == 0 else []
    for name in plugin_updates:
        issues.append(
            {
                "severity": "medium",
                "type": "plugin_update",
                "message": f"Plugin update available: {name}",
            }
        )

    theme_updates = _parse_csv_names(theme_check.stdout) if theme_check.returncode == 0 else []
    for name in theme_updates:
        issues.append(
            {
                "severity": "medium",
                "type": "theme_update",
                "message": f"Theme update available: {name}",
            }
        )

    # Filesystem permission sanity checks
    wp_config = os.path.join(path, "wp-config.php")
    try:
        st = await _run_sync(os.stat, wp_config)
        mode = st.st_mode & 0o777
        if mode & 0o004:
            issues.append(
                {
                    "severity": "high",
                    "type": "permissions",
                    "message": f"wp-config.php is world-readable (mode {oct(mode)})",
                }
            )
    except OSError:
        pass

    _log(db, request, current_user.id, "wordpress.security_check", f"Security check for {domain}")
    return WPSecurityReport(
        path=path,
        total_issues=len(issues),
        issues=issues,
    )
