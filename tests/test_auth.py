"""Tests for the authentication router -- /api/v1/auth."""

from __future__ import annotations

import pytest
from tests.conftest import auth_header


# --------------------------------------------------------------------------
# POST /login
# --------------------------------------------------------------------------


class TestLogin:
    async def test_login_valid_credentials(self, client, admin_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0

    async def test_login_invalid_password(self, client, admin_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "WrongPassword123!"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    async def test_login_nonexistent_user(self, client):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "Whatever123!@#"},
        )
        assert resp.status_code == 401

    async def test_login_suspended_user(self, client, suspended_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "suspended", "password": "Suspended12345!@#"},
        )
        assert resp.status_code == 403
        assert "suspended" in resp.json()["detail"].lower() or "inactive" in resp.json()["detail"].lower()

    async def test_brute_force_lockout(self, client, admin_user, fake_redis):
        """After 5 failed attempts the IP should be locked out (429)."""
        for i in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": f"wrong{i}!!Aa1"},
            )

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        assert resp.status_code == 429
        assert "Too many" in resp.json()["detail"]


# --------------------------------------------------------------------------
# POST /refresh
# --------------------------------------------------------------------------


class TestRefresh:
    async def test_refresh_token_returns_new_tokens(self, client, admin_user):
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        assert login.status_code == 200
        refresh_tok = login.json()["refresh_token"]

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_tok},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        # New refresh token should differ from old one
        assert body["refresh_token"] != refresh_tok

    async def test_refresh_invalid_token(self, client):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "not.a.valid.jwt.token"},
        )
        assert resp.status_code == 401


# --------------------------------------------------------------------------
# POST /logout
# --------------------------------------------------------------------------


class TestLogout:
    async def test_logout_invalidates_refresh_token(self, client, admin_user, admin_token):
        # Login to get a refresh token
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        refresh_tok = login.json()["refresh_token"]
        access_tok = login.json()["access_token"]

        # Logout
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_tok},
            headers=auth_header(access_tok),
        )
        assert resp.status_code == 204

        # Refresh should now fail
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_tok},
        )
        assert resp.status_code == 401


# --------------------------------------------------------------------------
# POST /change-password
# --------------------------------------------------------------------------


class TestChangePassword:
    async def test_change_password_success(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Admin12345!@#",
                "new_password": "NewAdmin12345!@#",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert "changed" in resp.json()["detail"].lower()

    async def test_change_password_wrong_old_password(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "WrongOldPwd123!@#",
                "new_password": "NewAdmin12345!@#",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "incorrect" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------
# GET /me
# --------------------------------------------------------------------------


class TestMe:
    async def test_me_returns_current_user_info(self, client, admin_user, admin_token):
        resp = await client.get(
            "/api/v1/auth/me",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "admin"
        assert body["email"] == "admin@test.com"
        assert body["role"] == "admin"

    async def test_unauthenticated_request_returns_401(self, client):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401
