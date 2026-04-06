"""Fernet-based encryption for sensitive values (e.g. database passwords).

The encryption key is derived from the application SECRET_KEY using PBKDF2
with a per-installation random salt (FERNET_SALT from secrets.env).

For backward compatibility with installations that predate the random salt,
decryption will fall back to the legacy hardcoded salt if the primary
attempt fails.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

_LEGACY_SALT = b"hosthive-fernet-salt"


def _get_configured_salt() -> bytes:
    """Return the installation-specific salt, or the legacy salt as fallback."""
    from api.core.config import settings  # deferred to avoid circular import

    if settings.FERNET_SALT:
        return bytes.fromhex(settings.FERNET_SALT)
    return _LEGACY_SALT


def _derive_fernet_key(secret_key: str, salt: bytes | None = None) -> bytes:
    """Derive a 32-byte URL-safe base64-encoded Fernet key via PBKDF2.

    Parameters
    ----------
    secret_key:
        The application SECRET_KEY.
    salt:
        Raw bytes to use as the PBKDF2 salt.  When *None*, the
        installation-specific salt from config is used.
    """
    if salt is None:
        salt = _get_configured_salt()
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode("utf-8"),
        salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(raw)


def encrypt_value(plaintext: str, key: str) -> str:
    """Encrypt *plaintext* using a Fernet key derived from *key*.

    Returns the ciphertext as a UTF-8 string suitable for database storage.
    Always uses the current installation salt.
    """
    fernet = Fernet(_derive_fernet_key(key))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str, key: str) -> str:
    """Decrypt a *ciphertext* previously produced by :func:`encrypt_value`.

    Tries the current installation salt first.  If that fails and a
    non-legacy salt is configured, retries with the legacy hardcoded salt
    so that data encrypted before the salt migration can still be read.

    Raises ``ValueError`` if the ciphertext is invalid or the key is wrong
    with both salts.
    """
    current_salt = _get_configured_salt()

    # --- attempt 1: current salt ---
    try:
        fernet = Fernet(_derive_fernet_key(key, salt=current_salt))
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        pass

    # --- attempt 2: legacy salt (only if we aren't already using it) ---
    if current_salt != _LEGACY_SALT:
        try:
            fernet = Fernet(_derive_fernet_key(key, salt=_LEGACY_SALT))
            return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            pass

    raise ValueError("Decryption failed — invalid ciphertext or wrong key.")


# ── Migration helper ───────────────────────────────────────────────────────


def re_encrypt_value(ciphertext: str, key: str) -> tuple[str, bool]:
    """Re-encrypt *ciphertext* under the current salt if it was encrypted
    with the legacy salt.

    Returns
    -------
    (new_ciphertext, changed)
        *changed* is ``True`` when re-encryption occurred (i.e. the value
        was still using the legacy salt).  ``False`` means it was already
        using the current salt and is returned unchanged.
    """
    current_salt = _get_configured_salt()

    # If no custom salt is configured, nothing to migrate.
    if current_salt == _LEGACY_SALT:
        return ciphertext, False

    # Try decrypting with the current salt first — already migrated.
    try:
        fernet = Fernet(_derive_fernet_key(key, salt=current_salt))
        fernet.decrypt(ciphertext.encode("utf-8"))
        return ciphertext, False
    except InvalidToken:
        pass

    # Must be legacy-encrypted — decrypt with legacy salt, re-encrypt with new.
    try:
        legacy_fernet = Fernet(_derive_fernet_key(key, salt=_LEGACY_SALT))
        plaintext = legacy_fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Cannot migrate: decryption failed with both current and legacy salt."
        ) from exc

    new_ciphertext = encrypt_value(plaintext, key)
    return new_ciphertext, True
