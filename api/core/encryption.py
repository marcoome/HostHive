"""Fernet-based encryption for sensitive values (e.g. database passwords).

The encryption key is derived from the application SECRET_KEY using PBKDF2
so that rotating the app secret automatically rotates the encryption key.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _derive_fernet_key(secret_key: str) -> bytes:
    """Derive a 32-byte URL-safe base64-encoded Fernet key via PBKDF2."""
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode("utf-8"),
        b"novapanel-fernet-salt",
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(raw)


def encrypt_value(plaintext: str, key: str) -> str:
    """Encrypt *plaintext* using a Fernet key derived from *key*.

    Returns the ciphertext as a UTF-8 string suitable for database storage.
    """
    fernet = Fernet(_derive_fernet_key(key))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str, key: str) -> str:
    """Decrypt a *ciphertext* previously produced by :func:`encrypt_value`.

    Raises ``ValueError`` if the ciphertext is invalid or the key is wrong.
    """
    fernet = Fernet(_derive_fernet_key(key))
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Decryption failed — invalid ciphertext or wrong key.") from exc
