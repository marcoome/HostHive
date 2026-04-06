"""Rclone-based backup storage service.

Shells out to the ``rclone`` CLI which supports 50+ cloud storage providers
(Google Drive, Backblaze B2, Dropbox, OneDrive, etc.).

The user is expected to have a pre-configured rclone remote on the server
(via ``rclone config``).  This service only needs the remote name and a
remote path prefix.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.core.config import settings
from api.core.encryption import decrypt_value

logger = logging.getLogger("hosthive.rclone")

_CMD_TIMEOUT = 600  # 10 minutes for large transfers
_LIST_TIMEOUT = 60


class RcloneBackupService:
    """Remote backup storage powered by the rclone CLI."""

    def __init__(self, encrypted_config: str) -> None:
        config = json.loads(decrypt_value(encrypted_config, settings.SECRET_KEY))
        self._init_from_dict(config)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RcloneBackupService":
        """Create an instance directly from a plain config dict."""
        instance = cls.__new__(cls)
        instance._init_from_dict(config)
        return instance

    def _init_from_dict(self, config: Dict[str, Any]) -> None:
        self._remote_name: str = config["remote_name"].rstrip(":")
        self._remote_path: str = config.get("remote_path", "/backups").strip("/")

        # Validate that rclone is installed
        if not shutil.which("rclone"):
            raise RuntimeError(
                "rclone binary not found in PATH. "
                "Install it: https://rclone.org/install/"
            )

    @property
    def _remote_prefix(self) -> str:
        """Return the full rclone remote:path prefix."""
        return f"{self._remote_name}:{self._remote_path}"

    @staticmethod
    def _run(args: list[str], timeout: int = _CMD_TIMEOUT) -> subprocess.CompletedProcess:
        """Run an rclone sub-command and return the result."""
        cmd = ["rclone"] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"rclone command failed (rc={result.returncode}): "
                f"{' '.join(cmd)}\nstderr: {result.stderr.strip()}"
            )
        return result

    def test_connection(self) -> bool:
        """Verify the rclone remote is reachable by listing top-level dirs."""
        try:
            self._run(
                ["lsd", f"{self._remote_name}:"],
                timeout=_LIST_TIMEOUT,
            )
            return True
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            logger.warning("Rclone connection test failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_backup(self, file_path: str, remote_key: str) -> Dict[str, Any]:
        """Upload a local file to the rclone remote."""
        local = Path(file_path)
        if not local.is_file():
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        remote_dest = f"{self._remote_prefix}/{os.path.dirname(remote_key)}"
        self._run(["copy", str(local), remote_dest])

        size = local.stat().st_size
        logger.info("Rclone uploaded %s -> %s/%s", file_path, self._remote_prefix, remote_key)
        return {"key": remote_key, "size": size}

    async def download_backup(self, remote_key: str, local_path: str) -> str:
        """Download a backup from the rclone remote to a local file."""
        remote_src = f"{self._remote_prefix}/{remote_key}"
        out = Path(local_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # rclone copyto copies a single file to a specific destination path
        self._run(["copyto", remote_src, str(out)])

        logger.info("Rclone downloaded %s -> %s", remote_src, local_path)
        return local_path

    async def delete_backup(self, remote_key: str) -> None:
        """Delete a single file from the rclone remote."""
        remote_file = f"{self._remote_prefix}/{remote_key}"
        self._run(["deletefile", remote_file])
        logger.info("Rclone deleted %s", remote_file)

    async def list_backups(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List files under the remote path, optionally filtered by prefix."""
        search_path = self._remote_prefix
        if prefix:
            search_path = f"{self._remote_prefix}/{prefix.strip('/')}"

        try:
            result = self._run(
                ["lsjson", search_path],
                timeout=_LIST_TIMEOUT,
            )
        except RuntimeError:
            # Directory may not exist yet
            return []

        entries = json.loads(result.stdout) if result.stdout.strip() else []
        objects: List[Dict[str, Any]] = []
        for entry in entries:
            if entry.get("IsDir", False):
                continue
            key = f"{prefix}{entry['Name']}" if prefix else entry["Name"]
            objects.append({
                "key": key,
                "size": entry.get("Size", 0),
                "last_modified": entry.get("ModTime", ""),
            })

        logger.info("Rclone listed %d objects in %s", len(objects), search_path)
        return objects

    async def cleanup_old_backups(self, keep: int = 30) -> int:
        """Delete all but the most recent *keep* backups (by modification time)."""
        all_objects = await self.list_backups()
        if len(all_objects) <= keep:
            logger.info("Rclone: only %d backups exist, nothing to clean up", len(all_objects))
            return 0

        sorted_objects = sorted(
            all_objects,
            key=lambda o: o.get("last_modified", ""),
            reverse=True,
        )
        to_delete = sorted_objects[keep:]

        deleted = 0
        for obj in to_delete:
            try:
                await self.delete_backup(obj["key"])
                deleted += 1
            except Exception:
                logger.warning("Rclone: failed to delete old backup %s", obj["key"])

        logger.info("Rclone cleaned up %d old backups (kept %d)", deleted, keep)
        return deleted

    def upload_backup_sync(self, file_path: str, remote_key: str) -> Dict[str, Any]:
        """Synchronous upload for use in Celery tasks."""
        local = Path(file_path)
        if not local.is_file():
            raise FileNotFoundError(f"Backup file not found: {file_path}")

        remote_dest = f"{self._remote_prefix}/{os.path.dirname(remote_key)}"
        self._run(["copy", str(local), remote_dest])

        size = local.stat().st_size
        logger.info("Rclone uploaded (sync) %s -> %s/%s", file_path, self._remote_prefix, remote_key)
        return {"key": remote_key, "size": size}

    def cleanup_old_backups_sync(self, keep: int = 30) -> int:
        """Synchronous cleanup for use in Celery tasks."""
        try:
            result = self._run(
                ["lsjson", self._remote_prefix],
                timeout=_LIST_TIMEOUT,
            )
        except RuntimeError:
            return 0

        entries = json.loads(result.stdout) if result.stdout.strip() else []
        files = [e for e in entries if not e.get("IsDir", False)]

        if len(files) <= keep:
            return 0

        sorted_files = sorted(
            files, key=lambda e: e.get("ModTime", ""), reverse=True
        )
        to_delete = sorted_files[keep:]

        deleted = 0
        for entry in to_delete:
            try:
                remote_file = f"{self._remote_prefix}/{entry['Name']}"
                self._run(["deletefile", remote_file])
                deleted += 1
            except Exception:
                logger.warning("Rclone: failed to delete %s", entry["Name"])

        logger.info("Rclone cleaned up %d old backups (kept %d)", deleted, keep)
        return deleted
