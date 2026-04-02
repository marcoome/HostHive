"""Tests for the file manager router -- /api/v1/files."""

from __future__ import annotations

import pytest
from tests.conftest import auth_header

from api.core.security import create_access_token, hash_password
from api.models.users import User, UserRole


# --------------------------------------------------------------------------
# GET /list -- directory listing
# --------------------------------------------------------------------------


class TestListDirectory:
    async def test_list_directory_returns_files(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.get(
            "/api/v1/files/list?path=/",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] >= 1
        assert body["items"][0]["name"] == "index.html"
        fake_agent.list_files.assert_awaited_once()


# --------------------------------------------------------------------------
# GET /read -- read file content
# --------------------------------------------------------------------------


class TestReadFile:
    async def test_read_file_returns_content(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.get(
            "/api/v1/files/read?path=/index.html",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        assert "line1" in body["content"]
        fake_agent.read_file.assert_awaited_once()


# --------------------------------------------------------------------------
# PUT /write -- write file content
# --------------------------------------------------------------------------


class TestWriteFile:
    async def test_write_file_updated(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.put(
            "/api/v1/files/write",
            json={"path": "/index.html", "content": "<h1>Hello</h1>"},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "written" in body["detail"].lower() or "file" in body["detail"].lower()
        fake_agent.write_file.assert_awaited_once()


# --------------------------------------------------------------------------
# Path traversal
# --------------------------------------------------------------------------


class TestPathTraversalBlocked:
    async def test_path_traversal_blocked(self, client, regular_user, user_token):
        resp = await client.get(
            "/api/v1/files/read?path=../../../etc/passwd",
            headers=auth_header(user_token),
        )
        assert resp.status_code in (400, 403, 422)


# --------------------------------------------------------------------------
# POST /upload -- file upload
# --------------------------------------------------------------------------


class TestUploadFile:
    async def test_upload_file(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.post(
            "/api/v1/files/upload?path=/",
            files={"file": ("test.txt", b"file content", "text/plain")},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "uploaded" in body["detail"].lower() or "file" in body["detail"].lower()
        fake_agent.write_file.assert_awaited_once()


# --------------------------------------------------------------------------
# DELETE /delete -- remove file
# --------------------------------------------------------------------------


class TestDeleteFile:
    async def test_delete_file_removed(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.request(
            "DELETE",
            "/api/v1/files/delete",
            json={"path": "/old-file.txt"},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 204
        fake_agent._request.assert_awaited()


# --------------------------------------------------------------------------
# User sandboxing
# --------------------------------------------------------------------------


class TestUserSandboxedToHome:
    async def test_user_sandboxed_to_home_cannot_access_other_users_files(
        self, client, regular_user, user_token
    ):
        """A non-admin user must not be able to read files outside /home/{username}/."""
        resp = await client.get(
            "/api/v1/files/read?path=/home/otheruser/secret.txt",
            headers=auth_header(user_token),
        )
        # The path /home/otheruser/ is outside /home/testuser/ so should be blocked
        assert resp.status_code in (400, 403, 422)
