"""
HMAC-SHA256 authentication module for HostHive Root Agent.

Verifies requests using a shared secret. The signature scheme:
  signature = HMAC-SHA256(secret, timestamp + nonce + sha256(body))

Headers required on every request:
  X-NP-Timestamp  — Unix epoch seconds (string)
  X-NP-Nonce      — Unique random string per request
  X-NP-Signature  — Hex-encoded HMAC-SHA256

Replay protection:
  - Requests older than MAX_AGE_SECONDS are rejected.
  - Seen nonces are stored in a bounded set and rejected on reuse.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import OrderedDict
from threading import Lock
from typing import Optional


MAX_AGE_SECONDS = 60
MAX_NONCE_CACHE = 100_000


class HMACVerifier:
    """Thread-safe HMAC-SHA256 verifier with replay protection."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        timestamp: Optional[str],
        nonce: Optional[str],
        body: bytes,
        signature: Optional[str],
    ) -> tuple[bool, str]:
        """Return (ok, reason).  ``reason`` is empty on success."""

        if not timestamp or not nonce or not signature:
            return False, "missing authentication headers"

        # --- timestamp freshness ---
        try:
            ts = int(timestamp)
        except ValueError:
            return False, "invalid timestamp"

        age = abs(time.time() - ts)
        if age > MAX_AGE_SECONDS:
            return False, "request expired"

        # --- nonce replay ---
        with self._lock:
            if nonce in self._nonces:
                return False, "nonce reused"
            self._nonces[nonce] = time.time()
            # Evict oldest entries when cache is full
            while len(self._nonces) > MAX_NONCE_CACHE:
                self._nonces.popitem(last=False)

        # --- HMAC verification ---
        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{timestamp}{nonce}{body_hash}".encode("utf-8")
        expected = hmac.new(self._secret, message, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, signature):
            return False, "invalid signature"

        return True, ""

    def purge_expired_nonces(self) -> int:
        """Remove nonces older than MAX_AGE_SECONDS.  Returns count removed."""
        cutoff = time.time() - MAX_AGE_SECONDS
        removed = 0
        with self._lock:
            while self._nonces:
                _nonce, ts = next(iter(self._nonces.items()))
                if ts < cutoff:
                    self._nonces.popitem(last=False)
                    removed += 1
                else:
                    break
        return removed

    @staticmethod
    def compute_signature(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
        """Utility used by the web-app side to sign outgoing requests."""
        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{timestamp}{nonce}{body_hash}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
