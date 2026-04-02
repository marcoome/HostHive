"""Tests for the databases router -- /api/v1/databases."""

from __future__ import annotations

import pytest
from tests.conftest import auth_header

from api.core.security import hash_password
from api.models.databases import Database, DbType


class TestCreateDatabase:
    async def test_create_mysql_db_returns_201(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.post(
            "/api/v1/databases/",
            json={
                "db_name": "mydb_test",
                "db_user": "mydb_user",
                "db_password": "SecurePass123!@#",
                "db_type": "mysql",
            },
            headers=auth_header(user_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["db_name"] == "mydb_test"
        assert body["db_type"] == "mysql"
        fake_agent.create_database.assert_awaited_once()

    async def test_create_postgres_db_returns_201(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.post(
            "/api/v1/databases/",
            json={
                "db_name": "pgdb_test",
                "db_user": "pgdb_user",
                "db_password": "SecurePass123!@#",
                "db_type": "postgresql",
            },
            headers=auth_header(user_token),
        )
        assert resp.status_code == 201
        assert resp.json()["db_type"] == "postgresql"

    async def test_create_duplicate_db_returns_409(
        self, client, regular_user, user_token, db_session
    ):
        existing = Database(
            user_id=regular_user.id,
            db_name="existing_db",
            db_user="existing_user",
            db_password_encrypted=hash_password("password"),
            db_type=DbType.MYSQL,
        )
        db_session.add(existing)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/databases/",
            json={
                "db_name": "existing_db",
                "db_user": "another_user",
                "db_password": "SecurePass123!@#",
            },
            headers=auth_header(user_token),
        )
        assert resp.status_code == 409


class TestDeleteDatabase:
    async def test_delete_db_returns_204(
        self, client, regular_user, user_token, db_session, fake_agent
    ):
        db_record = Database(
            user_id=regular_user.id,
            db_name="todelete_db",
            db_user="del_user",
            db_password_encrypted=hash_password("password"),
            db_type=DbType.MYSQL,
        )
        db_session.add(db_record)
        await db_session.commit()
        await db_session.refresh(db_record)

        resp = await client.delete(
            f"/api/v1/databases/{db_record.id}",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 204
        fake_agent.delete_database.assert_awaited_once()


class TestResetPassword:
    async def test_reset_password_returns_new_password(
        self, client, regular_user, user_token, db_session, fake_agent
    ):
        db_record = Database(
            user_id=regular_user.id,
            db_name="resetpw_db",
            db_user="rp_user",
            db_password_encrypted=hash_password("oldpassword"),
            db_type=DbType.MYSQL,
        )
        db_session.add(db_record)
        await db_session.commit()
        await db_session.refresh(db_record)

        resp = await client.post(
            f"/api/v1/databases/{db_record.id}/reset-password",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "new_password" in body
        assert len(body["new_password"]) > 0
        assert body["db_name"] == "resetpw_db"
        fake_agent._request.assert_awaited()
