"""Shared test fixtures for the HostHive test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.core.database import Base, get_db
from api.core.security import create_access_token, hash_password
from api.models.users import User, UserRole

# ---------------------------------------------------------------------------
# In-memory SQLite for isolation
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fake Redis (in-memory dict that mimics the async redis interface)
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async Redis stub for testing without a running Redis server."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = str(value)
        if ex is not None:
            self._ttl[key] = ex

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = str(value)
        self._ttl[key] = ttl

    async def incr(self, key: str) -> int:
        val = int(self._store.get(key, "0")) + 1
        self._store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> None:
        self._ttl[key] = seconds

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)
            self._ttl.pop(k, None)

    async def scan(self, cursor: int, match: str = "*", count: int = 100):
        import fnmatch

        matched = [k for k in self._store if fnmatch.fnmatch(k, match)]
        return (0, matched)

    async def aclose(self) -> None:
        pass

    def pipeline(self) -> "FakeRedisPipeline":
        return FakeRedisPipeline(self)

    def clear(self) -> None:
        self._store.clear()
        self._ttl.clear()


class FakeRedisPipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list = []

    def incr(self, key: str):
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, seconds: int):
        self._ops.append(("expire", key, seconds))
        return self

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            if op[0] == "incr":
                results.append(await self._redis.incr(op[1]))
            elif op[0] == "expire":
                await self._redis.expire(op[1], op[2])
                results.append(True)
        return results


# ---------------------------------------------------------------------------
# Fake Agent Client
# ---------------------------------------------------------------------------


def make_fake_agent() -> AsyncMock:
    """Create an AsyncMock that mimics the AgentClient interface."""
    agent = AsyncMock()
    agent.create_vhost.return_value = {"status": "ok"}
    agent.delete_vhost.return_value = {"status": "ok"}
    agent.update_vhost.return_value = {"status": "ok"}
    agent.create_database.return_value = {"status": "ok"}
    agent.delete_database.return_value = {"status": "ok"}
    agent.issue_ssl.return_value = {
        "status": "ok",
        "cert_path": "/etc/ssl/certs/example.com.pem",
        "key_path": "/etc/ssl/private/example.com.key",
    }
    agent.read_file.return_value = {
        "content": "line1\nline2\nline3\n",
        "encoding": "utf-8",
    }
    agent.write_file.return_value = {"status": "ok"}
    agent.list_files.return_value = {
        "items": [
            {"name": "index.html", "path": "/home/testuser/index.html", "is_dir": False, "size": 100},
        ],
    }
    agent._request.return_value = {"status": "ok"}
    agent.close.return_value = None
    agent.delete_mailbox.return_value = {"status": "ok"}
    agent.delete_ftp_account.return_value = {"status": "ok"}
    return agent


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis():
    return FakeRedis()


@pytest_asyncio.fixture
async def fake_agent():
    return make_fake_agent()


@pytest_asyncio.fixture
async def client(db_session, fake_redis, fake_agent):
    from api.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Patch app.state
    app.state.redis = fake_redis
    app.state.agent = fake_agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_user(db_session):
    user = User(
        username="admin",
        email="admin@test.com",
        password_hash=hash_password("Admin12345!@#"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_token(admin_user):
    return create_access_token(admin_user.id, "admin", admin_user.password_changed_at)


@pytest_asyncio.fixture
async def regular_user(db_session):
    user = User(
        username="testuser",
        email="user@test.com",
        password_hash=hash_password("User12345!@#"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_token(regular_user):
    return create_access_token(regular_user.id, "user", regular_user.password_changed_at)


@pytest_asyncio.fixture
async def suspended_user(db_session):
    user = User(
        username="suspended",
        email="suspended@test.com",
        password_hash=hash_password("Suspended12345!@#"),
        role=UserRole.USER,
        is_active=True,
        is_suspended=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
