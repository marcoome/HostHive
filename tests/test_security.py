"""Security-focused tests: JWT, headers, path traversal, encryption, rate limiting."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt

from api.core.config import settings
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import (
    create_access_token,
    hash_password,
    verify_password,
    verify_token,
)
from api.core.validators import (
    sanitize_domain,
    sanitize_path,
    sanitize_shell_arg,
    sanitize_sql_identifier,
    validate_cron_expression,
    validate_email_address,
    validate_password,
)
from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Path traversal
# --------------------------------------------------------------------------


class TestPathTraversal:
    async def test_path_traversal_file_manager_dot_dot_slash(
        self, client, regular_user, user_token
    ):
        traversal_patterns = [
            "../../../etc/passwd",
            "..%2F..%2Fetc/passwd",
            "/../../etc/shadow",
            "....//....//etc/passwd",
            "/home/testuser/../../../etc/passwd",
        ]
        for pattern in traversal_patterns:
            resp = await client.get(
                f"/api/v1/files/read?path={pattern}",
                headers=auth_header(user_token),
            )
            # Should be 403 (traversal blocked) or 400, never 200 with /etc content
            assert resp.status_code in (400, 403, 422), (
                f"Path traversal not blocked for pattern: {pattern}"
            )


# --------------------------------------------------------------------------
# SQL identifier sanitization
# --------------------------------------------------------------------------


class TestSqlIdentifierSanitization:
    def test_valid_sql_identifiers(self):
        assert sanitize_sql_identifier("my_database") == "my_database"
        assert sanitize_sql_identifier("DB123") == "DB123"
        assert sanitize_sql_identifier("a") == "a"

    def test_invalid_sql_identifiers(self):
        with pytest.raises(ValueError):
            sanitize_sql_identifier("my-database")  # hyphen
        with pytest.raises(ValueError):
            sanitize_sql_identifier("bobby'; DROP TABLE--")
        with pytest.raises(ValueError):
            sanitize_sql_identifier("")  # empty
        with pytest.raises(ValueError):
            sanitize_sql_identifier("a" * 64)  # too long (max 63)


# --------------------------------------------------------------------------
# Domain sanitization
# --------------------------------------------------------------------------


class TestDomainSanitization:
    def test_valid_domains(self):
        assert sanitize_domain("example.com") == "example.com"
        assert sanitize_domain("sub.example.co.uk") == "sub.example.co.uk"
        assert sanitize_domain("  EXAMPLE.COM  ") == "example.com"

    def test_invalid_domains(self):
        with pytest.raises(ValueError):
            sanitize_domain("")
        with pytest.raises(ValueError):
            sanitize_domain("exam ple.com")  # space
        with pytest.raises(ValueError):
            sanitize_domain("-example.com")  # starts with hyphen
        with pytest.raises(ValueError):
            sanitize_domain("example-.com")  # label ends with hyphen
        with pytest.raises(ValueError):
            sanitize_domain("a" * 254)  # too long


# --------------------------------------------------------------------------
# Password validation
# --------------------------------------------------------------------------


class TestPasswordValidation:
    def test_weak_passwords_rejected(self):
        weak = [
            "short",           # too short
            "alllowercase123!", # no uppercase
            "ALLUPPERCASE123!", # no lowercase
            "NoDigitsHere!!",  # no digit
            "NoSpecial123abc", # no special char
        ]
        for pw in weak:
            with pytest.raises(ValueError):
                validate_password(pw)

    def test_strong_password_accepted(self):
        validate_password("StrongPass123!@#")  # should not raise


# --------------------------------------------------------------------------
# Cron expression validation
# --------------------------------------------------------------------------


class TestCronExpressionValidation:
    def test_valid_crons(self):
        assert validate_cron_expression("0 * * * *") == "0 * * * *"
        assert validate_cron_expression("*/5 * * * *") == "*/5 * * * *"
        assert validate_cron_expression("@daily") == "@daily"
        assert validate_cron_expression("@reboot") == "@reboot"

    def test_invalid_crons(self):
        with pytest.raises(ValueError):
            validate_cron_expression("0 * *")  # too few fields
        with pytest.raises(ValueError):
            validate_cron_expression("0 * * * * *")  # too many fields
        with pytest.raises(ValueError):
            validate_cron_expression("60 * * * *")  # minute out of range
        with pytest.raises(ValueError):
            validate_cron_expression("abc * * * *")  # invalid chars


# --------------------------------------------------------------------------
# Email validation
# --------------------------------------------------------------------------


class TestEmailValidation:
    def test_valid_emails(self):
        assert validate_email_address("user@example.com") == "user@example.com"
        assert validate_email_address("USER@EXAMPLE.COM") == "user@example.com"
        assert validate_email_address("test.name+tag@sub.domain.org") == "test.name+tag@sub.domain.org"

    def test_invalid_emails(self):
        with pytest.raises(ValueError):
            validate_email_address("")
        with pytest.raises(ValueError):
            validate_email_address("notanemail")
        with pytest.raises(ValueError):
            validate_email_address("@missing-local.com")
        with pytest.raises(ValueError):
            validate_email_address("user@nodot")  # no dot in domain


# --------------------------------------------------------------------------
# Shell arg sanitization
# --------------------------------------------------------------------------


class TestShellArgSanitization:
    def test_safe_args(self):
        assert sanitize_shell_arg("hello-world") == "hello-world"
        assert sanitize_shell_arg("file.txt") == "file.txt"

    def test_dangerous_chars_rejected(self):
        dangerous = [
            "foo; rm -rf /",
            "$(whoami)",
            "`id`",
            "test|cat /etc/passwd",
            "foo\nbar",
            "path/../secret",
        ]
        for arg in dangerous:
            with pytest.raises(ValueError):
                sanitize_shell_arg(arg)


# --------------------------------------------------------------------------
# Encryption roundtrip
# --------------------------------------------------------------------------


class TestEncryption:
    def test_encrypt_then_decrypt_returns_original(self):
        key = "a-secret-key-that-is-long-enough-for-testing-purposes"
        original = "my-database-password-123"
        ciphertext = encrypt_value(original, key)
        assert ciphertext != original
        decrypted = decrypt_value(ciphertext, key)
        assert decrypted == original

    def test_decrypt_with_wrong_key_raises(self):
        key1 = "key-one-that-is-definitely-long-enough-for-testing"
        key2 = "key-two-that-is-definitely-long-enough-for-testing"
        ciphertext = encrypt_value("secret", key1)
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_value(ciphertext, key2)


# --------------------------------------------------------------------------
# JWT tests
# --------------------------------------------------------------------------


class TestJWT:
    def test_jwt_token_expired_returns_401(self, client):
        """Manually craft an expired token and verify it is rejected."""
        import uuid

        payload = {
            "sub": str(uuid.uuid4()),
            "role": "user",
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "jti": uuid.uuid4().hex,
        }
        expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            verify_token(expired_token)
        assert exc_info.value.status_code == 401

    def test_jwt_token_tampered_returns_401(self):
        """Modify a valid token payload and verify it fails."""
        import uuid

        token = create_access_token(uuid.uuid4(), "user")
        # Tamper with the token by changing one character
        parts = token.split(".")
        tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            verify_token(tampered_token)
        assert exc_info.value.status_code == 401


# --------------------------------------------------------------------------
# Security headers
# --------------------------------------------------------------------------


class TestSecurityHeaders:
    async def test_security_headers_present(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        headers = resp.headers
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-frame-options") == "SAMEORIGIN"
        assert headers.get("x-xss-protection") == "1; mode=block"
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "x-request-id" in headers

    async def test_cors_headers_on_options(self, client):
        resp = await client.options(
            "/api/v1/health",
            headers={
                "Origin": settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "https://panel.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS middleware should respond with access-control headers
        assert "access-control-allow-origin" in resp.headers or resp.status_code == 200


# --------------------------------------------------------------------------
# Rate limit on login
# --------------------------------------------------------------------------


class TestRateLimitLogin:
    async def test_brute_force_returns_429(self, client, admin_user, fake_redis):
        """After 5 failed logins, a 6th attempt should be rate-limited."""
        for i in range(5):
            await client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": f"wrong{i}!!Aa1"},
            )

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "Admin12345!@#"},
        )
        assert resp.status_code == 429
