"""Tests for subdomain management -- /api/v1/domains/{id}/subdomains."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="subdomain-test.com"):
    """Create a top-level domain and return its id."""
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
    """Patch nginx_service calls used by subdomain endpoints."""
    return patch.multiple(
        "api.routers.domains.nginx_service",
        create_vhost=AsyncMock(return_value={"warnings": []}),
        delete_vhost=AsyncMock(return_value=None),
        update_vhost=AsyncMock(return_value={"warnings": []}),
        issue_letsencrypt=AsyncMock(return_value={
            "cert_path": "/etc/ssl/certs/sub.example.com.pem",
            "key_path": "/etc/ssl/private/sub.example.com.key",
        }),
        apply_ssl_to_nginx=AsyncMock(return_value=None),
        list_templates=lambda: ["default"],
    )


async def _create_subdomain(client, token, domain_id, prefix="blog", **overrides):
    """Create a subdomain and return the response."""
    payload = {
        "subdomain_prefix": prefix,
        "php_version": "8.2",
        "enable_ssl": False,
    }
    payload.update(overrides)
    with _patch_nginx():
        resp = await client.post(
            f"/api/v1/domains/{domain_id}/subdomains",
            json=payload,
            headers=auth_header(token),
        )
    return resp


# --------------------------------------------------------------------------
# POST -- create subdomain
# --------------------------------------------------------------------------


class TestCreateSubdomain:
    async def test_create_subdomain(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token)
        resp = await _create_subdomain(client, admin_token, domain_id, prefix="blog")
        assert resp.status_code == 201
        body = resp.json()
        assert body["domain_name"] == "blog.subdomain-test.com"
        assert body["is_subdomain"] is True
        assert body["parent_domain_id"] == domain_id

    async def test_create_subdomain_duplicate_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dup-sub.com")
        await _create_subdomain(client, admin_token, domain_id, prefix="www")
        resp = await _create_subdomain(client, admin_token, domain_id, prefix="www")
        assert resp.status_code == 409

    async def test_create_subdomain_with_custom_doc_root(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "custom-root.com")
        resp = await _create_subdomain(
            client, admin_token, domain_id,
            prefix="api",
            document_root="/home/admin/web/custom-root.com/api",
        )
        assert resp.status_code == 201
        assert resp.json()["document_root"] == "/home/admin/web/custom-root.com/api"


# --------------------------------------------------------------------------
# GET -- list subdomains
# --------------------------------------------------------------------------


class TestListSubdomains:
    async def test_list_subdomains(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "list-sub.com")
        await _create_subdomain(client, admin_token, domain_id, prefix="blog")
        await _create_subdomain(client, admin_token, domain_id, prefix="shop")

        resp = await client.get(
            f"/api/v1/domains/{domain_id}/subdomains",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        names = [item["domain_name"] for item in body["items"]]
        assert "blog.list-sub.com" in names
        assert "shop.list-sub.com" in names

    async def test_list_subdomains_empty(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "empty-sub.com")
        resp = await client.get(
            f"/api/v1/domains/{domain_id}/subdomains",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# --------------------------------------------------------------------------
# DELETE -- delete subdomain
# --------------------------------------------------------------------------


class TestDeleteSubdomain:
    async def test_delete_subdomain(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "del-sub.com")
        create_resp = await _create_subdomain(client, admin_token, domain_id, prefix="temp")
        sub_id = create_resp.json()["id"]

        with _patch_nginx():
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/subdomains/{sub_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 204

        # Verify it is gone
        list_resp = await client.get(
            f"/api/v1/domains/{domain_id}/subdomains",
            headers=auth_header(admin_token),
        )
        assert list_resp.json()["total"] == 0

    async def test_delete_nonexistent_subdomain(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "del-ne-sub.com")
        fake_id = str(uuid.uuid4())
        with _patch_nginx():
            resp = await client.delete(
                f"/api/v1/domains/{domain_id}/subdomains/{fake_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# Nested subdomains -- should be rejected
# --------------------------------------------------------------------------


class TestNoNestedSubdomains:
    async def test_no_nested_subdomains(self, client, admin_user, admin_token):
        """Creating a subdomain of a subdomain should be rejected."""
        domain_id = await _create_domain(client, admin_token, "nested-test.com")
        create_resp = await _create_subdomain(client, admin_token, domain_id, prefix="level1")
        sub_id = create_resp.json()["id"]

        # Try to create a subdomain under the subdomain
        with _patch_nginx():
            resp = await client.post(
                f"/api/v1/domains/{sub_id}/subdomains",
                json={"subdomain_prefix": "level2", "php_version": "8.2"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 400
        assert "subdomain of a subdomain" in resp.json()["detail"].lower()
