"""Cloudflare DNS and proxy management via the Cloudflare API v4."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from api.core.config import settings
from api.core.encryption import decrypt_value

logger = logging.getLogger("hosthive.cloudflare")

_CF_BASE = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 30.0


class CloudflareService:
    """High-level wrapper around the Cloudflare REST API."""

    def __init__(self, encrypted_config: str) -> None:
        config = json.loads(decrypt_value(encrypted_config, settings.SECRET_KEY))
        self._api_key: str = config["api_key"]
        self._email: str = config["email"]
        self._zone_id: str = config["zone_id"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Auth-Email": self._email,
            "X-Auth-Key": self._api_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a request to the Cloudflare API and return the JSON response."""
        url = f"{_CF_BASE}{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
            )
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync_dns_zone(
        self, domain: str, records: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Push a full set of DNS records for *domain* to Cloudflare.

        Fetches the existing records, deletes stale ones, and creates or
        updates the records in *records*.
        """
        existing = await self._request(
            "GET", f"/zones/{self._zone_id}/dns_records?per_page=500"
        )
        existing_by_key = {
            (r["type"], r["name"]): r for r in existing.get("result", [])
        }

        results: List[Dict[str, Any]] = []
        seen_keys = set()

        for rec in records:
            key = (rec["type"], rec["name"])
            seen_keys.add(key)

            if key in existing_by_key:
                # Update existing record
                record_id = existing_by_key[key]["id"]
                resp = await self._request(
                    "PUT",
                    f"/zones/{self._zone_id}/dns_records/{record_id}",
                    json_body={
                        "type": rec["type"],
                        "name": rec["name"],
                        "content": rec["content"],
                        "ttl": rec.get("ttl", 1),
                        "proxied": rec.get("proxied", False),
                    },
                )
                results.append(resp.get("result", {}))
            else:
                # Create new record
                resp = await self.create_dns_record(
                    self._zone_id,
                    rec["type"],
                    rec["name"],
                    rec["content"],
                    ttl=rec.get("ttl", 1),
                    proxied=rec.get("proxied", False),
                )
                results.append(resp)

        # Delete records not present in the desired set
        for key, existing_rec in existing_by_key.items():
            if key not in seen_keys:
                try:
                    await self.delete_dns_record(
                        self._zone_id, existing_rec["id"]
                    )
                except httpx.HTTPStatusError:
                    logger.warning(
                        "Failed to delete stale DNS record %s", existing_rec["id"]
                    )

        logger.info(
            "Synced %d DNS records for domain %s (zone %s)",
            len(records), domain, self._zone_id,
        )
        return {"synced": len(results), "domain": domain}

    async def enable_proxy(self, domain: str) -> Dict[str, Any]:
        """Turn on Cloudflare proxy (orange cloud) for all A/AAAA records
        matching *domain*.
        """
        existing = await self._request(
            "GET",
            f"/zones/{self._zone_id}/dns_records?name={domain}&per_page=500",
        )
        updated = []
        for rec in existing.get("result", []):
            if rec["type"] in ("A", "AAAA") and not rec.get("proxied"):
                resp = await self._request(
                    "PATCH",
                    f"/zones/{self._zone_id}/dns_records/{rec['id']}",
                    json_body={"proxied": True},
                )
                updated.append(resp.get("result", {}))
        logger.info("Enabled proxy for %d records on %s", len(updated), domain)
        return {"proxied_count": len(updated)}

    async def get_analytics(self, zone_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch basic traffic analytics for the zone."""
        zid = zone_id or self._zone_id
        resp = await self._request(
            "GET",
            f"/zones/{zid}/analytics/dashboard?since=-1440&continuous=true",
        )
        return resp.get("result", {})

    async def create_dns_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        *,
        ttl: int = 1,
        proxied: bool = False,
    ) -> Dict[str, Any]:
        """Create a single DNS record in *zone_id*."""
        resp = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json_body={
                "type": record_type,
                "name": name,
                "content": content,
                "ttl": ttl,
                "proxied": proxied,
            },
        )
        result = resp.get("result", {})
        logger.info(
            "Created DNS record %s %s -> %s in zone %s",
            record_type, name, content, zone_id,
        )
        return result

    async def delete_dns_record(self, zone_id: str, record_id: str) -> Dict[str, Any]:
        """Delete a DNS record by ID."""
        resp = await self._request(
            "DELETE", f"/zones/{zone_id}/dns_records/{record_id}"
        )
        logger.info("Deleted DNS record %s from zone %s", record_id, zone_id)
        return resp.get("result", {})
