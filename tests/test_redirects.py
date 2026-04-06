"""Tests for the redirects router -- /api/v1/domains/{domain_id}/redirects."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="redirect-test.com"):
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


async def _create_redirect(client, token, domain_id, **overrides):
    """Create a redirect and return the response body."""
    payload = {
        "source_path": "/old-page",
        "destination_url": "https://example.com/new-page",
        "redirect_type": 301,
        "is_regex": False,
        "is_active": True,
    }
    payload.update(overrides)
    with patch("api.routers.redirects.nginx_service") as mock_nginx:
        mock_nginx.update_vhost = AsyncMock(return_value={"warnings": []})
        resp = await client.post(
            f"/api/v1/domains/{domain_id}/redirects",
            json=payload,
            headers=auth_header(token),
        )
    return resp


# --------------------------------------------------------------------------
# POST -- create redirect
# --------------------------------------------------------------------------


class TestCreateRedirect:
    async def test_create_redirect(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token)
        resp = await _create_redirect(client, admin_token, domain_id)
        assert resp.status_code == 201
        body = resp.json()
        assert body["source_path"] == "/old-page"
        assert body["destination_url"] == "https://example.com/new-page"
        assert body["redirect_type"] == 301
        assert body["is_regex"] is False
        assert body["is_active"] is True
        assert "id" in body

    async def test_regex_redirect(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "regex-redir.com")
        resp = await _create_redirect(
            client, admin_token, domain_id,
            source_path="^/blog/(.*)",
            destination_url="https://newblog.com/$1",
            is_regex=True,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["is_regex"] is True
        assert body["source_path"] == "^/blog/(.*)"

    async def test_redirect_types(self, client, admin_user, admin_token):
        """Test 301, 302, 307 redirect types all work."""
        domain_id = await _create_domain(client, admin_token, "types-test.com")
        for code in (301, 302, 307):
            resp = await _create_redirect(
                client, admin_token, domain_id,
                source_path=f"/path-{code}",
                redirect_type=code,
            )
            assert resp.status_code == 201
            assert resp.json()["redirect_type"] == code

    async def test_invalid_redirect_type_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "invalid-type.com")
        resp = await _create_redirect(
            client, admin_token, domain_id,
            redirect_type=308,
        )
        assert resp.status_code == 422


# --------------------------------------------------------------------------
# GET -- list redirects
# --------------------------------------------------------------------------


class TestListRedirects:
    async def test_list_redirects(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "list-redir.com")
        await _create_redirect(client, admin_token, domain_id, source_path="/a")
        await _create_redirect(client, admin_token, domain_id, source_path="/b")

        resp = await client.get(
            f"/api/v1/domains/{domain_id}/redirects",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    async def test_list_redirects_empty(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "empty-redir.com")
        resp = await client.get(
            f"/api/v1/domains/{domain_id}/redirects",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# --------------------------------------------------------------------------
# PUT -- update redirect
# --------------------------------------------------------------------------


class TestUpdateRedirect:
    async def test_update_redirect(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "update-redir.com")
        create_resp = await _create_redirect(client, admin_token, domain_id)
        redirect_id = create_resp.json()["id"]

        with patch("api.routers.redirects.nginx_service") as mock_nginx:
            mock_nginx.update_vhost = AsyncMock(return_value={"warnings": []})
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/redirects/{redirect_id}",
                json={
                    "destination_url": "https://example.com/updated",
                    "redirect_type": 302,
                },
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["destination_url"] == "https://example.com/updated"
        assert body["redirect_type"] == 302

    async def test_update_nonexistent_redirect(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "update-ne-redir.com")
        fake_id = str(uuid.uuid4())
        with patch("api.routers.redirects.nginx_service") as mock_nginx:
            mock_nginx.update_vhost = AsyncMock(return_value={"warnings": []})
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/redirects/{fake_id}",
                json={"destination_url": "https://x.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# DELETE -- delete redirect
# --------------------------------------------------------------------------


class TestDeleteRedirect:
    async def test_delete_redirect(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "del-redir.com")
        create_resp = await _create_redirect(client, admin_token, domain_id)
        redirect_id = create_resp.json()["id"]

        with patch("api.routers.redirects.nginx_service") as mock_nginx:
            mock_nginx.update_vhost = AsyncMock(return_value={"warnings": []})
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/redirects/{redirect_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 204

        # Verify it is gone
        list_resp = await client.get(
            f"/api/v1/domains/{domain_id}/redirects",
            headers=auth_header(admin_token),
        )
        assert list_resp.json()["total"] == 0

    async def test_delete_nonexistent_redirect(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "del-ne-redir.com")
        fake_id = str(uuid.uuid4())
        with patch("api.routers.redirects.nginx_service") as mock_nginx:
            mock_nginx.update_vhost = AsyncMock(return_value={"warnings": []})
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/redirects/{fake_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 404
