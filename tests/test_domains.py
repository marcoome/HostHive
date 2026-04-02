"""Tests for the domains router -- /api/v1/domains."""

from __future__ import annotations

import uuid

import pytest
from tests.conftest import auth_header

from api.models.domains import Domain


class TestCreateDomain:
    async def test_create_domain_returns_201(self, client, regular_user, user_token, fake_agent):
        resp = await client.post(
            "/api/v1/domains/",
            json={"domain_name": "example.com", "php_version": "8.2"},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["domain_name"] == "example.com"
        assert body["php_version"] == "8.2"
        assert body["user_id"] == str(regular_user.id)
        fake_agent.create_vhost.assert_awaited_once()

    async def test_create_domain_duplicate_returns_409(
        self, client, regular_user, user_token, db_session
    ):
        # Seed a domain
        domain = Domain(
            user_id=regular_user.id,
            domain_name="dup.com",
            document_root="/home/testuser/dup.com/public_html",
        )
        db_session.add(domain)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/domains/",
            json={"domain_name": "dup.com"},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()


class TestListDomains:
    async def test_user_sees_only_own_domains(
        self, client, regular_user, user_token, admin_user, admin_token, db_session
    ):
        # Create domains for both users
        d1 = Domain(
            user_id=regular_user.id,
            domain_name="usersite.com",
            document_root="/home/testuser/usersite.com/public_html",
        )
        d2 = Domain(
            user_id=admin_user.id,
            domain_name="adminsite.com",
            document_root="/home/admin/adminsite.com/public_html",
        )
        db_session.add_all([d1, d2])
        await db_session.commit()

        resp = await client.get(
            "/api/v1/domains/",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        domain_names = [d["domain_name"] for d in items]
        assert "usersite.com" in domain_names
        assert "adminsite.com" not in domain_names

    async def test_admin_sees_all_domains(
        self, client, regular_user, admin_user, admin_token, db_session
    ):
        d1 = Domain(
            user_id=regular_user.id,
            domain_name="u1.com",
            document_root="/home/testuser/u1.com/public_html",
        )
        d2 = Domain(
            user_id=admin_user.id,
            domain_name="a1.com",
            document_root="/home/admin/a1.com/public_html",
        )
        db_session.add_all([d1, d2])
        await db_session.commit()

        resp = await client.get(
            "/api/v1/domains/",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2


class TestDeleteDomain:
    async def test_delete_domain_returns_204(
        self, client, regular_user, user_token, db_session, fake_agent
    ):
        domain = Domain(
            user_id=regular_user.id,
            domain_name="todelete.com",
            document_root="/home/testuser/todelete.com/public_html",
        )
        db_session.add(domain)
        await db_session.commit()
        await db_session.refresh(domain)

        resp = await client.delete(
            f"/api/v1/domains/{domain.id}",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 204
        fake_agent.delete_vhost.assert_awaited_once_with("todelete.com")


class TestEnableSSL:
    async def test_enable_ssl_calls_agent(
        self, client, regular_user, user_token, db_session, fake_agent
    ):
        domain = Domain(
            user_id=regular_user.id,
            domain_name="ssltest.com",
            document_root="/home/testuser/ssltest.com/public_html",
        )
        db_session.add(domain)
        await db_session.commit()
        await db_session.refresh(domain)

        resp = await client.post(
            f"/api/v1/domains/{domain.id}/enable-ssl",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ssl_enabled"] is True
        assert body["ssl_cert_path"] is not None
        fake_agent.issue_ssl.assert_awaited_once_with("ssltest.com")


class TestDomainLogs:
    async def test_domain_logs_returns_lines(
        self, client, regular_user, user_token, db_session, fake_agent
    ):
        domain = Domain(
            user_id=regular_user.id,
            domain_name="logtest.com",
            document_root="/home/testuser/logtest.com/public_html",
        )
        db_session.add(domain)
        await db_session.commit()
        await db_session.refresh(domain)

        resp = await client.get(
            f"/api/v1/domains/{domain.id}/logs?log_type=access",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "logtest.com"
        assert body["log_type"] == "access"
        assert isinstance(body["lines"], list)
        fake_agent.read_file.assert_awaited_once()
