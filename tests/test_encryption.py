"""Tests for the encryption module -- api/core/encryption.py.

Covers: roundtrip, legacy salt fallback, re_encrypt_value, and new salt usage.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.core.encryption import (
    _LEGACY_SALT,
    _derive_fernet_key,
    decrypt_value,
    encrypt_value,
    re_encrypt_value,
)


_TEST_KEY = "a-secret-key-that-is-long-enough-for-testing-purposes"


# --------------------------------------------------------------------------
# Basic roundtrip
# --------------------------------------------------------------------------


class TestEncryptDecryptRoundtrip:
    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting then decrypting returns the original plaintext."""
        original = "super-secret-database-password-123!"
        ciphertext = encrypt_value(original, _TEST_KEY)
        assert ciphertext != original
        decrypted = decrypt_value(ciphertext, _TEST_KEY)
        assert decrypted == original

    def test_roundtrip_with_empty_string(self):
        """Empty strings should encrypt/decrypt cleanly."""
        ciphertext = encrypt_value("", _TEST_KEY)
        assert decrypt_value(ciphertext, _TEST_KEY) == ""

    def test_roundtrip_with_unicode(self):
        """Unicode characters should survive the roundtrip."""
        original = "password-with-unicode-\u00e9\u00e8\u00ea-\u2603"
        ciphertext = encrypt_value(original, _TEST_KEY)
        assert decrypt_value(ciphertext, _TEST_KEY) == original


# --------------------------------------------------------------------------
# Legacy salt fallback
# --------------------------------------------------------------------------


class TestLegacySaltFallback:
    def test_legacy_salt_fallback(self):
        """Values encrypted with the legacy salt should decrypt when a new salt is configured."""
        from cryptography.fernet import Fernet

        # Encrypt with the legacy salt
        legacy_fernet_key = _derive_fernet_key(_TEST_KEY, salt=_LEGACY_SALT)
        fernet = Fernet(legacy_fernet_key)
        legacy_ciphertext = fernet.encrypt(b"my-legacy-secret").decode("utf-8")

        # Configure a non-legacy salt
        new_salt_hex = "deadbeef" * 4  # 16 bytes as hex
        with patch("api.core.encryption._get_configured_salt", return_value=bytes.fromhex(new_salt_hex)):
            # Decrypt should fallback to legacy salt
            result = decrypt_value(legacy_ciphertext, _TEST_KEY)

        assert result == "my-legacy-secret"

    def test_decrypt_with_wrong_key_raises(self):
        """Decrypting with the wrong key should raise ValueError."""
        ciphertext = encrypt_value("secret", _TEST_KEY)
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_value(ciphertext, "completely-different-key-for-testing")


# --------------------------------------------------------------------------
# re_encrypt_value
# --------------------------------------------------------------------------


class TestReEncryptValue:
    def test_re_encrypt_value(self):
        """Legacy-encrypted values should be re-encrypted under the new salt."""
        from cryptography.fernet import Fernet

        # Encrypt with legacy salt
        legacy_fernet_key = _derive_fernet_key(_TEST_KEY, salt=_LEGACY_SALT)
        fernet = Fernet(legacy_fernet_key)
        legacy_ciphertext = fernet.encrypt(b"migrate-me").decode("utf-8")

        # Configure a new salt
        new_salt_hex = "cafebabe" * 4
        new_salt = bytes.fromhex(new_salt_hex)
        with patch("api.core.encryption._get_configured_salt", return_value=new_salt):
            new_ciphertext, changed = re_encrypt_value(legacy_ciphertext, _TEST_KEY)

        assert changed is True
        assert new_ciphertext != legacy_ciphertext

        # Verify the new ciphertext can be decrypted with the new salt
        with patch("api.core.encryption._get_configured_salt", return_value=new_salt):
            decrypted = decrypt_value(new_ciphertext, _TEST_KEY)
        assert decrypted == "migrate-me"

    def test_re_encrypt_already_current_returns_unchanged(self):
        """Values already under the current salt should not be re-encrypted."""
        new_salt_hex = "12345678" * 4
        new_salt = bytes.fromhex(new_salt_hex)

        with patch("api.core.encryption._get_configured_salt", return_value=new_salt):
            ciphertext = encrypt_value("already-current", _TEST_KEY)
            new_ciphertext, changed = re_encrypt_value(ciphertext, _TEST_KEY)

        assert changed is False
        assert new_ciphertext == ciphertext

    def test_re_encrypt_noop_when_legacy_salt_active(self):
        """When no custom salt is configured (legacy is active), re_encrypt is a no-op."""
        with patch("api.core.encryption._get_configured_salt", return_value=_LEGACY_SALT):
            ciphertext = encrypt_value("no-migration", _TEST_KEY)
            new_ciphertext, changed = re_encrypt_value(ciphertext, _TEST_KEY)

        assert changed is False
        assert new_ciphertext == ciphertext


# --------------------------------------------------------------------------
# New salt used for new encryptions
# --------------------------------------------------------------------------


class TestNewSaltUsedForNewEncryptions:
    def test_new_salt_used_for_new_encryptions(self):
        """encrypt_value should use the configured (non-legacy) salt for new encryptions."""
        new_salt_hex = "aabbccdd" * 4
        new_salt = bytes.fromhex(new_salt_hex)

        with patch("api.core.encryption._get_configured_salt", return_value=new_salt):
            ciphertext = encrypt_value("fresh-data", _TEST_KEY)

        # Decrypting with the new salt should work
        from cryptography.fernet import Fernet

        new_fernet_key = _derive_fernet_key(_TEST_KEY, salt=new_salt)
        fernet = Fernet(new_fernet_key)
        result = fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        assert result == "fresh-data"

        # Decrypting with the legacy salt should fail
        legacy_fernet_key = _derive_fernet_key(_TEST_KEY, salt=_LEGACY_SALT)
        legacy_fernet = Fernet(legacy_fernet_key)
        from cryptography.fernet import InvalidToken

        with pytest.raises(InvalidToken):
            legacy_fernet.decrypt(ciphertext.encode("utf-8"))
