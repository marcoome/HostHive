"""S3-compatible backup storage service using httpx with AWS Signature V4.

Supports Amazon S3, Backblaze B2, Wasabi, and MinIO via configurable endpoint.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx

from api.core.config import settings
from api.core.encryption import decrypt_value

logger = logging.getLogger("hosthive.s3")

_TIMEOUT = 30.0
_UPLOAD_TIMEOUT = 600.0  # 10 minutes for large backup uploads


class S3BackupService:
    """S3-compatible object storage with AWS Signature V4 authentication."""

    def __init__(self, encrypted_config: str) -> None:
        config = json.loads(decrypt_value(encrypted_config, settings.SECRET_KEY))
        self._endpoint: str = config["endpoint"].rstrip("/")
        self._bucket: str = config["bucket"]
        self._access_key: str = config["access_key"]
        self._secret_key: str = config["secret_key"]
        self._region: str = config.get("region", "us-east-1")

        parsed = urlparse(self._endpoint)
        self._host = parsed.hostname or ""
        self._scheme = parsed.scheme or "https"

    # ------------------------------------------------------------------
    # AWS Signature V4 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _hmac_sha256(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def _signing_key(self, date_stamp: str) -> bytes:
        k_date = self._hmac_sha256(
            f"AWS4{self._secret_key}".encode("utf-8"), date_stamp
        )
        k_region = self._hmac_sha256(k_date, self._region)
        k_service = self._hmac_sha256(k_region, "s3")
        return self._hmac_sha256(k_service, "aws4_request")

    def _sign_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        payload_hash: str,
    ) -> Dict[str, str]:
        """Add Authorization header using AWS Signature V4."""
        now = datetime.datetime.now(datetime.timezone.utc)
        date_stamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")

        headers["x-amz-date"] = amz_date
        headers["x-amz-content-sha256"] = payload_hash

        signed_header_keys = sorted(headers.keys())
        signed_headers = ";".join(k.lower() for k in signed_header_keys)

        canonical_headers = "".join(
            f"{k.lower()}:{headers[k].strip()}\n" for k in signed_header_keys
        )
        canonical_request = "\n".join([
            method,
            quote(path, safe="/"),
            "",  # no query string
            canonical_headers,
            signed_headers,
            payload_hash,
        ])

        credential_scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            self._sha256(canonical_request.encode("utf-8")),
        ])

        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 "
            f"Credential={self._access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        return headers

    def _build_url(self, key: str) -> str:
        return f"{self._endpoint}/{self._bucket}/{key}"

    def _build_path(self, key: str) -> str:
        return f"/{self._bucket}/{key}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_backup(self, file_path: str, remote_key: str) -> Dict[str, Any]:
        """Upload a local file to S3-compatible storage."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        data = path.read_bytes()
        payload_hash = self._sha256(data)
        headers = {"host": self._host, "content-type": "application/octet-stream"}
        headers = self._sign_request(
            "PUT", self._build_path(remote_key), headers, payload_hash
        )

        async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
            resp = await client.put(
                self._build_url(remote_key), headers=headers, content=data
            )
            resp.raise_for_status()

        logger.info("Uploaded backup %s -> %s", file_path, remote_key)
        return {"key": remote_key, "size": len(data)}

    async def download_backup(self, remote_key: str, local_path: str) -> str:
        """Download a backup object to a local file."""
        payload_hash = self._sha256(b"")
        headers = {"host": self._host}
        headers = self._sign_request(
            "GET", self._build_path(remote_key), headers, payload_hash
        )

        async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
            resp = await client.get(
                self._build_url(remote_key), headers=headers
            )
            resp.raise_for_status()

        out = Path(local_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(resp.content)

        logger.info("Downloaded backup %s -> %s", remote_key, local_path)
        return local_path

    async def delete_backup(self, remote_key: str) -> None:
        """Delete a single object from the bucket."""
        payload_hash = self._sha256(b"")
        headers = {"host": self._host}
        headers = self._sign_request(
            "DELETE", self._build_path(remote_key), headers, payload_hash
        )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                self._build_url(remote_key), headers=headers
            )
            resp.raise_for_status()

        logger.info("Deleted backup %s", remote_key)

    async def list_backups(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List objects in the bucket under *prefix*."""
        payload_hash = self._sha256(b"")
        list_path = f"/{self._bucket}/"
        url = f"{self._endpoint}/{self._bucket}/?list-type=2&prefix={prefix}"
        headers = {"host": self._host}
        headers = self._sign_request("GET", list_path, headers, payload_hash)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        # Parse the XML response minimally
        body = resp.text
        objects: List[Dict[str, Any]] = []
        for chunk in body.split("<Contents>")[1:]:
            key = chunk.split("<Key>")[1].split("</Key>")[0] if "<Key>" in chunk else ""
            size = chunk.split("<Size>")[1].split("</Size>")[0] if "<Size>" in chunk else "0"
            last_mod = (
                chunk.split("<LastModified>")[1].split("</LastModified>")[0]
                if "<LastModified>" in chunk
                else ""
            )
            objects.append({"key": key, "size": int(size), "last_modified": last_mod})

        logger.info("Listed %d objects with prefix '%s'", len(objects), prefix)
        return objects

    async def cleanup_old_backups(self, keep: int = 30) -> int:
        """Delete all but the most recent *keep* backups (by last-modified)."""
        all_objects = await self.list_backups()
        if len(all_objects) <= keep:
            logger.info("Only %d backups exist, nothing to clean up", len(all_objects))
            return 0

        # Sort by last_modified descending and delete the tail
        sorted_objects = sorted(
            all_objects, key=lambda o: o.get("last_modified", ""), reverse=True
        )
        to_delete = sorted_objects[keep:]

        deleted = 0
        for obj in to_delete:
            try:
                await self.delete_backup(obj["key"])
                deleted += 1
            except httpx.HTTPStatusError:
                logger.warning("Failed to delete old backup %s", obj["key"])

        logger.info("Cleaned up %d old backups (kept %d)", deleted, keep)
        return deleted
