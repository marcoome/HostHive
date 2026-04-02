"""Tests for the WAF router -- /api/v1/waf."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from tests.conftest import auth_header


# --------------------------------------------------------------------------
# WAF enable / disable (mock agent)
# --------------------------------------------------------------------------


class TestWafEnableDisable:
    async def test_waf_enable_disable(
        self, client, admin_user, admin_token, fake_agent
    ):
        # Mock agent responses for WAF enable/disable
        fake_agent.post = AsyncMock(return_value={
            "ok": True,
            "data": {
                "domain": "example.com",
                "enabled": True,
                "mode": "block",
                "blocked_requests": 0,
            },
        })

        # Enable WAF
        resp = await client.post(
            "/api/v1/waf/example.com/enable",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "example.com"
        assert body["enabled"] is True

        # Disable WAF
        fake_agent.post = AsyncMock(return_value={
            "ok": True,
            "data": {
                "domain": "example.com",
                "enabled": False,
                "mode": "detect",
                "blocked_requests": 0,
            },
        })

        resp = await client.post(
            "/api/v1/waf/example.com/disable",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False

    async def test_waf_non_admin_gets_403(
        self, client, regular_user, user_token, fake_agent
    ):
        resp = await client.post(
            "/api/v1/waf/example.com/enable",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# WAF list rules
# --------------------------------------------------------------------------


class TestWafListRules:
    async def test_waf_list_rules(
        self, client, admin_user, admin_token, fake_agent
    ):
        fake_agent.get = AsyncMock(return_value={
            "data": {
                "domain": "example.com",
                "rules": [
                    {"id": "1", "type": "default", "rule": "deny all;"},
                    {"id": "2", "type": "custom", "rule": "allow 10.0.0.0/8;"},
                ],
                "total": 2,
            },
        })

        resp = await client.get(
            "/api/v1/waf/example.com/rules",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "example.com"
        assert len(body["rules"]) == 2
        assert body["total"] == 2


# --------------------------------------------------------------------------
# WAF stats
# --------------------------------------------------------------------------


class TestWafStats:
    async def test_waf_stats(
        self, client, admin_user, admin_token, fake_agent
    ):
        fake_agent.get = AsyncMock(return_value={
            "data": {
                "total_blocked": 1234,
                "top_attack_types": [{"sql_injection": 500}, {"xss": 300}],
                "top_ips": [{"192.168.1.100": 200}],
                "domains_with_waf": 5,
            },
        })

        resp = await client.get(
            "/api/v1/waf/stats",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_blocked"] == 1234
        assert body["domains_with_waf"] == 5
        assert isinstance(body["top_attack_types"], list)
        assert isinstance(body["top_ips"], list)
