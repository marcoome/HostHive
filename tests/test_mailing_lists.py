"""Tests for the mailing lists router -- /api/v1/email/lists."""

from __future__ import annotations

import uuid

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="mail-test.com"):
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


def _patch_exim():
    """Patch the Exim alias sync so it does not import the agent module."""
    return patch("api.routers.mailing_lists._sync_exim_aliases", return_value=None)


async def _create_list(client, token, domain_id, name="announcements"):
    """Create a mailing list and return the response body."""
    with _patch_exim():
        resp = await client.post(
            "/api/v1/email/lists",
            json={
                "domain_id": domain_id,
                "name": name,
                "owner_email": "admin@test.com",
            },
            headers=auth_header(token),
        )
    return resp


# --------------------------------------------------------------------------
# POST /lists -- create mailing list
# --------------------------------------------------------------------------


class TestCreateList:
    async def test_create_list(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token)
        resp = await _create_list(client, admin_token, domain_id)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "announcements"
        assert body["list_address"] == "announcements@mail-test.com"
        assert body["owner_email"] == "admin@test.com"
        assert body["is_active"] is True
        assert "id" in body

    async def test_create_duplicate_list_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dup-list.com")
        await _create_list(client, admin_token, domain_id, name="news")
        resp = await _create_list(client, admin_token, domain_id, name="news")
        assert resp.status_code == 409

    async def test_create_list_invalid_domain(self, client, admin_user, admin_token):
        fake_domain_id = str(uuid.uuid4())
        with _patch_exim():
            resp = await client.post(
                "/api/v1/email/lists",
                json={
                    "domain_id": fake_domain_id,
                    "name": "test",
                    "owner_email": "admin@test.com",
                },
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# GET /lists -- list mailing lists
# --------------------------------------------------------------------------


class TestListLists:
    async def test_list_lists(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "listall.com")
        await _create_list(client, admin_token, domain_id, name="list1")
        await _create_list(client, admin_token, domain_id, name="list2")

        resp = await client.get(
            "/api/v1/email/lists",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        # At least the 2 we created
        names = [item["name"] for item in body]
        assert "list1" in names
        assert "list2" in names


# --------------------------------------------------------------------------
# POST /lists/{id}/members -- add members (bulk)
# --------------------------------------------------------------------------


class TestAddMembersBulk:
    async def test_add_members_bulk(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "bulk-members.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        with _patch_exim():
            resp = await client.post(
                f"/api/v1/email/lists/{list_id}/members",
                json={
                    "emails": ["alice@example.com", "bob@example.com", "carol@example.com"],
                },
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body) == 3
        emails = {m["email"] for m in body}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        assert "carol@example.com" in emails

    async def test_add_duplicate_member_skipped(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "dup-member.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        with _patch_exim():
            await client.post(
                f"/api/v1/email/lists/{list_id}/members",
                json={"emails": ["alice@example.com"]},
                headers=auth_header(admin_token),
            )
            # Add the same email again
            resp = await client.post(
                f"/api/v1/email/lists/{list_id}/members",
                json={"emails": ["alice@example.com", "new@example.com"]},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 201
        body = resp.json()
        # Only the new member should be returned
        assert len(body) == 1
        assert body[0]["email"] == "new@example.com"


# --------------------------------------------------------------------------
# DELETE /lists/{id}/members/{member_id} -- remove member
# --------------------------------------------------------------------------


class TestRemoveMember:
    async def test_remove_member(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "rm-member.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        with _patch_exim():
            add_resp = await client.post(
                f"/api/v1/email/lists/{list_id}/members",
                json={"emails": ["removeme@example.com"]},
                headers=auth_header(admin_token),
            )
        member_id = add_resp.json()[0]["id"]

        with _patch_exim():
            resp = await client.delete(
                f"/api/v1/email/lists/{list_id}/members/{member_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 204

    async def test_remove_nonexistent_member(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "rm-ne-member.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/api/v1/email/lists/{list_id}/members/{fake_id}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# DELETE /lists/{id} -- delete mailing list
# --------------------------------------------------------------------------


class TestDeleteList:
    async def test_delete_list(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "del-list.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        with patch("api.routers.mailing_lists.remove_mailing_list_aliases", create=True):
            resp = await client.delete(
                f"/api/v1/email/lists/{list_id}",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 204


# --------------------------------------------------------------------------
# POST /lists/{id}/send -- send message to list
# --------------------------------------------------------------------------


class TestSendToList:
    async def test_send_to_list(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "send-list.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        # Add a member first
        with _patch_exim():
            await client.post(
                f"/api/v1/email/lists/{list_id}/members",
                json={"emails": ["recipient@example.com"]},
                headers=auth_header(admin_token),
            )

        with patch("api.routers.mailing_lists.send_list_message", create=True) as mock_send:
            mock_send.return_value = {"ok": True}
            resp = await client.post(
                f"/api/v1/email/lists/{list_id}/send",
                json={
                    "subject": "Test Announcement",
                    "body": "Hello, this is a test message.",
                },
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["recipients"] == 1
        assert body["subject"] == "Test Announcement"

    async def test_send_to_empty_list_fails(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "send-empty.com")
        create_resp = await _create_list(client, admin_token, domain_id)
        list_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/email/lists/{list_id}/send",
            json={
                "subject": "Test",
                "body": "Hello",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "no members" in resp.json()["detail"].lower()
