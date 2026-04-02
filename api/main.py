"""FastAPI application entry point for HostHive."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.core.config import settings
from api.core.agent_client import AgentClient
from api.core.database import engine
from api.core.middleware import SecurityHeadersMiddleware, AuditLogMiddleware
from api.core.rate_limit import limiter
from api.core.reseller_middleware import ResellerBrandingMiddleware

# ---------------------------------------------------------------------------
# Lifespan: start-up / shutdown
# ---------------------------------------------------------------------------

async def _ensure_admin_user() -> None:
    """Create or update the admin account to match secrets.env credentials."""
    from api.core.database import async_session_factory
    from api.core.security import hash_password, verify_password
    from api.models.users import User, UserRole
    from sqlalchemy import select
    import logging
    _log = logging.getLogger("hosthive.startup")

    admin_username = settings.admin_username or "admin"
    admin_password = settings.admin_password or "changeme"
    admin_email = settings.admin_email or f"{admin_username}@localhost"

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.role == UserRole.ADMIN).limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            # Update password if it doesn't match (handles reinstall with new secrets)
            if not verify_password(admin_password, existing.password_hash):
                existing.password_hash = hash_password(admin_password)
                existing.username = admin_username
                existing.email = admin_email
                existing.is_active = True
                existing.is_suspended = False
                session.add(existing)
                await session.commit()
                _log.info("Admin password updated to match secrets.env")
            return

        admin = User(
            username=admin_username,
            email=admin_email,
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        _log.info("Admin user '%s' created.", admin_username)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    import logging
    _logger = logging.getLogger("hosthive.startup")

    # Startup -----------------------------------------------------------
    # Redis
    _logger.info("Connecting to Redis at %s", settings.REDIS_URL.split("@")[-1] if "@" in settings.REDIS_URL else settings.REDIS_URL)
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
    # Verify Redis connection at startup
    try:
        await app.state.redis.ping()
        _logger.info("Redis connection OK.")
    except Exception as exc:
        _logger.error("Redis connection FAILED: %s — login/sessions will not work!", exc)

    # Agent client
    app.state.agent = AgentClient()

    # Create tables if they don't exist yet (first run)
    _logger.info("Creating database tables (if not exist)...")
    import api.models  # noqa: F401 - ensure all models are registered
    from api.core.database import Base as _Base
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)
        _logger.info("Database tables ready.")
    except Exception as exc:
        _logger.error(
            "Failed to create database tables: %s. "
            "Check DATABASE_URL and PostgreSQL permissions (GRANT ALL ON SCHEMA public TO hosthive).",
            exc,
        )
        raise

    # Create initial admin user if not exists
    await _ensure_admin_user()
    _logger.info("HostHive API startup complete.")

    yield

    # Shutdown ----------------------------------------------------------
    await app.state.agent.close()
    await app.state.redis.aclose()  # type: ignore[union-attr]
    await engine.dispose()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HostHive",
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
    redirect_slashes=False,  # Disable trailing slash redirect to fix CORS preflight
)

# Middleware ----------------------------------------------------------------
# NOTE: Starlette processes middlewares in reverse order of registration,
# so the first added middleware is the *outermost* layer.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://panel.example.com",
        f"https://{settings.server_ip}:8443",  # Allow self-hosted IP
        "http://localhost:5173",  # Allow dev frontend
        "https://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditLogMiddleware)
app.add_middleware(ResellerBrandingMiddleware)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.exception_handler(PermissionError)
async def permission_error_handler(_request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    import logging
    logging.getLogger("hosthive.api").exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from api.routers import (  # noqa: E402
    ai_router,
    auth_router,
    backups_router,
    branding_router,
    cron_router,
    databases_router,
    dns_router,
    domains_router,
    email_router,
    files_router,
    ftp_router,
    packages_router,
    server_router,
    ssl_router,
    users_router,
    integrations_router,
    audit_router,
    api_keys_router,
    status_router,
    billing_router,
    metrics_router,
    monitoring_router,
    reseller_router,
    admin_router,
    wireguard_router,
    environments_router,
    analytics_router,
    waf_router,
    resources_router,
    apps_router,
    email_auth_router,
    docker_router,
    wordpress_router,
)

_v1 = "/api/v1"
app.include_router(ai_router,        prefix=f"{_v1}/ai",        tags=["AI"])
app.include_router(auth_router,      prefix=f"{_v1}/auth",      tags=["Auth"])
app.include_router(users_router,     prefix=f"{_v1}/users",     tags=["Users"])
app.include_router(domains_router,   prefix=f"{_v1}/domains",   tags=["Domains"])
app.include_router(databases_router, prefix=f"{_v1}/databases", tags=["Databases"])
app.include_router(email_router,     prefix=f"{_v1}/email",     tags=["Email"])
app.include_router(dns_router,       prefix=f"{_v1}/dns",       tags=["DNS"])
app.include_router(ftp_router,       prefix=f"{_v1}/ftp",       tags=["FTP"])
app.include_router(cron_router,      prefix=f"{_v1}/cron",      tags=["Cron"])
app.include_router(ssl_router,       prefix=f"{_v1}/ssl",       tags=["SSL"])
app.include_router(backups_router,   prefix=f"{_v1}/backups",   tags=["Backups"])
app.include_router(packages_router,  prefix=f"{_v1}/packages",  tags=["Packages"])
app.include_router(server_router,    prefix=f"{_v1}/server",    tags=["Server"])
app.include_router(files_router,     prefix=f"{_v1}/files",     tags=["Files"])
app.include_router(branding_router,      prefix=f"{_v1}/branding",      tags=["Branding"])
app.include_router(integrations_router,  prefix=f"{_v1}/integrations",  tags=["Integrations"])
app.include_router(audit_router,         prefix=f"{_v1}/audit",         tags=["Audit"])
app.include_router(api_keys_router,      prefix=f"{_v1}/api-keys",      tags=["API Keys"])
app.include_router(status_router,        prefix=f"{_v1}/status",        tags=["Status"])
app.include_router(billing_router,       prefix=f"{_v1}/billing",       tags=["Billing"])
app.include_router(monitoring_router,    prefix=f"{_v1}/monitoring",    tags=["Monitoring"])
app.include_router(reseller_router,     prefix=f"{_v1}/reseller",     tags=["Reseller"])
app.include_router(admin_router,         prefix=f"{_v1}/admin",         tags=["Admin"])
app.include_router(wireguard_router,     prefix=f"{_v1}/wireguard",     tags=["WireGuard"])
app.include_router(environments_router,  prefix=f"{_v1}/environments", tags=["Environments"])
app.include_router(analytics_router,     prefix=f"{_v1}/analytics",    tags=["Analytics"])
app.include_router(waf_router,           prefix=f"{_v1}/waf",          tags=["WAF"])
app.include_router(resources_router,     prefix=f"{_v1}/resources",    tags=["Resources"])
app.include_router(apps_router,          prefix=f"{_v1}/apps",         tags=["Apps"])
app.include_router(email_auth_router,    prefix=f"{_v1}/email/auth",   tags=["Email Auth"])
app.include_router(docker_router,        prefix=f"{_v1}/docker",       tags=["Docker"])
app.include_router(wordpress_router,     prefix=f"{_v1}/wordpress",    tags=["WordPress"])
app.include_router(metrics_router,       prefix="/metrics",             tags=["Metrics"])


@app.get("/api/v1/health", tags=["Health"])
async def healthcheck() -> dict[str, Any]:
    return {"status": "ok", "version": app.version}
