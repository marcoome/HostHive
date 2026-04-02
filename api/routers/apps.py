"""Apps router -- /api/v1/apps.

Deploy and manage Node.js / Python applications, plus a catalog of
popular web applications available for one-click installation.
"""

from __future__ import annotations

import uuid
from typing import Optional

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


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


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
]

_CATALOG_BY_SLUG = {app.slug: app for app in APP_CATALOG}


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
    """Install an application from the catalog onto a domain."""
    catalog_app = _CATALOG_BY_SLUG.get(body.slug)
    if catalog_app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{body.slug}' not found in catalog.",
        )

    agent = request.app.state.agent
    version = body.version or catalog_app.version

    # Route to the appropriate agent installer based on application type
    try:
        if body.slug == "wordpress":
            resp = await agent.post("/apps/install/wordpress", json={
                "domain": body.domain,
                "path": body.path,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "version": version,
            })
        elif body.slug in ("joomla", "drupal", "prestashop", "opencart", "magento"):
            resp = await agent.post("/apps/install/php", json={
                "app": body.slug,
                "domain": body.domain,
                "path": body.path,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "db_type": body.db_type,
                "version": version,
            })
        elif body.slug == "laravel":
            resp = await agent.post("/apps/install/laravel", json={
                "domain": body.domain,
                "path": body.path,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "db_type": body.db_type,
                "version": version,
            })
        elif body.slug == "nodejs":
            resp = await agent.post("/apps/deploy/nodejs", json={
                "domain": body.domain,
                "path": body.path or f"/home/{current_user.username}/web/{body.domain}/app",
                "port": body.port or 3000,
                "node_version": version,
            })
        elif body.slug == "python-django":
            resp = await agent.post("/apps/install/django", json={
                "domain": body.domain,
                "path": body.path or f"/home/{current_user.username}/web/{body.domain}/app",
                "port": body.port or 8000,
                "python_version": version,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "db_type": body.db_type,
            })
        elif body.slug == "ghost":
            resp = await agent.post("/apps/install/ghost", json={
                "domain": body.domain,
                "path": body.path,
                "port": body.port or 2368,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "version": version,
            })
        elif body.slug == "nextcloud":
            resp = await agent.post("/apps/install/php", json={
                "app": "nextcloud",
                "domain": body.domain,
                "path": body.path,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "db_type": body.db_type,
                "version": version,
            })
        elif body.slug == "phpmyadmin":
            resp = await agent.post("/apps/install/phpmyadmin", json={
                "domain": body.domain,
                "path": body.path or "/phpmyadmin",
                "version": version,
            })
        elif body.slug == "roundcube":
            resp = await agent.post("/apps/install/php", json={
                "app": "roundcube",
                "domain": body.domain,
                "path": body.path,
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "db_type": body.db_type,
                "version": version,
            })
        elif body.slug in ("gitea", "mattermost"):
            resp = await agent.post("/apps/install/binary", json={
                "app": body.slug,
                "domain": body.domain,
                "port": body.port or (3000 if body.slug == "gitea" else 8065),
                "db_name": body.db_name,
                "db_user": body.db_user,
                "db_password": body.db_password,
                "db_type": body.db_type,
                "version": version,
            })
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No installer available for '{body.slug}'.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error installing {catalog_app.name}: {exc}",
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
    agent = request.app.state.agent
    resp = await agent.get("/apps/list")
    return resp.get("data", [])


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
    agent = request.app.state.agent

    if body.runtime == "nodejs":
        resp = await agent.post("/apps/deploy/nodejs", json={
            "domain": body.domain,
            "path": body.path,
            "port": body.port,
            "node_version": body.version or "20",
        })
    elif body.runtime == "python":
        resp = await agent.post("/apps/deploy/python", json={
            "domain": body.domain,
            "path": body.path,
            "port": body.port,
            "python_version": body.version or "3.11",
        })
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported runtime: {body.runtime}")

    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Deployment failed"))

    # Persist to DB
    db.add(App(
        user_id=current_user.id,
        domain=body.domain,
        runtime=body.runtime,
        port=body.port,
        path=body.path,
        status="running",
        version=body.version,
    ))

    data = resp.get("data", resp)
    return data


# --------------------------------------------------------------------------
# POST /{domain}/stop
# --------------------------------------------------------------------------


@router.post("/{domain}/stop", response_model=AppStopStartResponse)
async def stop_app(
    domain: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.post("/apps/stop", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Stop failed"))

    # Update DB
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
    agent = request.app.state.agent
    resp = await agent.post("/apps/restart", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Start failed"))

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
    agent = request.app.state.agent
    resp = await agent.post("/apps/restart", json={"domain": domain})
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Restart failed"))

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
    current_user: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    resp = await agent.get(f"/apps/status/{domain}")
    if not resp.get("ok", True):
        raise HTTPException(status_code=404, detail=resp.get("error", "App not found"))
    return resp.get("data", resp)


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
    agent = request.app.state.agent
    resp = await agent.get(f"/apps/logs/{domain}", params={"lines": lines})
    return resp.get("data", resp)


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
    agent = request.app.state.agent
    resp = await agent.put(f"/apps/env/{domain}", json={
        "domain": domain,
        "env_dict": body.env_vars,
    })
    if not resp.get("ok", True):
        raise HTTPException(status_code=400, detail=resp.get("error", "Failed to update env vars"))
    return resp.get("data", resp)


# --------------------------------------------------------------------------
# WebSocket /ws/apps/{domain}/logs -- live log streaming
# --------------------------------------------------------------------------


@router.websocket("/ws/apps/{domain}/logs")
async def ws_app_logs(websocket: WebSocket, domain: str):
    """Stream live application logs via WebSocket.

    Clients receive log lines as they are written.
    """
    import asyncio
    from pathlib import Path

    await websocket.accept()

    log_path = Path(f"/var/log/hosthive/apps/{domain}.stdout.log")

    try:
        # Start tailing the log file
        if not log_path.exists():
            await websocket.send_text(f"No log file found for {domain}")
            await websocket.close()
            return

        # Use tail -f approach via asyncio subprocess
        proc = await asyncio.create_subprocess_exec(
            "tail", "-f", "-n", "50", str(log_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_output():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await websocket.send_text(line.decode("utf-8", errors="replace").rstrip())

        read_task = asyncio.create_task(read_output())

        # Wait for client disconnect
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            read_task.cancel()
            proc.terminate()

    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
