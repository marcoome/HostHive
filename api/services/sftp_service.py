"""SFTP backup storage service using paramiko.

Supports any SFTP-accessible server with password or key-based authentication.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

import paramiko

from api.core.config import settings
from api.core.encryption import decrypt_value

logger = logging.getLogger("hosthive.sftp")

_CONNECT_TIMEOUT = 15
_TRANSFER_TIMEOUT = 600  # 10 minutes for large backup uploads


class SFTPBackupService:
    """SFTP-based remote backup storage."""

    def __init__(self, encrypted_config: str) -> None:
        config = json.loads(decrypt_value(encrypted_config, settings.SECRET_KEY))
        self._init_from_dict(config)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "SFTPBackupService":
        """Create an instance directly from a plain config dict."""
        instance = cls.__new__(cls)
        instance._init_from_dict(config)
        return instance

    def _init_from_dict(self, config: Dict[str, Any]) -> None:
        self._hostname: str = config["hostname"]
        self._port: int = int(config.get("port", 22))
        self._username: str = config["username"]
        self._password: Optional[str] = config.get("password")
        self._key_path: Optional[str] = config.get("key_path")
        self._remote_path: str = config.get("remote_path", "/backups").rstrip("/")

    def _connect(self) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """Open an SSH + SFTP connection and return both clients."""
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: Dict[str, Any] = {
            "hostname": self._hostname,
            "port": self._port,
            "username": self._username,
            "timeout": _CONNECT_TIMEOUT,
        }

        if self._key_path and os.path.isfile(self._key_path):
            connect_kwargs["key_filename"] = self._key_path
        elif self._password:
            connect_kwargs["password"] = self._password
        else:
            raise RuntimeError(
                "SFTP authentication requires either a password or key_path."
            )

        ssh.connect(**connect_kwargs)
        sftp = ssh.open_sftp()
        sftp.get_channel().settimeout(_TRANSFER_TIMEOUT)
        return ssh, sftp

    def _ensure_remote_dir(self, sftp: paramiko.SFTPClient, path: str) -> None:
        """Recursively create remote directories if they don't exist."""
        dirs_to_create: list[str] = []
        current = path
        while current and current != "/":
            try:
                sftp.stat(current)
                break  # exists
            except FileNotFoundError:
                dirs_to_create.append(current)
                current = os.path.dirname(current)

        for d in reversed(dirs_to_create):
            try:
                sftp.mkdir(d)
            except OSError:
                pass  # may already exist due to race

    # ------------------------------------------------------------------
    # Public API (synchronous -- called from Celery or wrapped in executor)
    # ------------------------------------------------------------------

    async def upload_backup(self, file_path: str, remote_key: str) -> Dict[str, Any]:
        """Upload a local file to the SFTP server."""
        local = Path(file_path)
        if not local.is_file():
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        remote_full = f"{self._remote_path}/{remote_key}"
        ssh, sftp = self._connect()
        try:
            self._ensure_remote_dir(sftp, os.path.dirname(remote_full))
            sftp.put(str(local), remote_full)
            file_stat = sftp.stat(remote_full)
            size = file_stat.st_size if file_stat.st_size else local.stat().st_size
        finally:
            sftp.close()
            ssh.close()

        logger.info("SFTP uploaded %s -> %s:%s", file_path, self._hostname, remote_full)
        return {"key": remote_key, "size": size}

    async def download_backup(self, remote_key: str, local_path: str) -> str:
        """Download a backup from the SFTP server to a local file."""
        remote_full = f"{self._remote_path}/{remote_key}"
        out = Path(local_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        ssh, sftp = self._connect()
        try:
            sftp.get(remote_full, str(out))
        finally:
            sftp.close()
            ssh.close()

        logger.info("SFTP downloaded %s:%s -> %s", self._hostname, remote_full, local_path)
        return local_path

    async def delete_backup(self, remote_key: str) -> None:
        """Delete a single file from the SFTP server."""
        remote_full = f"{self._remote_path}/{remote_key}"
        ssh, sftp = self._connect()
        try:
            sftp.remove(remote_full)
        finally:
            sftp.close()
            ssh.close()

        logger.info("SFTP deleted %s:%s", self._hostname, remote_full)

    async def list_backups(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List files under the remote path, optionally filtered by prefix."""
        search_dir = self._remote_path
        if prefix:
            search_dir = f"{self._remote_path}/{prefix}".rstrip("/")

        ssh, sftp = self._connect()
        try:
            objects: List[Dict[str, Any]] = []
            try:
                entries = sftp.listdir_attr(search_dir)
            except FileNotFoundError:
                return []

            for entry in entries:
                if stat.S_ISREG(entry.st_mode or 0):
                    key = f"{prefix}{entry.filename}" if prefix else entry.filename
                    objects.append({
                        "key": key,
                        "size": entry.st_size or 0,
                        "last_modified": str(entry.st_mtime or ""),
                    })
        finally:
            sftp.close()
            ssh.close()

        logger.info("SFTP listed %d objects in %s", len(objects), search_dir)
        return objects

    async def cleanup_old_backups(self, keep: int = 30) -> int:
        """Delete all but the most recent *keep* backups (by modification time)."""
        all_objects = await self.list_backups()
        if len(all_objects) <= keep:
            logger.info("SFTP: only %d backups exist, nothing to clean up", len(all_objects))
            return 0

        sorted_objects = sorted(
            all_objects,
            key=lambda o: float(o.get("last_modified", "0") or "0"),
            reverse=True,
        )
        to_delete = sorted_objects[keep:]

        deleted = 0
        for obj in to_delete:
            try:
                await self.delete_backup(obj["key"])
                deleted += 1
            except Exception:
                logger.warning("SFTP: failed to delete old backup %s", obj["key"])

        logger.info("SFTP cleaned up %d old backups (kept %d)", deleted, keep)
        return deleted

    def upload_backup_sync(self, file_path: str, remote_key: str) -> Dict[str, Any]:
        """Synchronous upload for use in Celery tasks."""
        local = Path(file_path)
        if not local.is_file():
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        remote_full = f"{self._remote_path}/{remote_key}"
        ssh, sftp = self._connect()
        try:
            self._ensure_remote_dir(sftp, os.path.dirname(remote_full))
            sftp.put(str(local), remote_full)
            file_stat = sftp.stat(remote_full)
            size = file_stat.st_size if file_stat.st_size else local.stat().st_size
        finally:
            sftp.close()
            ssh.close()

        logger.info("SFTP uploaded (sync) %s -> %s:%s", file_path, self._hostname, remote_full)
        return {"key": remote_key, "size": size}

    def cleanup_old_backups_sync(self, keep: int = 30) -> int:
        """Synchronous cleanup for use in Celery tasks."""
        ssh, sftp = self._connect()
        try:
            try:
                entries = sftp.listdir_attr(self._remote_path)
            except FileNotFoundError:
                return 0

            files = [
                e for e in entries if stat.S_ISREG(e.st_mode or 0)
            ]
            if len(files) <= keep:
                return 0

            sorted_files = sorted(
                files, key=lambda e: e.st_mtime or 0, reverse=True
            )
            to_delete = sorted_files[keep:]

            deleted = 0
            for entry in to_delete:
                try:
                    sftp.remove(f"{self._remote_path}/{entry.filename}")
                    deleted += 1
                except Exception:
                    logger.warning("SFTP: failed to delete %s", entry.filename)
        finally:
            sftp.close()
            ssh.close()

        logger.info("SFTP cleaned up %d old backups (kept %d)", deleted, keep)
        return deleted
