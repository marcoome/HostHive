"""Tests for the TOTP two-factor authentication router -- /api/v1/auth/2fa."""

from __future__ import annotations

import pyotp
import pytest
from unittest.mock import patch

from api.core.config import settings
from api.core.encryption import decrypt_value
from api.core.security import create_2fa_pending_token
from tests.conftest import auth_header


# --------------------------------------------------------------------------
# POST /setup
# --------------------------------------------------------------------------


class TestTOTPSetup:
    async def test_2fa_setup_returns_qr_and_codes(self, client, admin_user, admin_token):
        resp = await client.post(
            "/api/v1/auth/2fa/setup",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "secret" in body
        assert "qr_code_base64" in body
        assert "otpauth_uri" in body
        assert "backup_codes" in body
        assert len(body["backup_codes"]) == 10
        # Each backup code should be 8 characters
        for code in body["backup_codes"]:
            assert len(code) == 8
        # QR code should be non-empty base64
        assert len(body["qr_code_base64"]) > 100
        # otpauth URI should contain the issuer
        assert "NovaPanel" in body["otpauth_uri"]


# --------------------------------------------------------------------------
# POST /verify
# --------------------------------------------------------------------------


class TestTOTPVerify:
    async def test_2fa_verify_with_valid_code(self, client, admin_user, admin_token, db_session):
        # Step 1: Setup 2FA
        setup_resp = await client.post(
            "/api/v1/auth/2fa/setup",
            headers=auth_header(admin_token),
        )
        assert setup_resp.status_code == 200
        secret = setup_resp.json()["secret"]

        # Step 2: Generate a valid TOTP code
        totp = pyotp.TOTP(secret)
        code = totp.now()

        # Step 3: Verify
        resp = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"code": code},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["verified"] is True

    async def test_2fa_verify_with_invalid_code(self, client, admin_user, admin_token):
        # Setup 2FA first
        setup_resp = await client.post(
            "/api/v1/auth/2fa/setup",
            headers=auth_header(admin_token),
        )
        assert setup_resp.status_code == 200

        # Try verifying with an obviously wrong code
        resp = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"code": "000000"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]


# --------------------------------------------------------------------------
# Full 2FA login flow
# --------------------------------------------------------------------------


class TestTOTPLoginFlow:
    async def test_2fa_login_flow(self, client, admin_user, admin_token, db_session):
        """Full flow: setup -> verify -> login returns pending -> 2fa/login -> tokens."""
        # 1. Setup 2FA
        setup_resp = await client.post(
            "/api/v1/auth/2fa/setup",
            headers=auth_header(admin_token),
        )
        secret = setup_resp.json()["secret"]

        # 2. Verify setup
        totp = pyotp.TOTP(secret)
        code = totp.now()
        verify_resp = await client.post(
            "/api/v1/auth/2fa/verify",
            json={"code": code},
            headers=auth_header(admin_token),
        )
        assert verify_resp.status_code == 200

        # 3. Now login should return 2fa_pending
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        assert login_resp.status_code == 200
        login_body = login_resp.json()
        assert login_body.get("requires_2fa") is True
        assert "pending_token" in login_body

        # 4. Complete login with TOTP code
        pending_token = login_body["pending_token"]
        new_code = totp.now()
        totp_login_resp = await client.post(
            "/api/v1/auth/2fa/login",
            json={"pending_token": pending_token, "code": new_code},
        )
        assert totp_login_resp.status_code == 200
        totp_body = totp_login_resp.json()
        assert "access_token" in totp_body
        assert "refresh_token" in totp_body
        assert totp_body.get("expires_in", 0) > 0

    async def test_2fa_backup_code_works_once(self, client, admin_user, admin_token, db_session):
        """Backup code can be used once to complete login, then is consumed."""
        # 1. Setup + verify 2FA
        setup_resp = await client.post(
            "/api/v1/auth/2fa/setup",
            headers=auth_header(admin_token),
        )
        secret = setup_resp.json()["secret"]
        backup_codes = setup_resp.json()["backup_codes"]

        totp = pyotp.TOTP(secret)
        await client.post(
            "/api/v1/auth/2fa/verify",
            json={"code": totp.now()},
            headers=auth_header(admin_token),
        )

        # 2. Login to get pending token
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        pending_token = login_resp.json()["pending_token"]

        # 3. Use first backup code
        first_code = backup_codes[0]
        backup_resp = await client.post(
            "/api/v1/auth/2fa/backup-verify",
            json={"pending_token": pending_token, "backup_code": first_code},
        )
        assert backup_resp.status_code == 200
        assert "access_token" in backup_resp.json()

        # 4. Try using the same backup code again -- should fail
        login_resp2 = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        pending_token2 = login_resp2.json()["pending_token"]

        backup_resp2 = await client.post(
            "/api/v1/auth/2fa/backup-verify",
            json={"pending_token": pending_token2, "backup_code": first_code},
        )
        assert backup_resp2.status_code == 401
        assert "Invalid" in backup_resp2.json()["detail"]


# --------------------------------------------------------------------------
# POST /disable
# --------------------------------------------------------------------------


class TestTOTPDisable:
    async def test_2fa_disable_requires_code(self, client, admin_user, admin_token, db_session):
        """Disabling 2FA requires a valid TOTP code."""
        # Setup + verify 2FA
        setup_resp = await client.post(
            "/api/v1/auth/2fa/setup",
            headers=auth_header(admin_token),
        )
        secret = setup_resp.json()["secret"]

        totp = pyotp.TOTP(secret)
        await client.post(
            "/api/v1/auth/2fa/verify",
            json={"code": totp.now()},
            headers=auth_header(admin_token),
        )

        # Try disabling with wrong code
        resp_bad = await client.post(
            "/api/v1/auth/2fa/disable",
            json={"code": "000000"},
            headers=auth_header(admin_token),
        )
        assert resp_bad.status_code == 400
        assert "Invalid" in resp_bad.json()["detail"]

        # Disable with correct code
        resp_ok = await client.post(
            "/api/v1/auth/2fa/disable",
            json={"code": totp.now()},
            headers=auth_header(admin_token),
        )
        assert resp_ok.status_code == 200
        assert "disabled" in resp_ok.json()["detail"].lower()


# --------------------------------------------------------------------------
# Login without 2FA remains unchanged
# --------------------------------------------------------------------------


class TestLoginWithout2FA:
    async def test_login_without_2fa_unchanged(self, client, admin_user):
        """Users without 2FA still receive tokens directly on login."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body.get("requires_2fa") is not True
