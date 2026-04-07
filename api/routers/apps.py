"""Apps router -- /api/v1/apps.

Deploy and manage Node.js / Python applications, plus a catalog of
popular web applications available for one-click installation.

All operations run locally via subprocess (wget, tar, composer, php,
systemctl, pm2, docker, etc.) using ``asyncio.get_running_loop().run_in_executor``
so the FastAPI event loop stays responsive. Nothing is proxied to a
remote agent on port 7080 -- this router executes commands directly on
the host where the API is running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import string
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Sequence, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.apps import App
from api.models.users import User
from api.schemas.apps import (
    AppDeployRequest,
    AppEnvUpdate,
    AppListEntry,
    AppLogsResponse,
    AppStatusResponse,
    AppStopStartResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# =========================================================================
# Subprocess helpers -- run blocking commands off the event loop
# =========================================================================

# Default subprocess timeout (seconds) so a hung command can never block
# the API event loop indefinitely.
_DEFAULT_TIMEOUT = 600

# Where logs from app installs / runtime are kept.
LOG_DIR = Path("/var/log/hosthive/apps")


def _run_sync(
    cmd: Union[str, Sequence[str]],
    *,
    shell: bool = False,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: int = _DEFAULT_TIMEOUT,
    input_data: Optional[str] = None,
) -> tuple[int, str, str]:
    """Synchronous subprocess runner -- intended for ``run_in_executor``.

    Runs the command directly via ``subprocess.run`` (no proxying through
    any agent / network service). Prefers list-form arguments to avoid
    shell injection; only falls back to ``shell=True`` when explicitly
    requested.
    """
    try:
        completed = subprocess.run(
            cmd,
            shell=shell,
            cwd=cwd,
            env=env,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"Command timed out after {timeout}s: {exc}"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except Exception as exc:  # noqa: BLE001 - surface any subprocess error
        return 1, "", str(exc)

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    return completed.returncode, stdout, stderr


async def _run(
    cmd: Union[str, Sequence[str]],
    *,
    shell: bool = False,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: int = _DEFAULT_TIMEOUT,
    input_data: Optional[str] = None,
) -> tuple[int, str, str]:
    """Run a blocking subprocess off the event loop.

    Wraps :func:`_run_sync` in
    ``asyncio.get_running_loop().run_in_executor`` so the FastAPI event
    loop stays responsive while installers (wget, tar, composer, ...)
    do their work.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_sync(
            cmd,
            shell=shell,
            cwd=cwd,
            env=env,
            timeout=timeout,
            input_data=input_data,
        ),
    )


async def _to_thread(func, *args, **kwargs):
    """Run a blocking callable in the default thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _random_token(length: int = 16) -> str:
    """Generate a URL-safe random token suitable for DB credentials."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _doc_root(username: str, domain: str, sub_path: str = "") -> Path:
    """Compute the document root for a given user/domain/sub-path."""
    base = Path(f"/home/{username}/web/{domain}/public_html")
    if sub_path:
        clean = sub_path.strip("/")
        if clean:
            base = base / clean
    return base


# =========================================================================
# App catalog -- available installable applications
# =========================================================================

class CatalogApp(BaseModel):
    slug: str
    name: str
    version: str
    description: str
    category: str
    icon: str = ""
    website: str = ""
    min_php: Optional[str] = None
    requires_database: bool = False
    database_types: list[str] = []


APP_CATALOG: list[CatalogApp] = [
    CatalogApp(
        slug="wordpress",
        name="WordPress",
        version="6.7",
        description="The world's most popular CMS powering over 40% of all websites.",
        category="CMS",
        icon="wordpress",
        website="https://wordpress.org",
        min_php="7.4",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="joomla",
        name="Joomla",
        version="5.2",
        description="Flexible CMS for building websites and powerful online applications.",
        category="CMS",
        icon="joomla",
        website="https://www.joomla.org",
        min_php="8.1",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="drupal",
        name="Drupal",
        version="11.1",
        description="Enterprise-grade CMS for ambitious digital experiences.",
        category="CMS",
        icon="drupal",
        website="https://www.drupal.org",
        min_php="8.3",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="prestashop",
        name="PrestaShop",
        version="8.2",
        description="Open-source e-commerce platform for building online stores.",
        category="E-Commerce",
        icon="prestashop",
        website="https://www.prestashop.com",
        min_php="8.1",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="opencart",
        name="OpenCart",
        version="4.1",
        description="Free and open-source online store management system.",
        category="E-Commerce",
        icon="opencart",
        website="https://www.opencart.com",
        min_php="8.0",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="magento",
        name="Magento / OpenMage",
        version="20.12",
        description="Feature-rich open-source e-commerce platform (OpenMage LTS fork).",
        category="E-Commerce",
        icon="magento",
        website="https://www.openmage.org",
        min_php="8.1",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="laravel",
        name="Laravel",
        version="12.0",
        description="Elegant PHP framework for web artisans.",
        category="Framework",
        icon="laravel",
        website="https://laravel.com",
        min_php="8.2",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="nodejs",
        name="Node.js App",
        version="22",
        description="Deploy a custom Node.js application with PM2 process manager.",
        category="Runtime",
        icon="nodejs",
        website="https://nodejs.org",
        requires_database=False,
    ),
    CatalogApp(
        slug="python-django",
        name="Python / Django",
        version="5.1",
        description="High-level Python web framework for rapid development.",
        category="Framework",
        icon="django",
        website="https://www.djangoproject.com",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="ghost",
        name="Ghost",
        version="5.100",
        description="Professional publishing platform for modern journalism and blogging.",
        category="CMS",
        icon="ghost",
        website="https://ghost.org",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="nextcloud",
        name="Nextcloud",
        version="30.0",
        description="Self-hosted productivity platform with file sync, collaboration, and more.",
        category="Productivity",
        icon="nextcloud",
        website="https://nextcloud.com",
        min_php="8.1",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="phpmyadmin",
        name="phpMyAdmin",
        version="5.2",
        description="Web-based MySQL/MariaDB database administration tool.",
        category="Tools",
        icon="phpmyadmin",
        website="https://www.phpmyadmin.net",
        min_php="8.1",
        requires_database=False,
    ),
    CatalogApp(
        slug="roundcube",
        name="Roundcube",
        version="1.6",
        description="Free and open-source browser-based IMAP email client.",
        category="Email",
        icon="roundcube",
        website="https://roundcube.net",
        min_php="8.0",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="gitea",
        name="Gitea",
        version="1.22",
        description="Lightweight self-hosted Git service, similar to GitHub.",
        category="DevOps",
        icon="gitea",
        website="https://gitea.io",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="mattermost",
        name="Mattermost",
        version="10.3",
        description="Open-source, self-hosted Slack alternative for team messaging.",
        category="Communication",
        icon="mattermost",
        website="https://mattermost.com",
        requires_database=True,
        database_types=["postgresql"],
    ),
    # --- New apps ---
    CatalogApp(
        slug="mediawiki",
        name="MediaWiki",
        version="1.42",
        description="The wiki engine that powers Wikipedia, ideal for knowledge bases.",
        category="CMS",
        icon="mediawiki",
        website="https://www.mediawiki.org",
        min_php="8.1",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="bookstack",
        name="BookStack",
        version="24.10",
        description="Simple, self-hosted wiki and documentation platform.",
        category="CMS",
        icon="bookstack",
        website="https://www.bookstackapp.com",
        min_php="8.2",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="phpbb",
        name="phpBB",
        version="3.3",
        description="Free and open-source bulletin board forum software.",
        category="Forum",
        icon="phpbb",
        website="https://www.phpbb.com",
        min_php="8.1",
        requires_database=True,
        database_types=["mysql", "postgresql"],
    ),
    CatalogApp(
        slug="discourse",
        name="Discourse",
        version="3.3",
        description="Modern, Docker-based discussion forum for civilized communities.",
        category="Forum",
        icon="discourse",
        website="https://www.discourse.org",
        requires_database=False,
    ),
    CatalogApp(
        slug="invoiceninja",
        name="Invoice Ninja",
        version="5.10",
        description="Open-source invoicing, payments, and time-tracking platform.",
        category="Productivity",
        icon="invoiceninja",
        website="https://invoiceninja.com",
        requires_database=True,
        database_types=["mysql"],
    ),
    CatalogApp(
        slug="uptimekuma",
        name="Uptime Kuma",
        version="1.23",
        description="Easy-to-use self-hosted monitoring tool with a beautiful UI.",
        category="Monitoring",
        icon="uptimekuma",
        website="https://uptime.kuma.pet",
        requires_database=False,
    ),
    CatalogApp(
        slug="grafana",
        name="Grafana",
        version="11.4",
        description="Open-source analytics and interactive visualization platform.",
        category="Monitoring",
        icon="grafana",
        website="https://grafana.com",
        requires_database=False,
    ),
    CatalogApp(
        slug="portainer",
        name="Portainer",
        version="2.21",
        description="Lightweight Docker management UI for containers and images.",
        category="DevOps",
        icon="portainer",
        website="https://www.portainer.io",
        requires_database=False,
    ),
    CatalogApp(
        slug="minio",
        name="MinIO",
        version="2024.12",
        description="High-performance S3-compatible object storage for private clouds.",
        category="DevOps",
        icon="minio",
        website="https://min.io",
        requires_database=False,
    ),
    CatalogApp(
        slug="adminer",
        name="Adminer",
        version="4.8",
        description="Full-featured database management in a single PHP file.",
        category="Tools",
        icon="adminer",
        website="https://www.adminer.org",
        min_php="8.0",
        requires_database=False,
    ),
]

_CATALOG_BY_SLUG = {app.slug: app for app in APP_CATALOG}


# Source URLs for the various installers. Centralised so it is easy to
# update versions / mirrors.
_DOWNLOAD_URLS: dict[str, str] = {
    "wordpress": "https://wordpress.org/latest.tar.gz",
    "joomla": "https://downloads.joomla.org/cms/joomla5/5-2-0/Joomla_5-2-0-Stable-Full_Package.tar.gz",
    "drupal": "https://www.drupal.org/download-latest/tar.gz",
    "prestashop": "https://github.com/PrestaShop/PrestaShop/releases/download/8.2.0/prestashop_8.2.0.zip",
    "opencart": "https://github.com/opencart/opencart/releases/download/4.1.0.0/opencart-4.1.0.0.zip",
    "magento": "https://github.com/OpenMage/magento-lts/archive/refs/heads/main.tar.gz",
    "mediawiki": "https://releases.wikimedia.org/mediawiki/1.42/mediawiki-1.42.3.tar.gz",
    "bookstack": "https://github.com/BookStackApp/BookStack/archive/refs/heads/release.tar.gz",
    "phpbb": "https://download.phpbb.com/pub/release/3.3/3.3.13/phpBB-3.3.13.tar.bz2",
    "roundcube": "https://github.com/roundcube/roundcubemail/releases/download/1.6.9/roundcubemail-1.6.9-complete.tar.gz",
    "phpmyadmin": "https://files.phpmyadmin.net/phpMyAdmin/5.2.1/phpMyAdmin-5.2.1-all-languages.tar.gz",
    "adminer": "https://github.com/vrana/adminer/releases/download/v4.8.1/adminer-4.8.1.php",
    "nextcloud": "https://download.nextcloud.com/server/releases/latest.tar.bz2",
}


class CatalogInstallRequest(BaseModel):
    """Request body for installing a catalog application."""
    slug: str = Field(..., description="Application slug from the catalog")
    domain: str = Field(..., min_length=3, max_length=255)
    path: str = Field(default="", description="Sub-path under the domain document root (optional)")
    db_name: Optional[str] = Field(default=None, description="Database name (auto-generated if omitted)")
    db_user: Optional[str] = Field(default=None, description="Database user (auto-generated if omitted)")
    db_password: Optional[str] = Field(default=None, description="Database password (auto-generated if omitted)")
    db_type: str = Field(default="mysql", description="'mysql' or 'postgresql'")
    port: Optional[int] = Field(default=None, ge=1024, le=65535, description="Port for Node.js/runtime apps")
    version: Optional[str] = Field(default=None, description="Override default version")


class CatalogInstallResponse(BaseModel):
    slug: str
    name: str
    domain: str
    status: str = "installing"
    message: str = ""
    details: dict = {}


# =========================================================================
# Installer primitives -- direct local subprocess
# =========================================================================

async def _ensure_dir(path: Path, owner: Optional[str] = None) -> None:
    """Create a directory (and parents) and optionally chown it."""
    await _to_thread(path.mkdir, parents=True, exist_ok=True)
    if owner:
        await _run(["chown", "-R", f"{owner}:{owner}", str(path)])


async def _download(url: str, dest: Path, *, timeout: int = _DEFAULT_TIMEOUT) -> None:
    """Download ``url`` to ``dest`` using wget."""
    await _ensure_dir(dest.parent)
    rc, out, err = await _run(
        ["wget", "--quiet", "--show-progress=off", "-O", str(dest), url],
        timeout=timeout,
    )
    if rc != 0:
        raise RuntimeError(f"wget failed for {url}: {err or out}")


async def _extract(archive: Path, dest: Path) -> None:
    """Extract a tar/zip archive to ``dest`` using the right tool."""
    await _ensure_dir(dest)
    name = archive.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        cmd = ["tar", "-xzf", str(archive), "-C", str(dest), "--strip-components=1"]
    elif name.endswith(".tar.bz2"):
        cmd = ["tar", "-xjf", str(archive), "-C", str(dest), "--strip-components=1"]
    elif name.endswith(".tar"):
        cmd = ["tar", "-xf", str(archive), "-C", str(dest), "--strip-components=1"]
    elif name.endswith(".zip"):
        cmd = ["unzip", "-q", "-o", str(archive), "-d", str(dest)]
    else:
        raise RuntimeError(f"Unsupported archive type: {archive.name}")

    rc, out, err = await _run(cmd)
    if rc != 0:
        raise RuntimeError(f"Extract failed for {archive.name}: {err or out}")


async def _create_mysql_database(db_name: str, db_user: str, db_password: str) -> None:
    """Create a MySQL/MariaDB database + user via the local mysql client."""
    sql = (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
        f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' "
        f"IDENTIFIED BY '{db_password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';\n"
        f"FLUSH PRIVILEGES;\n"
    )
    rc, out, err = await _run(["mysql"], input_data=sql)
    if rc != 0:
        raise RuntimeError(f"MySQL provisioning failed: {err or out}")


async def _create_postgres_database(db_name: str, db_user: str, db_password: str) -> None:
    """Create a PostgreSQL database + user via psql as the postgres user."""
    sql = (
        f"CREATE USER \"{db_user}\" WITH PASSWORD '{db_password}';\n"
        f"CREATE DATABASE \"{db_name}\" OWNER \"{db_user}\";\n"
        f"GRANT ALL PRIVILEGES ON DATABASE \"{db_name}\" TO \"{db_user}\";\n"
    )
    rc, out, err = await _run(
        ["sudo", "-u", "postgres", "psql"],
        input_data=sql,
    )
    if rc != 0:
        raise RuntimeError(f"PostgreSQL provisioning failed: {err or out}")


async def _provision_db(
    db_type: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> None:
    if db_type == "mysql":
        await _create_mysql_database(db_name, db_user, db_password)
    elif db_type == "postgresql":
        await _create_postgres_database(db_name, db_user, db_password)
    else:
        raise RuntimeError(f"Unsupported db_type: {db_type}")


async def _composer_install(project_dir: Path, owner: str) -> None:
    """Run ``composer install`` in the given project directory."""
    rc, out, err = await _run(
        ["sudo", "-u", owner, "composer", "install", "--no-dev", "--optimize-autoloader"],
        cwd=str(project_dir),
        timeout=900,
    )
    if rc != 0:
        raise RuntimeError(f"composer install failed: {err or out}")


# =========================================================================
# High-level installer dispatch
# =========================================================================

async def _install_php_archive(
    *,
    slug: str,
    body: CatalogInstallRequest,
    username: str,
    requires_db: bool,
) -> dict:
    """Generic installer for PHP apps shipped as a tar/zip archive.

    Steps:
    1. Provision a database (if required)
    2. wget the source tarball into /tmp
    3. tar/unzip into the document root
    4. chown to the user, restore default perms
    """
    url = _DOWNLOAD_URLS.get(slug)
    if not url:
        raise RuntimeError(f"No download URL configured for {slug}")

    target = _doc_root(username, body.domain, body.path)
    await _ensure_dir(target.parent, owner=username)
    await _ensure_dir(target, owner=username)

    db_info: dict = {}
    if requires_db:
        db_name = body.db_name or f"{slug}_{_random_token(6)}"
        db_user = body.db_user or f"{slug}_{_random_token(6)}"
        db_password = body.db_password or _random_token(20)
        await _provision_db(body.db_type, db_name, db_user, db_password)
        db_info = {
            "db_type": body.db_type,
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
        }

    archive_name = url.rsplit("/", 1)[-1]
    archive_path = Path("/tmp") / f"hosthive-{slug}-{_random_token(6)}-{archive_name}"

    try:
        await _download(url, archive_path)
        if archive_name.endswith(".php"):
            # Single-file apps like Adminer
            dest = target / archive_name
            await _to_thread(shutil.move, str(archive_path), str(dest))
        else:
            await _extract(archive_path, target)
    finally:
        exists = await _to_thread(archive_path.exists)
        if exists:
            await _to_thread(archive_path.unlink)

    await _run(["chown", "-R", f"{username}:{username}", str(target)])
    await _run(["find", str(target), "-type", "d", "-exec", "chmod", "755", "{}", "+"])
    await _run(["find", str(target), "-type", "f", "-exec", "chmod", "644", "{}", "+"])

    return {
        "ok": True,
        "data": {
            "path": str(target),
            "url": f"https://{body.domain}/" + (body.path.strip("/") if body.path else ""),
            **db_info,
        },
    }


async def _install_wordpress(body: CatalogInstallRequest, username: str) -> dict:
    """Install WordPress: download, extract, generate wp-config.php."""
    target = _doc_root(username, body.domain, body.path)
    await _ensure_dir(target.parent, owner=username)
    await _ensure_dir(target, owner=username)

    db_name = body.db_name or f"wp_{_random_token(6)}"
    db_user = body.db_user or f"wp_{_random_token(6)}"
    db_password = body.db_password or _random_token(20)
    await _provision_db("mysql", db_name, db_user, db_password)

    archive_path = Path("/tmp") / f"hosthive-wordpress-{_random_token(6)}.tar.gz"
    try:
        await _download(_DOWNLOAD_URLS["wordpress"], archive_path)
        await _extract(archive_path, target)
    finally:
        exists = await _to_thread(archive_path.exists)
        if exists:
            await _to_thread(archive_path.unlink)

    # Generate wp-config.php from the sample.
    sample = target / "wp-config-sample.php"
    cfg = target / "wp-config.php"
    sample_exists = await _to_thread(sample.exists)
    if sample_exists:
        contents = await _to_thread(sample.read_text, encoding="utf-8")
        contents = (
            contents.replace("database_name_here", db_name)
            .replace("username_here", db_user)
            .replace("password_here", db_password)
            .replace("localhost", "localhost")
        )
        # Replace salts with random ones
        for placeholder in (
            "put your unique phrase here",
        ):
            while placeholder in contents:
                contents = contents.replace(placeholder, _random_token(48), 1)
        await _to_thread(cfg.write_text, contents, encoding="utf-8")

    await _run(["chown", "-R", f"{username}:{username}", str(target)])

    return {
        "ok": True,
        "data": {
            "path": str(target),
            "url": f"https://{body.domain}/",
            "db_type": "mysql",
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
        },
    }


async def _install_laravel(body: CatalogInstallRequest, username: str) -> dict:
    """Install Laravel using composer create-project, then run composer install."""
    target = _doc_root(username, body.domain, body.path)
    await _ensure_dir(target.parent, owner=username)

    db_name = body.db_name or f"laravel_{_random_token(6)}"
    db_user = body.db_user or f"laravel_{_random_token(6)}"
    db_password = body.db_password or _random_token(20)
    await _provision_db(body.db_type, db_name, db_user, db_password)

    rc, out, err = await _run(
        [
            "sudo", "-u", username,
            "composer", "create-project", "--prefer-dist",
            "laravel/laravel", str(target),
        ],
        timeout=1200,
    )
    if rc != 0:
        raise RuntimeError(f"composer create-project laravel failed: {err or out}")

    # Write a basic .env file with the new DB credentials.
    env_file = target / ".env"
    env_contents = (
        f"APP_NAME=Laravel\n"
        f"APP_ENV=production\n"
        f"APP_KEY=\n"
        f"APP_URL=https://{body.domain}\n"
        f"DB_CONNECTION={'pgsql' if body.db_type == 'postgresql' else 'mysql'}\n"
        f"DB_HOST=127.0.0.1\n"
        f"DB_PORT={'5432' if body.db_type == 'postgresql' else '3306'}\n"
        f"DB_DATABASE={db_name}\n"
        f"DB_USERNAME={db_user}\n"
        f"DB_PASSWORD={db_password}\n"
    )
    await _to_thread(env_file.write_text, env_contents, encoding="utf-8")

    await _run(
        ["sudo", "-u", username, "php", "artisan", "key:generate", "--force"],
        cwd=str(target),
    )
    await _run(["chown", "-R", f"{username}:{username}", str(target)])

    return {
        "ok": True,
        "data": {
            "path": str(target),
            "url": f"https://{body.domain}/",
            "db_type": body.db_type,
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
        },
    }


async def _install_nodejs(body: CatalogInstallRequest, username: str) -> dict:
    """Scaffold a Node.js app and register it with PM2."""
    app_path = Path(body.path or f"/home/{username}/web/{body.domain}/app")
    await _ensure_dir(app_path, owner=username)

    port = body.port or 3000
    package_json = {
        "name": body.domain.replace(".", "-"),
        "version": "1.0.0",
        "main": "index.js",
        "scripts": {"start": "node index.js"},
    }
    index_js = (
        "const http = require('http');\n"
        f"const port = process.env.PORT || {port};\n"
        "http.createServer((req,res)=>{res.writeHead(200);res.end('Hello from HostHive');})"
        ".listen(port);\n"
    )
    await _to_thread(
        (app_path / "package.json").write_text,
        json.dumps(package_json, indent=2),
        encoding="utf-8",
    )
    await _to_thread((app_path / "index.js").write_text, index_js, encoding="utf-8")
    await _run(["chown", "-R", f"{username}:{username}", str(app_path)])

    rc, out, err = await _run(
        [
            "sudo", "-u", username, "pm2", "start", "index.js",
            "--name", body.domain, "--", "--port", str(port),
        ],
        cwd=str(app_path),
    )
    if rc != 0:
        raise RuntimeError(f"pm2 start failed: {err or out}")

    return {
        "ok": True,
        "data": {
            "path": str(app_path),
            "port": port,
            "url": f"https://{body.domain}/",
        },
    }


async def _install_django(body: CatalogInstallRequest, username: str) -> dict:
    """Create a virtualenv, install Django + gunicorn, and scaffold a project."""
    app_path = Path(body.path or f"/home/{username}/web/{body.domain}/app")
    await _ensure_dir(app_path, owner=username)

    venv = app_path / "venv"
    rc, out, err = await _run(
        ["sudo", "-u", username, "python3", "-m", "venv", str(venv)],
    )
    if rc != 0:
        raise RuntimeError(f"venv creation failed: {err or out}")

    pip = venv / "bin" / "pip"
    rc, out, err = await _run(
        ["sudo", "-u", username, str(pip), "install", "--quiet", "django", "gunicorn"],
        timeout=900,
    )
    if rc != 0:
        raise RuntimeError(f"pip install django failed: {err or out}")

    db_info: dict = {}
    if body.db_type:
        db_name = body.db_name or f"dj_{_random_token(6)}"
        db_user = body.db_user or f"dj_{_random_token(6)}"
        db_password = body.db_password or _random_token(20)
        try:
            await _provision_db(body.db_type, db_name, db_user, db_password)
            db_info = {
                "db_type": body.db_type,
                "db_name": db_name,
                "db_user": db_user,
                "db_password": db_password,
            }
        except RuntimeError as exc:
            logger.warning("Skipping DB provisioning for django: %s", exc)

    django_admin = venv / "bin" / "django-admin"
    project_name = "site_" + body.domain.replace(".", "_").replace("-", "_")
    rc, out, err = await _run(
        ["sudo", "-u", username, str(django_admin), "startproject", project_name, "."],
        cwd=str(app_path),
    )
    if rc != 0:
        raise RuntimeError(f"django-admin startproject failed: {err or out}")

    await _run(["chown", "-R", f"{username}:{username}", str(app_path)])

    return {
        "ok": True,
        "data": {
            "path": str(app_path),
            "port": body.port or 8000,
            "url": f"https://{body.domain}/",
            **db_info,
        },
    }


async def _install_ghost(body: CatalogInstallRequest, username: str) -> dict:
    """Install Ghost via the Ghost-CLI tool (npm)."""
    target = _doc_root(username, body.domain, body.path)
    await _ensure_dir(target, owner=username)

    db_name = body.db_name or f"ghost_{_random_token(6)}"
    db_user = body.db_user or f"ghost_{_random_token(6)}"
    db_password = body.db_password or _random_token(20)
    await _provision_db("mysql", db_name, db_user, db_password)

    # Make sure ghost-cli is available
    await _run(["npm", "install", "-g", "ghost-cli@latest"], timeout=900)

    rc, out, err = await _run(
        [
            "sudo", "-u", username, "ghost", "install",
            "--db", "mysql",
            "--dbhost", "localhost",
            "--dbuser", db_user,
            "--dbpass", db_password,
            "--dbname", db_name,
            "--no-prompt", "--no-setup-nginx", "--no-setup-ssl", "--no-stack",
        ],
        cwd=str(target),
        timeout=1800,
    )
    if rc != 0:
        raise RuntimeError(f"ghost install failed: {err or out}")

    return {
        "ok": True,
        "data": {
            "path": str(target),
            "port": body.port or 2368,
            "url": f"https://{body.domain}/",
            "db_type": "mysql",
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
        },
    }


async def _install_docker_app(body: CatalogInstallRequest, username: str) -> dict:
    """Pull and run a docker image for apps that ship as containers."""
    image_map = {
        "discourse": "bitnami/discourse:latest",
        "invoiceninja": "invoiceninja/invoiceninja:latest",
        "uptimekuma": "louislam/uptime-kuma:latest",
        "grafana": "grafana/grafana:latest",
        "portainer": "portainer/portainer-ce:latest",
    }
    port_map = {
        "discourse": (4200, 80),
        "invoiceninja": (9080, 80),
        "uptimekuma": (3001, 3001),
        "grafana": (3100, 3000),
        "portainer": (9443, 9443),
    }
    image = image_map.get(body.slug)
    if not image:
        raise RuntimeError(f"No docker image configured for {body.slug}")

    host_port, container_port = port_map.get(body.slug, (8080, 80))
    if body.port:
        host_port = body.port

    container_name = f"hosthive-{body.slug}-{body.domain.replace('.', '-')}"

    rc, out, err = await _run(["docker", "pull", image], timeout=900)
    if rc != 0:
        raise RuntimeError(f"docker pull failed: {err or out}")

    rc, out, err = await _run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "--restart", "unless-stopped",
            "-p", f"{host_port}:{container_port}",
            image,
        ],
    )
    if rc != 0:
        raise RuntimeError(f"docker run failed: {err or out}")

    return {
        "ok": True,
        "data": {
            "container": container_name,
            "image": image,
            "port": host_port,
            "url": f"https://{body.domain}/",
        },
    }


async def _install_binary_app(body: CatalogInstallRequest, username: str) -> dict:
    """Install binary-distributed apps (gitea, mattermost, minio) via apt or wget."""
    slug = body.slug
    db_info: dict = {}
    if slug in ("gitea", "mattermost"):
        db_name = body.db_name or f"{slug}_{_random_token(6)}"
        db_user = body.db_user or f"{slug}_{_random_token(6)}"
        db_password = body.db_password or _random_token(20)
        await _provision_db(body.db_type, db_name, db_user, db_password)
        db_info = {
            "db_type": body.db_type,
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
        }

    install_dir = Path(f"/opt/{slug}")
    await _ensure_dir(install_dir)

    if slug == "gitea":
        url = "https://dl.gitea.com/gitea/1.22.0/gitea-1.22.0-linux-amd64"
        target = install_dir / "gitea"
        await _download(url, target)
        await _run(["chmod", "+x", str(target)])
    elif slug == "mattermost":
        url = "https://releases.mattermost.com/10.3.0/mattermost-10.3.0-linux-amd64.tar.gz"
        archive = Path("/tmp") / f"mattermost-{_random_token(6)}.tar.gz"
        try:
            await _download(url, archive)
            await _extract(archive, install_dir)
        finally:
            exists = await _to_thread(archive.exists)
            if exists:
                await _to_thread(archive.unlink)
    elif slug == "minio":
        url = "https://dl.min.io/server/minio/release/linux-amd64/minio"
        target = install_dir / "minio"
        await _download(url, target)
        await _run(["chmod", "+x", str(target)])
    else:
        raise RuntimeError(f"Unknown binary app: {slug}")

    return {
        "ok": True,
        "data": {
            "path": str(install_dir),
            "port": body.port,
            "url": f"https://{body.domain}/",
            **db_info,
        },
    }


# --------------------------------------------------------------------------
# GET /catalog -- list available applications for installation
# --------------------------------------------------------------------------

@router.get("/catalog", response_model=list[CatalogApp])
async def list_catalog(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    current_user: User = Depends(get_current_user),
):
    """Return the catalog of available applications for one-click install."""
    if category:
        return [app for app in APP_CATALOG if app.category.lower() == category.lower()]
    return APP_CATALOG


# --------------------------------------------------------------------------
# POST /catalog/install -- install a catalog application
# --------------------------------------------------------------------------

@router.post("/catalog/install", response_model=CatalogInstallResponse)
async def install_catalog_app(
    body: CatalogInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Install an application from the catalog onto a domain.

    Runs all installer commands directly on this host via subprocess --
    no requests are made to any agent on port 7080. Blocking work is
    pushed onto a worker thread via ``run_in_executor``.
    """
    catalog_app = _CATALOG_BY_SLUG.get(body.slug)
    if catalog_app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.slug}' not found in catalog.",
        )

    username = current_user.username
    version = body.version or catalog_app.version

    php_archive_apps = {
        "joomla": True,
        "drupal": True,
        "prestashop": True,
        "opencart": True,
        "magento": True,
        "mediawiki": True,
        "bookstack": True,
        "phpbb": True,
        "roundcube": True,
        "adminer": False,
        "phpmyadmin": False,
        "nextcloud": True,
    }

    try:
        if body.slug == "wordpress":
            resp = await _install_wordpress(body, username)
        elif body.slug == "laravel":
            resp = await _install_laravel(body, username)
        elif body.slug == "nodejs":
            resp = await _install_nodejs(body, username)
        elif body.slug == "python-django":
            resp = await _install_django(body, username)
        elif body.slug == "ghost":
            resp = await _install_ghost(body, username)
        elif body.slug in php_archive_apps:
            resp = await _install_php_archive(
                slug=body.slug,
                body=body,
                username=username,
                requires_db=php_archive_apps[body.slug],
            )
        elif body.slug in ("gitea", "mattermost", "minio"):
            resp = await _install_binary_app(body, username)
        elif body.slug in ("discourse", "invoiceninja", "uptimekuma", "grafana", "portainer"):
            resp = await _install_docker_app(body, username)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No installer available for '{body.slug}'.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Catalog install failed for %s", body.slug)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to install {catalog_app.name}: {exc}",
        )

    if not resp.get("ok", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=resp.get("error", f"Installation of {catalog_app.name} failed"),
        )

    _log(
        db, request, current_user.id,
        "apps.install",
        f"Installed {catalog_app.name} v{version} on {body.domain}",
    )

    return CatalogInstallResponse(
        slug=body.slug,
        name=catalog_app.name,
        domain=body.domain,
        status="installed",
        message=f"{catalog_app.name} has been installed successfully.",
        details=resp.get("data", {}),
    )


# --------------------------------------------------------------------------
# GET / -- list all running apps
# --------------------------------------------------------------------------


@router.get("", response_model=list[AppListEntry])
async def list_apps(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List apps stored in the local DB (no agent proxy)."""
    query = select(App)
    if not _is_admin(current_user):
        query = query.where(App.user_id == current_user.id)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        AppListEntry(
            domain=row.domain,
            runtime=row.runtime,
            port=row.port,
            status=row.status,
            path=row.path,
            deployed_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]


# --------------------------------------------------------------------------
# POST /deploy -- deploy Node.js or Python app
# --------------------------------------------------------------------------


@router.post("/deploy", response_model=AppStatusResponse)
async def deploy_app(
    body: AppDeployRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deploy a Node.js or Python app locally via PM2 / virtualenv."""
    username = current_user.username

    try:
        if body.runtime == "nodejs":
            install_body = CatalogInstallRequest(
                slug="nodejs",
                domain=body.domain,
                path=body.path,
                port=body.port,
                version=body.version or "20",
            )
            resp = await _install_nodejs(install_body, username)
        elif body.runtime == "python":
            install_body = CatalogInstallRequest(
                slug="python-django",
                domain=body.domain,
                path=body.path,
                port=body.port,
                version=body.version or "3.11",
                db_type="",
            )
            resp = await _install_django(install_body, username)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported runtime: {body.runtime}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Deploy failed for %s", body.domain)
        raise HTTPException(status_code=500, detail=f"Deployment failed: {exc}")

    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Deployment failed"))

    db.add(App(
        user_id=current_user.id,
        domain=body.domain,
        runtime=body.runtime,
        port=body.port,
        path=body.path,
        status="running",
        version=body.version,
    ))

    data = resp.get("data", {})
    return AppStatusResponse(
        domain=body.domain,
        runtime=body.runtime,
        status="running",
        port=data.get("port", body.port),
        path=data.get("path", body.path),
    )


# --------------------------------------------------------------------------
# POST /{domain}/stop
# --------------------------------------------------------------------------


async def _control_app(domain: str, action: str) -> None:
    """Run a PM2 stop/restart for the given app, then fall back to systemctl."""
    cmd_map = {
        "stop": ["pm2", "stop", domain],
        "start": ["pm2", "start", domain],
        "restart": ["pm2", "restart", domain],
    }
    cmd = cmd_map.get(action)
    if not cmd:
        raise RuntimeError(f"Unknown action: {action}")

    rc, out, err = await _run(cmd)
    if rc == 0:
        return

    # Fall back to systemctl for non-PM2 apps.
    rc, out, err = await _run(["systemctl", action, f"hosthive-app-{domain}"])
    if rc != 0:
        raise RuntimeError(f"{action} failed: {err or out}")


@router.post("/{domain}/stop", response_model=AppStopStartResponse)
async def stop_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop a running app via local PM2/systemctl."""
    try:
        await _control_app(domain, "stop")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Stop failed: {exc}")

    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if app_row:
        app_row.status = "stopped"

    return {"domain": domain, "action": "stop", "success": True}


# --------------------------------------------------------------------------
# POST /{domain}/start
# --------------------------------------------------------------------------


@router.post("/{domain}/start", response_model=AppStopStartResponse)
async def start_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a previously-stopped app via local PM2/systemctl."""
    try:
        await _control_app(domain, "start")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Start failed: {exc}")

    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if app_row:
        app_row.status = "running"

    return {"domain": domain, "action": "start", "success": True}


# --------------------------------------------------------------------------
# POST /{domain}/restart
# --------------------------------------------------------------------------


@router.post("/{domain}/restart", response_model=AppStopStartResponse)
async def restart_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restart an app via local PM2/systemctl."""
    try:
        await _control_app(domain, "restart")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Restart failed: {exc}")

    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if app_row:
        app_row.status = "running"

    return {"domain": domain, "action": "restart", "success": True}


# --------------------------------------------------------------------------
# GET /{domain}/status -- app status + resource usage
# --------------------------------------------------------------------------


@router.get("/{domain}/status", response_model=AppStatusResponse)
async def app_status(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return app status from PM2 (preferred) or DB."""
    rc, out, err = await _run(["pm2", "jlist"])
    if rc == 0 and out:
        try:
            entries = json.loads(out)
        except json.JSONDecodeError:
            entries = []
        for entry in entries:
            if entry.get("name") == domain:
                pm2_env = entry.get("pm2_env", {}) or {}
                monit = entry.get("monit", {}) or {}
                return AppStatusResponse(
                    domain=domain,
                    runtime="nodejs",
                    status=pm2_env.get("status", "unknown"),
                    pid=int(entry.get("pid") or 0),
                    port=pm2_env.get("PORT"),
                    path=pm2_env.get("pm_cwd"),
                    started_at=str(pm2_env.get("pm_uptime") or ""),
                    memory_bytes=monit.get("memory"),
                    memory_mb=(monit.get("memory") or 0) / (1024 * 1024) if monit.get("memory") else None,
                )

    # Fall back to DB
    result = await db.execute(select(App).where(App.domain == domain))
    app_row = result.scalar_one_or_none()
    if not app_row:
        raise HTTPException(status_code=404, detail="App not found")
    return AppStatusResponse(
        domain=app_row.domain,
        runtime=app_row.runtime,
        status=app_row.status,
        port=app_row.port,
        path=app_row.path,
    )


# --------------------------------------------------------------------------
# GET /{domain}/logs -- app logs
# --------------------------------------------------------------------------


@router.get("/{domain}/logs", response_model=AppLogsResponse)
async def app_logs(
    domain: str,
    lines: int = Query(200, ge=1, le=10000),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    """Tail recent log lines for an app via local ``tail -n``."""
    out_path = LOG_DIR / f"{domain}.stdout.log"
    err_path = LOG_DIR / f"{domain}.stderr.log"

    async def _tail(path: Path) -> str:
        exists = await _to_thread(path.exists)
        if not exists:
            return ""
        rc, out, err = await _run(["tail", "-n", str(lines), str(path)])
        if rc != 0:
            return err or out
        return out

    stdout, stderr = await asyncio.gather(_tail(out_path), _tail(err_path))
    return AppLogsResponse(
        domain=domain,
        logs={
            "stdout": stdout,
            "stderr": stderr,
        },
    )


# --------------------------------------------------------------------------
# PUT /{domain}/env -- update environment variables
# --------------------------------------------------------------------------


@router.put("/{domain}/env")
async def update_env_vars(
    domain: str,
    body: AppEnvUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Persist env vars to ``/etc/hosthive/apps/<domain>.env`` and restart."""
    env_dir = Path("/etc/hosthive/apps")
    await _ensure_dir(env_dir)
    env_file = env_dir / f"{domain}.env"

    lines = [f"{k}={v}" for k, v in body.env_vars.items()]
    try:
        await _to_thread(env_file.write_text, "\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write env file: {exc}")

    # Best-effort restart so the new env takes effect.
    try:
        await _control_app(domain, "restart")
    except Exception as exc:
        logger.warning("Could not restart %s after env update: %s", domain, exc)

    return {"domain": domain, "env_file": str(env_file), "count": len(body.env_vars)}


# --------------------------------------------------------------------------
# WebSocket /ws/apps/{domain}/logs -- live log streaming
# --------------------------------------------------------------------------


@router.websocket("/ws/apps/{domain}/logs")
async def ws_app_logs(websocket: WebSocket, domain: str):
    """Stream live application logs via WebSocket.

    Clients receive log lines as they are written. Uses ``tail -f`` via
    asyncio subprocess (no agent proxy).
    """
    await websocket.accept()

    log_path = LOG_DIR / f"{domain}.stdout.log"

    try:
        exists = await _to_thread(log_path.exists)
        if not exists:
            await websocket.send_text(f"No log file found for {domain}")
            await websocket.close()
            return

        proc = await asyncio.create_subprocess_exec(
            "tail", "-f", "-n", "50", str(log_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_output():
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await websocket.send_text(line.decode("utf-8", errors="replace").rstrip())

        read_task = asyncio.create_task(read_output())

        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            read_task.cancel()
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
