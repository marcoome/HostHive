"""IP reputation checking via AbuseIPDB with Redis caching."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger("hosthive.ip_reputation")

_ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/check"
_TIMEOUT = 30.0
_CACHE_TTL = 86400  # 24 hours in seconds
_CACHE_PREFIX = "hosthive:ip_reputation:"
_BLOCK_THRESHOLD = 50


@dataclass
class ReputationResult:
    """Result of an IP reputation check."""

    ip: str
    score: int
    blocked: bool
    cached: bool = False


async def check_ip_reputation(
    ip: str,
    api_key: str,
    redis: Any,
) -> ReputationResult:
    """Check the abuse confidence score for *ip* via AbuseIPDB.

    Parameters
    ----------
    ip:
        The IPv4 or IPv6 address to check.
    api_key:
        AbuseIPDB API key (decrypted).
    redis:
        An async Redis client instance.

    Returns
    -------
    ReputationResult
        Contains the abuse score and whether the IP should be blocked.
    """
    cache_key = f"{_CACHE_PREFIX}{ip}"

    # ── Check Redis cache first ────────────────────────────────────────
    cached = await redis.get(cache_key)
    if cached is not None:
        try:
            data = json.loads(cached)
            return ReputationResult(
                ip=ip,
                score=data["score"],
                blocked=data["score"] > _BLOCK_THRESHOLD,
                cached=True,
            )
        except (json.JSONDecodeError, KeyError):
            pass  # stale/corrupt cache entry — re-fetch

    # ── Query AbuseIPDB ────────────────────────────────────────────────
    score = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _ABUSEIPDB_URL,
                params={"ipAddress": ip, "maxAgeInDays": "90"},
                headers={
                    "Key": api_key,
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            score = payload.get("data", {}).get("abuseConfidenceScore", 0)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "AbuseIPDB request failed for %s: %s %s",
            ip, exc.response.status_code, exc.response.text[:200],
        )
    except Exception as exc:
        logger.error("AbuseIPDB request error for %s: %s", ip, exc)

    # ── Cache the result ───────────────────────────────────────────────
    try:
        await redis.set(
            cache_key,
            json.dumps({"score": score}),
            ex=_CACHE_TTL,
        )
    except Exception as exc:
        logger.warning("Failed to cache IP reputation for %s: %s", ip, exc)

    return ReputationResult(
        ip=ip,
        score=score,
        blocked=score > _BLOCK_THRESHOLD,
    )
