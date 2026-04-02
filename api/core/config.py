"""Application settings loaded from environment / secrets file."""

from __future__ import annotations

from pathlib import Path
from typing import List
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SECRETS_ENV = Path("/opt/hosthive/config/secrets.env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_SECRETS_ENV) if _SECRETS_ENV.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="",
        description="Async PostgreSQL connection string (asyncpg driver).",
    )

    # ── Database components (from installer secrets.env) ───────────────
    DB_USER: str = Field(default="hosthive", description="PostgreSQL username.")
    DB_PASSWORD: str = Field(default="", description="PostgreSQL password.")
    DB_NAME: str = Field(default="hosthive", description="PostgreSQL database name.")

    # ── Redis ───────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="",
        description="Redis connection URL used for caching and rate-limiting.",
    )
    REDIS_PASSWORD: str = Field(default="", description="Redis password (from installer).")

    # ── Secrets / Keys ──────────────────────────────────────────────────
    SECRET_KEY: str = Field(
        ...,
        min_length=32,
        description="Main secret used to sign JWTs and session data.",
    )
    AGENT_SECRET: str = Field(
        default="",
        description="Shared HMAC secret for API <-> Agent communication.",
    )

    @model_validator(mode="after")
    def _build_connection_urls(self) -> "Settings":
        """Construct DATABASE_URL and REDIS_URL from components if not set."""
        if not self.DATABASE_URL:
            password = quote_plus(self.DB_PASSWORD) if self.DB_PASSWORD else "changeme"
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.DB_USER}:{password}"
                f"@127.0.0.1:5432/{self.DB_NAME}"
            )
        if not self.REDIS_URL:
            if self.REDIS_PASSWORD:
                self.REDIS_URL = f"redis://:{quote_plus(self.REDIS_PASSWORD)}@127.0.0.1:6379/0"
            else:
                self.REDIS_URL = "redis://127.0.0.1:6379/0"
        if not self.AGENT_SECRET:
            # Derive from SECRET_KEY so the API can start even if AGENT_SECRET
            # was not explicitly provided (older secrets.env files).
            import hashlib
            self.AGENT_SECRET = hashlib.sha256(
                (self.SECRET_KEY + ":agent").encode()
            ).hexdigest()
        # Support legacy ADMIN_USER env var from older installers
        if self.ADMIN_USER and self.admin_username == "admin":
            self.admin_username = self.ADMIN_USER
        return self

    # ── Agent connection ────────────────────────────────────────────────
    AGENT_URL: str = Field(
        default="http://127.0.0.1:7080",
        description="Base URL of the HostHive system agent.",
    )

    # ── JWT settings ────────────────────────────────────────────────────
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30)
    JWT_ALGORITHM: str = Field(default="HS256")

    # ── CORS / Domain ──────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = Field(
        default=["https://panel.example.com"],
        description="Allowed CORS origins.",
    )
    PANEL_DOMAIN: str = Field(
        default="panel.example.com",
        description="Public domain where the panel is served.",
    )

    # ── MCP ─────────────────────────────────────────────────────────────
    MCP_ENABLED: bool = Field(
        default=False,
        description="Enable the MCP (Model Context Protocol) server on port 8765.",
    )
    MCP_TOKEN: str = Field(
        default="",
        description="Bearer token for MCP authentication.  Auto-derived from SECRET_KEY if empty.",
    )

    # ── Docker ──────────────────────────────────────────────────────────
    DOCKER_ENABLED: bool = Field(
        default=True,
        description="Enable Docker container management (requires Docker on host).",
    )

    # ── Installer-generated fields ─────────────────────────────────────
    admin_username: str = Field(default="admin", description="Initial admin username.")
    ADMIN_USER: str = Field(default="", description="Legacy env var for admin username.")
    admin_password: str = Field(default="", description="Initial admin password.")
    admin_email: str = Field(default="admin@localhost", description="Initial admin email.")
    server_ip: str = Field(default="127.0.0.1", description="Server public IP.")
    panel_port: str = Field(default="8083", description="Panel HTTPS port.")

    # ── Misc ────────────────────────────────────────────────────────────
    DEBUG: bool = Field(default=False)


settings = Settings()  # type: ignore[call-arg]
