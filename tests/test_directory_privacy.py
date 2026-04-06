"""Tests for the directory privacy router -- /api/v1/domains/{domain_id}/directory-privacy."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="dp-test.com"):
    """Create a domain and return its id."""
    with patch("api.routers.domains.nginx_service") as mock_nginx:
        mock_nginx.create_vhost = AsyncMock(return_value={"warnings": []})
        mock_nginx.list_templates.return_value = ["default"]
        resp = await client.post(
            "/api/v1/domains",
            json={"domain_name": domain_name, "php_version": "8.2"},
            headers=auth_header(token),
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _patch_nginx():
    """Patch nginx_service calls used by directory privacy."""
    return patch.multiple(
        "api.routers.directory_privacy.nginx_service",
        sync_directory_privacy=AsyncMock(return_value=None),
        generate_htpasswd_hash=lambda pw: f"$apr1$fake${pw}",
        remove_htpasswd_file=AsyncMock(return_value=None),
    )


async def _protect_dir(client, token, domain_id, path="/admin", auth_name="Restricted"):
    """Create a directory privacy rule and return the response."""
    with _patch_nginx():
        resp = await client.post(
            f"/api/v1/domains/{domain_id}/directory-privacy",
            json={"path": path, "auth_name": auth_name},
            headers=auth_header(token),
        )
    return resp


# --------------------------------------------------------------------------
# POST -- protect directory
# --------------------------------------------------------------------------


class TestProtectDirectory:
    async def test_protect_directory(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token)
        resp = await _protect_dir(client, admin_token, domain_id)
        assert resp.status_code == 201
        body = resp.json()
        assert body["path"] == "/admin"
        assert body["auth_name"] == "Restricted"
        assert body["is_active"] is True
        assert body["user_count"] == 0
        assert "id" in body

    async def test_protect_directory_normalizes_path(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-normalize.com")
        resp = await _protect_dir(client, admin_token, domain_id, path="admin/")
        assert resp.status_code == 201
        assert resp.json()["path"] == "/admin"

    async def test_duplicate_path_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-dup.com")
        await _protect_dir(client, admin_token, domain_id, path="/secret")
        resp = await _protect_dir(client, admin_token, domain_id, path="/secret")
        assert resp.status_code == 409


# --------------------------------------------------------------------------
# POST .../users -- add user
# --------------------------------------------------------------------------


class TestAddUser:
    async def test_add_user(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-adduser.com")
        dp_resp = await _protect_dir(client, admin_token, domain_id)
        dp_id = dp_resp.json()["id"]

        with _patch_nginx():
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}/users",
                json={"username": "testuser", "password": "secret123"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["user_count"] == 1
        assert body["users"][0]["username"] == "testuser"

    async def test_add_duplicate_user_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-dupuser.com")
        dp_resp = await _protect_dir(client, admin_token, domain_id)
        dp_id = dp_resp.json()["id"]

        with _patch_nginx():
            await client.post(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}/users",
                json={"username": "alice", "password": "secret"},
                headers=auth_header(admin_token),
            )
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}/users",
                json={"username": "alice", "password": "other"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 409


# --------------------------------------------------------------------------
# DELETE .../users/{username} -- remove user
# --------------------------------------------------------------------------


class TestRemoveUser:
    async def test_remove_user(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-rmuser.com")
        dp_resp = await _protect_dir(client, admin_token, domain_id)
        dp_id = dp_resp.json()["id"]

        with _patch_nginx():
            # Add user first
            await client.post(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}/users",
                json={"username": "bob", "password": "secret"},
                headers=auth_header(admin_token),
            )
            # Remove user
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}/users/bob",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        assert resp.json()["user_count"] == 0

    async def test_remove_nonexistent_user(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-rmne.com")
        dp_resp = await _protect_dir(client, admin_token, domain_id)
        dp_id = dp_resp.json()["id"]

        with _patch_nginx():
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}/users/ghost",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# PUT -- toggle active
# --------------------------------------------------------------------------


class TestToggleActive:
    async def test_toggle_active(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-toggle.com")
        dp_resp = await _protect_dir(client, admin_token, domain_id)
        dp_id = dp_resp.json()["id"]
        assert dp_resp.json()["is_active"] is True

        with _patch_nginx():
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}",
                json={"is_active": False},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # Toggle back on
        with _patch_nginx():
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}",
                json={"is_active": True},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True


# --------------------------------------------------------------------------
# DELETE -- remove protection
# --------------------------------------------------------------------------


class TestDeleteProtection:
    async def test_delete_protection(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-delete.com")
        dp_resp = await _protect_dir(client, admin_token, domain_id)
        dp_id = dp_resp.json()["id"]

        with _patch_nginx():
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/directory-privacy/{dp_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 204

        # Verify it is gone
        resp = await client.get(
            f"/api/v1/domains/{domain_id}/directory-privacy",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

    async def test_delete_nonexistent_protection(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dp-delne.com")
        fake_id = str(uuid.uuid4())
        with _patch_nginx():
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/directory-privacy/{fake_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 404
