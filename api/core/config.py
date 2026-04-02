"""Application settings loaded from environment / secrets file."""

from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_SECRETS_ENV = Path("/opt/hosthive/config/secrets.env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_SECRETS_ENV) if _SECRETS_ENV.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://hosthive:changeme@127.0.0.1:5432/hosthive",
        description="Async PostgreSQL connection string (asyncpg driver).",
    )

    # ── Redis ───────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis connection URL used for caching and rate-limiting.",
    )

    # ── Secrets / Keys ──────────────────────────────────────────────────
    SECRET_KEY: str = Field(
        ...,
        min_length=32,
        description="Main secret used to sign JWTs and session data.",
    )
    AGENT_SECRET: str = Field(
        ...,
        min_length=32,
        description="Shared HMAC secret for API <-> Agent communication.",
    )

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
    database_password: str = Field(default="", description="PostgreSQL password (from installer).")
    redis_password: str = Field(default="", description="Redis password (from installer).")
    admin_username: str = Field(default="admin", description="Initial admin username.")
    admin_password: str = Field(default="", description="Initial admin password.")
    admin_email: str = Field(default="admin@localhost", description="Initial admin email.")
    server_ip: str = Field(default="127.0.0.1", description="Server public IP.")
    panel_port: str = Field(default="8083", description="Panel HTTPS port.")

    # ── Misc ────────────────────────────────────────────────────────────
    DEBUG: bool = Field(default=False)


settings = Settings()  # type: ignore[call-arg]
