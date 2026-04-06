"""Tests for the runtime apps router -- /api/v1/runtime."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="runtime-test.com"):
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


def _patch_runtime_system():
    """Context manager that patches subprocess calls and filesystem operations
    used during runtime app setup."""
    async def fake_run(cmd):
        # Return success for all shell commands
        if "version" in cmd or "--version" in cmd:
            return (0, "v20.0.0", "")
        if "systemctl show" in cmd:
            return (0, "12345", "")
        return (0, "", "")

    patches = patch.multiple(
        "api.routers.runtime",
        _run=AsyncMock(side_effect=fake_run),
        _setup_node_app=AsyncMock(return_value={"ok": True, "warnings": []}),
        _setup_python_app=AsyncMock(return_value={"ok": True, "warnings": []}),
        _configure_reverse_proxy=AsyncMock(return_value={"ok": True, "warnings": []}),
        _remove_service=AsyncMock(return_value=[]),
    )
    return patches


async def _create_app(client, token, domain_id, app_type="node", port=3000, **overrides):
    """Create a runtime app and return the response."""
    payload = {
        "domain_id": domain_id,
        "app_type": app_type,
        "app_name": "myapp",
        "app_root": f"/home/testuser/apps/{app_type}-app",
        "entry_point": "app.js" if app_type == "node" else "app.py",
        "runtime_version": "20" if app_type == "node" else "3.11",
        "port": port,
    }
    payload.update(overrides)
    with _patch_runtime_system():
        resp = await client.post(
            "/api/v1/runtime/apps",
            json=payload,
            headers=auth_header(token),
        )
    return resp


# --------------------------------------------------------------------------
# GET /versions -- list available runtime versions
# --------------------------------------------------------------------------


class TestListVersions:
    async def test_list_versions(self, client, admin_user, admin_token):
        async def fake_run(cmd):
            if "node --version" in cmd:
                return (0, "v20.0.0", "")
            if "python3." in cmd and "--version" in cmd:
                if "3.11" in cmd:
                    return (0, "Python 3.11.5", "")
                if "3.12" in cmd:
                    return (0, "Python 3.12.1", "")
                return (1, "", "not found")
            if "python3 --version" in cmd:
                return (0, "Python 3.11.5", "")
            return (1, "", "")

        with patch("api.routers.runtime._run", AsyncMock(side_effect=fake_run)):
            resp = await client.get(
                "/api/v1/runtime/versions",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "node" in body
        assert "python" in body
        assert isinstance(body["node"], list)
        assert isinstance(body["python"], list)
        assert len(body["node"]) >= 1
        assert len(body["python"]) >= 1


# --------------------------------------------------------------------------
# POST /apps -- create runtime app
# --------------------------------------------------------------------------


class TestCreateNodeApp:
    async def test_create_node_app(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "node-app.com")
        resp = await _create_app(client, admin_token, domain_id, app_type="node", port=3001)
        assert resp.status_code == 201
        body = resp.json()
        assert body["app_type"] == "node"
        assert body["port"] == 3001
        assert body["is_running"] is False
        assert "id" in body


class TestCreatePythonApp:
    async def test_create_python_app(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "python-app.com")
        resp = await _create_app(client, admin_token, domain_id, app_type="python", port=8001)
        assert resp.status_code == 201
        body = resp.json()
        assert body["app_type"] == "python"
        assert body["port"] == 8001
        assert body["runtime_version"] == "3.11"

    async def test_create_app_duplicate_port_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dup-port.com")
        await _create_app(client, admin_token, domain_id, app_type="node", port=4000)
        resp = await _create_app(client, admin_token, domain_id, app_type="python", port=4000)
        assert resp.status_code == 409


# --------------------------------------------------------------------------
# POST /apps/{id}/start, /stop, /restart
# --------------------------------------------------------------------------


class TestStartStopRestart:
    async def test_start_app(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "start-app.com")
        create_resp = await _create_app(client, admin_token, domain_id, port=5001)
        app_id = create_resp.json()["id"]

        async def fake_run(cmd):
            if "systemctl start" in cmd:
                return (0, "", "")
            if "systemctl show" in cmd:
                return (0, "99999", "")
            return (0, "", "")

        with patch("api.routers.runtime._run", AsyncMock(side_effect=fake_run)):
            resp = await client.post(
                f"/api/v1/runtime/apps/{app_id}/start",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["action"] == "start"
        assert body["pid"] == 99999

    async def test_stop_app(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "stop-app.com")
        create_resp = await _create_app(client, admin_token, domain_id, port=5002)
        app_id = create_resp.json()["id"]

        async def fake_run(cmd):
            return (0, "", "")

        with patch("api.routers.runtime._run", AsyncMock(side_effect=fake_run)):
            resp = await client.post(
                f"/api/v1/runtime/apps/{app_id}/stop",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["action"] == "stop"

    async def test_restart_app(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "restart-app.com")
        create_resp = await _create_app(client, admin_token, domain_id, port=5003)
        app_id = create_resp.json()["id"]

        async def fake_run(cmd):
            if "systemctl restart" in cmd:
                return (0, "", "")
            if "systemctl show" in cmd:
                return (0, "55555", "")
            return (0, "", "")

        with patch("api.routers.runtime._run", AsyncMock(side_effect=fake_run)):
            resp = await client.post(
                f"/api/v1/runtime/apps/{app_id}/restart",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["action"] == "restart"


# --------------------------------------------------------------------------
# POST /apps/{id}/install-deps
# --------------------------------------------------------------------------


class TestInstallDeps:
    async def test_install_deps_node_no_package_json(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "deps-node.com")
        create_resp = await _create_app(client, admin_token, domain_id, app_type="node", port=6001)
        app_id = create_resp.json()["id"]

        # Without a package.json on disk, it should fail with 400
        with patch("api.routers.runtime._run", AsyncMock(return_value=(0, "", ""))):
            resp = await client.post(
                f"/api/v1/runtime/apps/{app_id}/install-deps",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 400
        assert "package.json" in resp.json()["detail"]

    async def test_install_deps_python_no_requirements(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "deps-python.com")
        create_resp = await _create_app(client, admin_token, domain_id, app_type="python", port=6002)
        app_id = create_resp.json()["id"]

        with patch("api.routers.runtime._run", AsyncMock(return_value=(0, "", ""))):
            resp = await client.post(
                f"/api/v1/runtime/apps/{app_id}/install-deps",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 400
        assert "requirements.txt" in resp.json()["detail"]


# --------------------------------------------------------------------------
# GET /apps/{id}/logs
# --------------------------------------------------------------------------


class TestGetLogs:
    async def test_get_logs(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "logs-app.com")
        create_resp = await _create_app(client, admin_token, domain_id, port=7001)
        app_id = create_resp.json()["id"]

        async def fake_run(cmd):
            if "tail" in cmd and "stdout" in cmd:
                return (0, "line1\nline2\nline3", "")
            return (0, "", "")

        with patch("api.routers.runtime._run", AsyncMock(side_effect=fake_run)):
            resp = await client.get(
                f"/api/v1/runtime/apps/{app_id}/logs?log_type=stdout&lines=50",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "logs" in body
        assert "stdout" in body["logs"]
        assert len(body["logs"]["stdout"]) == 3

    async def test_get_logs_all(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "logs-all.com")
        create_resp = await _create_app(client, admin_token, domain_id, port=7002)
        app_id = create_resp.json()["id"]

        async def fake_run(cmd):
            if "stdout" in cmd:
                return (0, "stdout-line", "")
            if "stderr" in cmd:
                return (0, "stderr-line", "")
            return (0, "", "")

        with patch("api.routers.runtime._run", AsyncMock(side_effect=fake_run)):
            resp = await client.get(
                f"/api/v1/runtime/apps/{app_id}/logs?log_type=all",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "stdout" in body["logs"]
        assert "stderr" in body["logs"]
