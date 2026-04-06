"""Tests for the email deliverability router -- /api/v1/email/deliverability."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from api.schemas.email_deliverability import (
    CheckStatus,
    DeliverabilityCheck,
    DeliverabilityReport,
)
from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_report(domain="example.com", score=85, checks=None):
    """Build a DeliverabilityReport for mocking."""
    if checks is None:
        checks = [
            DeliverabilityCheck(
                name="SPF Record",
                status=CheckStatus.PASS,
                details='v=spf1 include:_spf.google.com ~all',
                recommendation="",
            ),
            DeliverabilityCheck(
                name="DKIM Record",
                status=CheckStatus.PASS,
                details="DKIM record found for selector 'default'",
                recommendation="",
            ),
            DeliverabilityCheck(
                name="DMARC Record",
                status=CheckStatus.PASS,
                details="v=DMARC1; p=reject; rua=mailto:dmarc@example.com",
                recommendation="",
            ),
            DeliverabilityCheck(
                name="MX Records",
                status=CheckStatus.PASS,
                details="10 mail.example.com.",
                recommendation="",
            ),
            DeliverabilityCheck(
                name="Blacklist Check",
                status=CheckStatus.PASS,
                details="Not listed on any checked blacklists",
                recommendation="",
            ),
        ]
    return DeliverabilityReport(
        domain=domain,
        score=score,
        checks=checks,
        tested_at=datetime.now(timezone.utc),
    )


def _patch_deliverability_service(report=None):
    """Patch the run_deliverability_test service function."""
    if report is None:
        report = _make_report()
    return patch(
        "api.routers.email_deliverability.run_deliverability_test",
        AsyncMock(return_value=report),
    )


# --------------------------------------------------------------------------
# POST /test -- run deliverability test
# --------------------------------------------------------------------------


class TestRunDeliverabilityTest:
    async def test_run_deliverability_test(self, client, admin_user, admin_token):
        report = _make_report("test-domain.com", score=90)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "test-domain.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "test-domain.com"
        assert body["score"] == 90
        assert isinstance(body["checks"], list)
        assert len(body["checks"]) == 5
        assert "tested_at" in body

    async def test_run_deliverability_test_low_score(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="SPF Record",
                status=CheckStatus.FAIL,
                details="No SPF record found",
                recommendation="Add a TXT record: v=spf1 ...",
            ),
            DeliverabilityCheck(
                name="DKIM Record",
                status=CheckStatus.FAIL,
                details="No DKIM record found",
                recommendation="Configure DKIM signing",
            ),
        ]
        report = _make_report("bad-domain.com", score=20, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "bad-domain.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["score"] == 20
        failing = [c for c in body["checks"] if c["status"] == "fail"]
        assert len(failing) == 2

    async def test_run_deliverability_test_service_error(self, client, admin_user, admin_token):
        with patch(
            "api.routers.email_deliverability.run_deliverability_test",
            AsyncMock(side_effect=Exception("DNS timeout")),
        ):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "timeout.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 500
        assert "failed" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------
# GET /report/{domain} -- cached report
# --------------------------------------------------------------------------


class TestCachedReport:
    async def test_cached_report(self, client, admin_user, admin_token):
        report = _make_report("cached.com", score=75)
        with _patch_deliverability_service(report):
            resp = await client.get(
                "/api/v1/email/deliverability/report/cached.com",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "cached.com"
        assert body["score"] == 75

    async def test_cached_report_nonexistent_domain(self, client, admin_user, admin_token):
        """When no cache exists, a fresh test is run."""
        report = _make_report("fresh.com", score=60)
        with _patch_deliverability_service(report):
            resp = await client.get(
                "/api/v1/email/deliverability/report/fresh.com",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        assert resp.json()["domain"] == "fresh.com"


# --------------------------------------------------------------------------
# SPF check focus
# --------------------------------------------------------------------------


class TestSPFCheck:
    async def test_spf_check_pass(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="SPF Record",
                status=CheckStatus.PASS,
                details='v=spf1 include:_spf.google.com ~all',
                recommendation="",
            ),
        ]
        report = _make_report("spf-pass.com", score=100, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "spf-pass.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        spf = resp.json()["checks"][0]
        assert spf["name"] == "SPF Record"
        assert spf["status"] == "pass"
        assert "v=spf1" in spf["details"]

    async def test_spf_check_fail(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="SPF Record",
                status=CheckStatus.FAIL,
                details="No SPF record found for domain",
                recommendation="Add a TXT record with v=spf1",
            ),
        ]
        report = _make_report("spf-fail.com", score=30, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "spf-fail.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        spf = resp.json()["checks"][0]
        assert spf["status"] == "fail"
        assert spf["recommendation"] != ""


# --------------------------------------------------------------------------
# DKIM check focus
# --------------------------------------------------------------------------


class TestDKIMCheck:
    async def test_dkim_check_pass(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="DKIM Record",
                status=CheckStatus.PASS,
                details="DKIM record found for selector 'default'",
                recommendation="",
            ),
        ]
        report = _make_report("dkim-pass.com", score=100, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "dkim-pass.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        dkim = resp.json()["checks"][0]
        assert dkim["name"] == "DKIM Record"
        assert dkim["status"] == "pass"

    async def test_dkim_check_warn(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="DKIM Record",
                status=CheckStatus.WARN,
                details="DKIM key length is 1024 bits (2048 recommended)",
                recommendation="Generate a new 2048-bit DKIM key",
            ),
        ]
        report = _make_report("dkim-warn.com", score=70, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "dkim-warn.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        dkim = resp.json()["checks"][0]
        assert dkim["status"] == "warn"


# --------------------------------------------------------------------------
# Blacklist check focus
# --------------------------------------------------------------------------


class TestBlacklistCheck:
    async def test_blacklist_check_clean(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="Blacklist Check",
                status=CheckStatus.PASS,
                details="Not listed on any of the 4 checked blacklists",
                recommendation="",
            ),
        ]
        report = _make_report("clean.com", score=100, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "clean.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        bl = resp.json()["checks"][0]
        assert bl["status"] == "pass"

    async def test_blacklist_check_listed(self, client, admin_user, admin_token):
        checks = [
            DeliverabilityCheck(
                name="Blacklist Check",
                status=CheckStatus.FAIL,
                details="Listed on: zen.spamhaus.org",
                recommendation="Request delisting from zen.spamhaus.org",
            ),
        ]
        report = _make_report("listed.com", score=10, checks=checks)
        with _patch_deliverability_service(report):
            resp = await client.post(
                "/api/v1/email/deliverability/test",
                json={"domain": "listed.com"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        bl = resp.json()["checks"][0]
        assert bl["status"] == "fail"
        assert "spamhaus" in bl["details"].lower()
