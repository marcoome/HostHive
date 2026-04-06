"""Tests for the WebAuthn / FIDO2 router -- /api/v1/auth/webauthn."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# POST /register/options
# --------------------------------------------------------------------------


class TestWebAuthnRegisterOptions:
    async def test_register_options_returns_challenge(self, client, admin_user, admin_token):
        """Registration options should return a valid PublicKeyCredentialCreationOptions."""
        resp = await client.post(
            "/api/v1/auth/webauthn/register/options",
            json={"device_name": "Test Key"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "options" in body
        options = body["options"]
        # Should contain standard WebAuthn fields
        assert "challenge" in options
        assert "rp" in options
        assert "user" in options
        assert "pubKeyCredParams" in options
        assert len(options["challenge"]) > 0

    async def test_register_options_unauthenticated(self, client):
        """Unauthenticated requests should be rejected."""
        resp = await client.post(
            "/api/v1/auth/webauthn/register/options",
            json={"device_name": "Test Key"},
        )
        assert resp.status_code == 401


# --------------------------------------------------------------------------
# GET /credentials
# --------------------------------------------------------------------------


class TestWebAuthnCredentialsList:
    async def test_credentials_list_empty(self, client, admin_user, admin_token):
        """A user with no credentials should get an empty list."""
        resp = await client.get(
            "/api/v1/auth/webauthn/credentials",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "credentials" in body
        assert body["credentials"] == []


# --------------------------------------------------------------------------
# DELETE /credentials/{credential_id}
# --------------------------------------------------------------------------


class TestWebAuthnCredentialsDelete:
    async def test_credentials_delete_nonexistent(self, client, admin_user, admin_token):
        """Deleting a nonexistent credential should return 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/auth/webauthn/credentials/{fake_id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_credentials_delete_unauthenticated(self, client):
        """Unauthenticated delete should be rejected."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/auth/webauthn/credentials/{fake_id}",
        )
        assert resp.status_code == 401


# --------------------------------------------------------------------------
# POST /login/options
# --------------------------------------------------------------------------


class TestWebAuthnLoginOptions:
    async def test_login_options_returns_challenge(self, client, admin_user):
        """Authentication options should return a challenge (no auth required)."""
        resp = await client.post(
            "/api/v1/auth/webauthn/login/options",
            json={"username": "admin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "options" in body
        options = body["options"]
        assert "challenge" in options
        # Should include a session_token for the verify step
        assert "session_token" in options

    async def test_login_options_unknown_user_still_returns_challenge(self, client):
        """Even for an unknown username, we should return a challenge (to avoid user enumeration)."""
        resp = await client.post(
            "/api/v1/auth/webauthn/login/options",
            json={"username": "nonexistent_user_xyz"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "options" in body
        assert "challenge" in body["options"]

    async def test_login_options_no_username(self, client):
        """When no username is provided, should still return a challenge for discoverable credentials."""
        resp = await client.post(
            "/api/v1/auth/webauthn/login/options",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "options" in body
        assert "challenge" in body["options"]
