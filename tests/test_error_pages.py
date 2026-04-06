"""Tests for custom error pages -- /api/v1/domains/{id}/error-pages."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="errpages-test.com"):
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
    """Patch nginx_service.update_vhost for error-page regeneration."""
    return patch(
        "api.routers.domains.nginx_service.update_vhost",
        AsyncMock(return_value={"warnings": []}),
    )


# --------------------------------------------------------------------------
# GET /error-pages -- get current error page config
# --------------------------------------------------------------------------


class TestGetErrorPages:
    async def test_get_error_pages_default(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token)
        resp = await client.get(
            f"/api/v1/domains/{domain_id}/error-pages",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "errpages-test.com"
        assert body["error_pages"] == {}

    async def test_get_error_pages_after_set(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "errpages-get.com")

        with _patch_nginx():
            await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={"error_pages": {404: "/custom_404.html", 500: "/custom_500.html"}},
                headers=auth_header(admin_token),
            )

        resp = await client.get(
            f"/api/v1/domains/{domain_id}/error-pages",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        # Keys are stored as strings in JSON
        assert body["error_pages"]["404"] == "/custom_404.html"
        assert body["error_pages"]["500"] == "/custom_500.html"


# --------------------------------------------------------------------------
# PUT /error-pages -- update error pages
# --------------------------------------------------------------------------


class TestUpdateErrorPages:
    async def test_update_error_pages(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "errpages-update.com")

        with _patch_nginx():
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={
                    "error_pages": {
                        404: "/errors/404.html",
                        403: "/errors/403.html",
                        502: "/errors/502.html",
                    }
                },
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "errpages-update.com"
        assert body["error_pages"]["404"] == "/errors/404.html"
        assert body["error_pages"]["403"] == "/errors/403.html"
        assert body["error_pages"]["502"] == "/errors/502.html"

    async def test_update_error_pages_overwrite(self, client, admin_user, admin_token):
        """Updating error pages replaces the entire mapping."""
        domain_id = await _create_domain(client, admin_token, "errpages-overwrite.com")

        with _patch_nginx():
            # Set initial
            await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={"error_pages": {404: "/404.html", 500: "/500.html"}},
                headers=auth_header(admin_token),
            )
            # Overwrite with different set
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={"error_pages": {503: "/maintenance.html"}},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        # Only the new mapping should exist
        assert body["error_pages"].get("503") == "/maintenance.html"
        assert "404" not in body["error_pages"]
        assert "500" not in body["error_pages"]

    async def test_update_error_pages_all_valid_codes(self, client, admin_user, admin_token):
        """All allowed HTTP error codes should be accepted."""
        domain_id = await _create_domain(client, admin_token, "errpages-allcodes.com")
        allowed_codes = [400, 401, 403, 404, 405, 408, 410, 413, 429, 500, 501, 502, 503, 504]
        pages = {code: f"/{code}.html" for code in allowed_codes}

        with _patch_nginx():
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={"error_pages": pages},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["error_pages"]) == len(allowed_codes)


# --------------------------------------------------------------------------
# Invalid error codes
# --------------------------------------------------------------------------


class TestInvalidCode:
    async def test_invalid_error_code_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "errpages-invalid.com")

        resp = await client.put(
            f"/api/v1/domains/{domain_id}/error-pages",
            json={"error_pages": {418: "/teapot.html"}},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_multiple_invalid_codes_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "errpages-multi-inv.com")

        resp = await client.put(
            f"/api/v1/domains/{domain_id}/error-pages",
            json={"error_pages": {200: "/ok.html", 301: "/moved.html"}},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_mix_valid_and_invalid_codes_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "errpages-mix.com")

        resp = await client.put(
            f"/api/v1/domains/{domain_id}/error-pages",
            json={"error_pages": {404: "/404.html", 418: "/teapot.html"}},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_empty_error_pages_clears_config(self, client, admin_user, admin_token):
        """Sending an empty mapping should clear custom error pages."""
        domain_id = await _create_domain(client, admin_token, "errpages-clear.com")

        with _patch_nginx():
            # Set some pages
            await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={"error_pages": {404: "/404.html"}},
                headers=auth_header(admin_token),
            )
            # Clear
            resp = await client.put(
                f"/api/v1/domains/{domain_id}/error-pages",
                json={"error_pages": {}},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        assert resp.json()["error_pages"] == {}
