"""HTTP client for communicating with the HostHive system agent.

Every request is authenticated with HMAC-SHA256 (timestamp + nonce + body hash)
and protected against replay via a unique nonce per request.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import Any, Optional

import httpx

from api.core.config import settings


class AgentClient:
    """Async client for the privileged HostHive agent running on the same host."""

    def __init__(
        self,
        base_url: str | None = None,
        secret: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = (base_url or settings.AGENT_URL).rstrip("/")
        self._secret = (secret or settings.AGENT_SECRET).encode()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # HMAC auth helpers
    # ------------------------------------------------------------------

    def _sign(self, timestamp: str, nonce: str, body: bytes) -> str:
        body_hash = hashlib.sha256(body).hexdigest()
        message = f"{timestamp}:{nonce}:{body_hash}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def _auth_headers(self, body: bytes) -> dict[str, str]:
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        sig = self._sign(ts, nonce, body)
        return {
            "X-NP-Timestamp": ts,
            "X-NP-Nonce": nonce,
            "X-NP-Signature": sig,
        }

    # ------------------------------------------------------------------
    # Generic request
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body = b""
        if json_body is not None:
            import json as _json
            body = _json.dumps(json_body, default=str).encode()

        headers = self._auth_headers(body)
        if body:
            headers["Content-Type"] = "application/json"

        resp = await self._client.request(
            method,
            path,
            content=body if body else None,
            params=params,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # HTTP method convenience wrappers
    # ------------------------------------------------------------------

    async def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return await self._request("POST", path, json_body=payload, **kwargs)

    async def put(self, path: str, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return await self._request("PUT", path, json_body=payload, **kwargs)

    async def delete(self, path: str, payload: Any = None, **kwargs: Any) -> dict[str, Any]:
        return await self._request("DELETE", path, json_body=payload, **kwargs)

    # ------------------------------------------------------------------
    # Web / Nginx
    # ------------------------------------------------------------------

    async def create_vhost(
        self, domain: str, document_root: str, php_version: str = "8.2",
    ) -> dict[str, Any]:
        return await self._request("POST", "/nginx/vhost", json_body={
            "domain": domain, "document_root": document_root, "php_version": php_version,
        })

    async def delete_vhost(self, domain: str) -> dict[str, Any]:
        return await self._request("DELETE", "/nginx/vhost", json_body={
            "domain": domain,
        })

    # ------------------------------------------------------------------
    # DNS
    # ------------------------------------------------------------------

    async def create_zone(self, zone_name: str, ip: str) -> dict[str, Any]:
        return await self._request("POST", "/dns/zone", json_body={
            "domain": zone_name, "ip": ip,
        })

    async def delete_zone(self, zone_name: str) -> dict[str, Any]:
        return await self._request("DELETE", "/dns/zone", json_body={
            "domain": zone_name,
        })

    async def add_dns_record(
        self, zone: str, record_type: str, name: str, value: str,
        ttl: int = 3600, priority: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "domain": zone, "record_type": record_type, "name": name,
            "value": value, "ttl": ttl,
        }
        if priority is not None:
            payload["priority"] = priority
        return await self._request("POST", "/dns/record", json_body=payload)

    async def delete_dns_record(self, zone: str, record_id: int) -> dict[str, Any]:
        return await self._request("DELETE", "/dns/record", json_body={
            "domain": zone, "record_id": record_id,
        })

    # ------------------------------------------------------------------
    # Mail
    # ------------------------------------------------------------------

    async def create_mailbox(
        self, address: str, password: str, quota_mb: int = 1024,
    ) -> dict[str, Any]:
        return await self._request("POST", "/mail/mailbox", json_body={
            "address": address, "password": password, "quota_mb": quota_mb,
        })

    async def delete_mailbox(self, address: str) -> dict[str, Any]:
        return await self._request("DELETE", "/mail/mailbox", json_body={
            "address": address,
        })

    async def create_mail_alias(self, source: str, destination: str) -> dict[str, Any]:
        return await self._request("POST", "/mail/alias", json_body={
            "from_addr": source, "to_addr": destination,
        })

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    async def create_database(
        self, db_name: str, db_user: str, db_password: str, db_type: str = "mysql",
    ) -> dict[str, Any]:
        path = f"/db/{db_type}"
        return await self._request("POST", path, json_body={
            "db_name": db_name, "db_user": db_user, "db_password": db_password,
        })

    async def delete_database(
        self, db_name: str, db_user: str, db_type: str = "mysql",
    ) -> dict[str, Any]:
        path = f"/db/{db_type}"
        return await self._request("DELETE", path, json_body={
            "db_name": db_name, "db_user": db_user,
        })

    # ------------------------------------------------------------------
    # FTP
    # ------------------------------------------------------------------

    async def create_ftp_account(
        self, username: str, password: str, home_dir: str,
    ) -> dict[str, Any]:
        return await self._request("POST", "/ftp/user", json_body={
            "username": username, "password": password, "home_dir": home_dir,
        })

    async def delete_ftp_account(self, username: str) -> dict[str, Any]:
        return await self._request("DELETE", "/ftp/user", json_body={
            "username": username,
        })

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------

    async def set_crontab(self, username: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", "/cron", json_body={
            "username": username, "entries": entries,
        })

    # ------------------------------------------------------------------
    # SSL
    # ------------------------------------------------------------------

    async def issue_ssl(self, domain: str, email: str) -> dict[str, Any]:
        return await self._request("POST", "/ssl/letsencrypt", json_body={
            "domain": domain, "email": email,
        })

    async def install_custom_ssl(
        self, domain: str, cert_pem: str, key_pem: str,
    ) -> dict[str, Any]:
        return await self._request("POST", "/ssl/custom", json_body={
            "domain": domain, "cert_pem": cert_pem, "key_pem": key_pem,
        })

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    async def create_backup(self, username: str, backup_type: str = "full") -> dict[str, Any]:
        return await self._request("POST", "/backup/create", json_body={
            "username": username, "backup_type": backup_type,
        })

    async def restore_backup(self, username: str, backup_file: str) -> dict[str, Any]:
        return await self._request("POST", "/backup/restore", json_body={
            "username": username, "backup_file": backup_file,
        })

    # ------------------------------------------------------------------
    # System / services
    # ------------------------------------------------------------------

    async def service_action(self, service: str, action: str = "restart") -> dict[str, Any]:
        return await self._request("POST", "/system/service/restart", json_body={
            "name": service,
        })

    async def get_server_stats(self) -> dict[str, Any]:
        return await self._request("GET", "/system/stats")

    async def firewall_add_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/system/firewall/rule", json_body=rule)

    async def firewall_delete_rule(self, rule_id: int) -> dict[str, Any]:
        return await self._request("DELETE", "/system/firewall/rule", json_body={
            "rule_id": rule_id,
        })

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def list_files(self, path: str) -> dict[str, Any]:
        return await self._request("GET", "/files", params={"path": path})

    async def read_file(self, path: str) -> dict[str, Any]:
        return await self._request("GET", "/files/read", params={"path": path})

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        return await self._request("POST", "/files/write", json_body={
            "path": path, "content": content,
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
