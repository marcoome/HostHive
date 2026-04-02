"""Tests for integrations and API keys routers."""

from __future__ import annotations

import pytest
from tests.conftest import auth_header

from api.models.integrations import ApiKey, ApiKeyScope, Integration, IntegrationName


# --------------------------------------------------------------------------
# GET /api/v1/integrations/ -- list integrations
# --------------------------------------------------------------------------


class TestListIntegrations:
    async def test_list_integrations_admin(
        self, client, admin_user, admin_token, db_session
    ):
        # Seed an integration
        integration = Integration(
            name=IntegrationName.CLOUDFLARE,
            is_enabled=False,
        )
        db_session.add(integration)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/integrations/",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        assert body[0]["name"] == "cloudflare"

    async def test_list_integrations_non_admin(
        self, client, regular_user, user_token
    ):
        resp = await client.get(
            "/api/v1/integrations/",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST /api/v1/integrations/{name}/toggle -- enable/disable
# --------------------------------------------------------------------------


class TestToggleIntegration:
    async def test_toggle_integration_enable_disable(
        self, client, admin_user, admin_token, db_session
    ):
        integration = Integration(
            name=IntegrationName.TELEGRAM,
            is_enabled=False,
        )
        db_session.add(integration)
        await db_session.commit()

        # Enable
        resp = await client.post(
            "/api/v1/integrations/telegram/toggle",
            json={"enabled": True},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is True

        # Disable
        resp = await client.post(
            "/api/v1/integrations/telegram/toggle",
            json={"enabled": False},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False


# --------------------------------------------------------------------------
# POST /api/v1/api-keys/ -- create API key
# --------------------------------------------------------------------------


class TestApiKeyCreate:
    async def test_api_key_create_returns_full_key_once(
        self, client, regular_user, user_token
    ):
        resp = await client.post(
            "/api/v1/api-keys/",
            json={"name": "My CI Key", "scope": "read_only"},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "key" in body
        assert body["key"].startswith("hh_")
        assert body["key_prefix"] == body["key"][:8]
        assert body["name"] == "My CI Key"
        assert body["scope"] == "read_only"


# --------------------------------------------------------------------------
# GET /api/v1/api-keys/ -- list API keys (prefix only)
# --------------------------------------------------------------------------


class TestApiKeyList:
    async def test_api_key_list_shows_prefix_only(
        self, client, regular_user, user_token
    ):
        # Create a key first
        create_resp = await client.post(
            "/api/v1/api-keys/",
            json={"name": "List Test Key"},
            headers=auth_header(user_token),
        )
        assert create_resp.status_code == 201

        # List keys
        resp = await client.get(
            "/api/v1/api-keys/",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        # List response should have key_prefix but NOT the full key
        key_item = body[0]
        assert "key_prefix" in key_item
        assert "key" not in key_item  # full key must NOT be in list response


# --------------------------------------------------------------------------
# DELETE /api/v1/api-keys/{id} -- revoke API key
# --------------------------------------------------------------------------


class TestApiKeyRevoke:
    async def test_api_key_revoke_key_no_longer_works(
        self, client, regular_user, user_token
    ):
        # Create a key
        create_resp = await client.post(
            "/api/v1/api-keys/",
            json={"name": "Revoke Test Key"},
            headers=auth_header(user_token),
        )
        assert create_resp.status_code == 201
        key_id = create_resp.json()["id"]

        # Revoke
        resp = await client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 204

        # List and verify the key is now inactive
        list_resp = await client.get(
            "/api/v1/api-keys/",
            headers=auth_header(user_token),
        )
        assert list_resp.status_code == 200
        keys = list_resp.json()
        revoked = [k for k in keys if k["id"] == key_id]
        assert len(revoked) == 1
        assert revoked[0]["is_active"] is False
