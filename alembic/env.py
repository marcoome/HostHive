"""Alembic environment configuration for NovaPanel."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.database import Base  # noqa: E402

# Import ALL model modules so that Base.metadata has every table registered
import api.models.users  # noqa: E402, F401
import api.models.packages  # noqa: E402, F401
import api.models.domains  # noqa: E402, F401
import api.models.databases  # noqa: E402, F401
import api.models.dns_zones  # noqa: E402, F401
import api.models.dns_records  # noqa: E402, F401
import api.models.dns_cluster  # noqa: E402, F401
import api.models.email_accounts  # noqa: E402, F401
import api.models.email_aliases  # noqa: E402, F401
import api.models.ftp_accounts  # noqa: E402, F401
import api.models.ssl_certificates  # noqa: E402, F401
import api.models.cron_jobs  # noqa: E402, F401
import api.models.backups  # noqa: E402, F401
import api.models.docker  # noqa: E402, F401
import api.models.webauthn  # noqa: E402, F401
import api.models.antivirus  # noqa: E402, F401
import api.models.reseller  # noqa: E402, F401
import api.models.monitoring  # noqa: E402, F401
import api.models.notifications  # noqa: E402, F401
import api.models.activity_log  # noqa: E402, F401
import api.models.server_stats  # noqa: E402, F401
import api.models.resources  # noqa: E402, F401
import api.models.apps  # noqa: E402, F401
import api.models.ai  # noqa: E402, F401
import api.models.integrations  # noqa: E402, F401
import api.models.user_environment  # noqa: E402, F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_sync_url() -> str:
    """Build a synchronous database URL from settings or alembic.ini."""
    try:
        from api.core.config import settings
        url = settings.DATABASE_URL
        # Replace async driver with sync driver for Alembic
        return url.replace("+asyncpg", "+psycopg2")
    except Exception:
        return config.get_main_option("sqlalchemy.url", "")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
