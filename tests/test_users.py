"""Tests for the users router -- /api/v1/users (admin only)."""

from __future__ import annotations

import pytest
from tests.conftest import auth_header


class TestListUsers:
    async def test_list_users_admin_gets_paginated_list(self, client, admin_user, admin_token):
        resp = await client.get(
            "/api/v1/users/",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] >= 1
        assert body["page"] == 1
        assert body["per_page"] == 50

    async def test_list_users_non_admin_gets_403(self, client, regular_user, user_token):
        resp = await client.get(
            "/api/v1/users/",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


class TestCreateUser:
    async def test_create_user_returns_201(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/users/",
            json={
                "username": "newuser",
                "email": "newuser@test.com",
                "password": "Newuser12345!@#",
                "role": "user",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "newuser"
        assert body["email"] == "newuser@test.com"
        assert body["role"] == "user"

    async def test_create_user_duplicate_username_returns_409(
        self, client, admin_user, admin_token
    ):
        # First creation
        await client.post(
            "/api/v1/users/",
            json={
                "username": "dupuser",
                "email": "dup1@test.com",
                "password": "DupUser12345!@#",
            },
            headers=auth_header(admin_token),
        )
        # Duplicate
        resp = await client.post(
            "/api/v1/users/",
            json={
                "username": "dupuser",
                "email": "dup2@test.com",
                "password": "DupUser12345!@#",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()


class TestGetUser:
    async def test_get_user_detail(self, client, admin_user, admin_token, regular_user):
        resp = await client.get(
            f"/api/v1/users/{regular_user.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "testuser"


class TestUpdateUser:
    async def test_update_user(self, client, admin_user, admin_token, regular_user):
        resp = await client.put(
            f"/api/v1/users/{regular_user.id}",
            json={"email": "updated@test.com"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "updated@test.com"


class TestDeleteUser:
    async def test_delete_user_returns_204(self, client, admin_user, admin_token, regular_user):
        resp = await client.delete(
            f"/api/v1/users/{regular_user.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 204

        # Verify user no longer exists
        resp = await client.get(
            f"/api/v1/users/{regular_user.id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


class TestSuspendUnsuspend:
    async def test_suspend_user(self, client, admin_user, admin_token, regular_user):
        resp = await client.post(
            f"/api/v1/users/{regular_user.id}/suspend",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["is_suspended"] is True

    async def test_unsuspend_user(self, client, admin_user, admin_token, suspended_user):
        resp = await client.post(
            f"/api/v1/users/{suspended_user.id}/unsuspend",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["is_suspended"] is False


class TestUserAccessControl:
    async def test_regular_user_cannot_access_admin_endpoints(
        self, client, regular_user, user_token
    ):
        """A non-admin user should receive 403 on all /users/ admin endpoints."""
        resp = await client.post(
            "/api/v1/users/",
            json={
                "username": "hacker",
                "email": "hacker@test.com",
                "password": "Hacker12345!@#",
            },
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403
