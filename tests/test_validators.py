"""Tests for api.core.validators -- input sanitisation and validation."""

from __future__ import annotations

import pytest

from api.core.validators import (
    sanitize_domain,
    sanitize_path,
    sanitize_shell_arg,
    sanitize_sql_identifier,
    validate_cron_expression,
    validate_email_address,
    validate_password,
)


# --------------------------------------------------------------------------
# sanitize_domain
# --------------------------------------------------------------------------


class TestSanitizeDomain:
    def test_sanitize_domain_valid(self):
        assert sanitize_domain("example.com") == "example.com"
        assert sanitize_domain("sub.example.co.uk") == "sub.example.co.uk"
        assert sanitize_domain("  EXAMPLE.COM  ") == "example.com"
        assert sanitize_domain("my-site.org") == "my-site.org"

    def test_sanitize_domain_invalid(self):
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
# sanitize_path
# --------------------------------------------------------------------------


class TestSanitizePathTraversalBlocked:
    def test_sanitize_path_traversal_blocked(self):
        with pytest.raises(ValueError, match="traversal"):
            sanitize_path("../../etc/passwd", "/home/testuser")
        with pytest.raises(ValueError, match="traversal"):
            sanitize_path("../../../etc/shadow", "/home/testuser")

    def test_sanitize_path_valid(self):
        result = sanitize_path("documents/file.txt", "/home/testuser")
        assert str(result).startswith("/home/testuser")


# --------------------------------------------------------------------------
# validate_password
# --------------------------------------------------------------------------


class TestValidatePassword:
    def test_validate_password_weak(self):
        weak_passwords = [
            "short",              # too short
            "alllowercase123!",   # no uppercase
            "ALLUPPERCASE123!",   # no lowercase
            "NoDigitsHere!!",     # no digit
            "NoSpecial123abc",    # no special char
        ]
        for pw in weak_passwords:
            with pytest.raises(ValueError):
                validate_password(pw)

    def test_validate_password_strong(self):
        validate_password("StrongPass123!@#")  # should not raise


# --------------------------------------------------------------------------
# sanitize_shell_arg
# --------------------------------------------------------------------------


class TestSanitizeShellArgDangerous:
    def test_sanitize_shell_arg_dangerous(self):
        dangerous_args = [
            "foo; rm -rf /",
            "$(whoami)",
            "`id`",
            "test|cat /etc/passwd",
            "foo\nbar",
            "path/../secret",
        ]
        for arg in dangerous_args:
            with pytest.raises(ValueError):
                sanitize_shell_arg(arg)

    def test_sanitize_shell_arg_safe(self):
        assert sanitize_shell_arg("hello-world") == "hello-world"
        assert sanitize_shell_arg("file.txt") == "file.txt"
        assert sanitize_shell_arg("my_script") == "my_script"


# --------------------------------------------------------------------------
# validate_email_address
# --------------------------------------------------------------------------


class TestValidateEmail:
    def test_validate_email_valid(self):
        assert validate_email_address("user@example.com") == "user@example.com"
        assert validate_email_address("USER@EXAMPLE.COM") == "user@example.com"
        assert (
            validate_email_address("test.name+tag@sub.domain.org")
            == "test.name+tag@sub.domain.org"
        )

    def test_validate_email_invalid(self):
        with pytest.raises(ValueError):
            validate_email_address("")
        with pytest.raises(ValueError):
            validate_email_address("notanemail")
        with pytest.raises(ValueError):
            validate_email_address("@missing-local.com")
        with pytest.raises(ValueError):
            validate_email_address("user@nodot")


# --------------------------------------------------------------------------
# validate_cron_expression
# --------------------------------------------------------------------------


class TestValidateCron:
    def test_validate_cron_valid(self):
        assert validate_cron_expression("0 * * * *") == "0 * * * *"
        assert validate_cron_expression("*/5 * * * *") == "*/5 * * * *"
        assert validate_cron_expression("@daily") == "@daily"
        assert validate_cron_expression("@reboot") == "@reboot"

    def test_validate_cron_invalid(self):
        with pytest.raises(ValueError):
            validate_cron_expression("0 * *")  # too few fields
        with pytest.raises(ValueError):
            validate_cron_expression("0 * * * * *")  # too many fields
        with pytest.raises(ValueError):
            validate_cron_expression("60 * * * *")  # minute out of range
        with pytest.raises(ValueError):
            validate_cron_expression("abc * * * *")  # invalid chars


# --------------------------------------------------------------------------
# sanitize_sql_identifier
# --------------------------------------------------------------------------


class TestSanitizeSqlIdentifier:
    def test_sanitize_sql_identifier_valid(self):
        assert sanitize_sql_identifier("my_database") == "my_database"
        assert sanitize_sql_identifier("DB123") == "DB123"
        assert sanitize_sql_identifier("a") == "a"

    def test_sanitize_sql_identifier_invalid(self):
        with pytest.raises(ValueError):
            sanitize_sql_identifier("my-database")  # hyphen
        with pytest.raises(ValueError):
            sanitize_sql_identifier("bobby'; DROP TABLE--")
        with pytest.raises(ValueError):
            sanitize_sql_identifier("")  # empty
        with pytest.raises(ValueError):
            sanitize_sql_identifier("a" * 64)  # too long (max 63)
