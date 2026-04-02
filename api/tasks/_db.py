"""Synchronous database session factory for Celery workers.

Celery tasks run in a synchronous context, so we need a separate
sync engine/session instead of the async one used by FastAPI.
The connection string is derived from the async DATABASE_URL by
swapping the asyncpg driver for psycopg2.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.core.config import settings

# Convert async URL (postgresql+asyncpg://) to sync (postgresql+psycopg2://)
_sync_url = settings.DATABASE_URL.replace(
    "postgresql+asyncpg", "postgresql+psycopg2"
)

_sync_engine = create_engine(
    _sync_url,
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
)

_SyncSessionFactory = sessionmaker(bind=_sync_engine, expire_on_commit=False)


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    """Yield a transactional synchronous SQLAlchemy session.

    Usage in tasks::

        with get_sync_session() as session:
            session.add(obj)
            session.commit()
    """
    session = _SyncSessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
