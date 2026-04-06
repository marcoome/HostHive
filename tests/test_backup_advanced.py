"""Tests for advanced backup features -- schedule, retention, S3 upload/list."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# PUT /schedule -- backup schedule persists to DB
# --------------------------------------------------------------------------


class TestBackupSchedule:
    async def test_backup_schedule_persists_to_db(
        self, client, admin_user, admin_token, db_session
    ):
        """Setting a backup schedule should persist to the User row in the database."""
        resp = await client.put(
            "/api/v1/backups/schedule",
            json={
                "enabled": True,
                "frequency": "daily",
                "backup_type": "full",
                "retention_days": 14,
                "retention_count": 10,
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["frequency"] == "daily"
        assert body["retention_days"] == 14
        assert body["retention_count"] == 10

        # Verify it persisted by reading it back
        get_resp = await client.get(
            "/api/v1/backups/schedule",
            headers=auth_header(admin_token),
        )
        assert get_resp.status_code == 200
        get_body = get_resp.json()
        assert get_body["enabled"] is True
        assert get_body["frequency"] == "daily"
        assert get_body["retention_days"] == 14
        assert get_body["retention_count"] == 10

    async def test_backup_schedule_update_overwrites(
        self, client, admin_user, admin_token
    ):
        """Updating the schedule should overwrite the previous values."""
        # Set initial schedule
        await client.put(
            "/api/v1/backups/schedule",
            json={
                "enabled": True,
                "frequency": "daily",
                "backup_type": "full",
                "retention_days": 30,
                "retention_count": 5,
            },
            headers=auth_header(admin_token),
        )

        # Overwrite with new values
        resp = await client.put(
            "/api/v1/backups/schedule",
            json={
                "enabled": False,
                "frequency": "weekly",
                "backup_type": "incremental",
                "retention_days": 60,
                "retention_count": 20,
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["frequency"] == "weekly"
        assert body["backup_type"] == "incremental"
        assert body["retention_days"] == 60


# --------------------------------------------------------------------------
# Retention per user
# --------------------------------------------------------------------------


class TestRetentionPerUser:
    async def test_retention_per_user(
        self, client, admin_user, admin_token, regular_user, user_token
    ):
        """Each user should have their own independent backup retention settings."""
        # Admin sets retention
        await client.put(
            "/api/v1/backups/schedule",
            json={
                "enabled": True,
                "frequency": "daily",
                "backup_type": "full",
                "retention_days": 7,
                "retention_count": 3,
            },
            headers=auth_header(admin_token),
        )

        # Regular user sets different retention
        await client.put(
            "/api/v1/backups/schedule",
            json={
                "enabled": True,
                "frequency": "weekly",
                "backup_type": "full",
                "retention_days": 90,
                "retention_count": 50,
            },
            headers=auth_header(user_token),
        )

        # Verify they are independent
        admin_schedule = await client.get(
            "/api/v1/backups/schedule",
            headers=auth_header(admin_token),
        )
        user_schedule = await client.get(
            "/api/v1/backups/schedule",
            headers=auth_header(user_token),
        )

        assert admin_schedule.json()["retention_days"] == 7
        assert admin_schedule.json()["retention_count"] == 3
        assert user_schedule.json()["retention_days"] == 90
        assert user_schedule.json()["retention_count"] == 50


# --------------------------------------------------------------------------
# POST /{id}/upload-remote -- S3 upload
# --------------------------------------------------------------------------


class TestS3Upload:
    async def test_s3_upload_endpoint(
        self, client, admin_user, admin_token, db_session
    ):
        """Uploading a completed backup to S3 should call the S3 service."""
        from api.models.backups import Backup, BackupStatus, BackupType

        backup = Backup(
            user_id=admin_user.id,
            backup_type=BackupType.FULL,
            status=BackupStatus.COMPLETED,
            file_path="/opt/hosthive/backups/test_backup.tar.gz",
            size_bytes=1024,
        )
        db_session.add(backup)
        await db_session.flush()
        await db_session.refresh(backup)

        mock_s3 = AsyncMock()
        mock_s3.upload_backup.return_value = {
            "key": f"backups/{admin_user.id}/test_backup.tar.gz",
            "size": 1024,
        }

        with patch("api.routers.backups._get_s3_service", return_value=mock_s3):
            with patch("os.path.isfile", return_value=True):
                resp = await client.post(
                    f"/api/v1/backups/{backup.id}/upload-remote",
                    headers=auth_header(admin_token),
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "remote_key" in body
        assert body["remote_key"].startswith("backups/")
        mock_s3.upload_backup.assert_called_once()

    async def test_s3_upload_incomplete_backup_rejected(
        self, client, admin_user, admin_token, db_session
    ):
        """Uploading an incomplete backup should be rejected."""
        from api.models.backups import Backup, BackupStatus, BackupType

        backup = Backup(
            user_id=admin_user.id,
            backup_type=BackupType.FULL,
            status=BackupStatus.IN_PROGRESS,
        )
        db_session.add(backup)
        await db_session.flush()
        await db_session.refresh(backup)

        resp = await client.post(
            f"/api/v1/backups/{backup.id}/upload-remote",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------
# GET /remote -- list remote backups
# --------------------------------------------------------------------------


class TestRemoteList:
    async def test_remote_list_endpoint(self, client, admin_user, admin_token):
        """Listing remote backups should call S3 service and return objects."""
        mock_s3 = AsyncMock()
        mock_s3.list_backups.return_value = [
            {"key": "backups/abc/full_2026.tar.gz", "size": 2048, "last_modified": "2026-01-01T00:00:00Z"},
            {"key": "backups/abc/inc_2026.tar.gz", "size": 512, "last_modified": "2026-01-02T00:00:00Z"},
        ]

        with patch("api.routers.backups._get_s3_service", return_value=mock_s3):
            resp = await client.get(
                "/api/v1/backups/remote",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert body["total"] == 2
        assert len(body["items"]) == 2
        # Admin sees all (prefix is empty)
        mock_s3.list_backups.assert_called_once_with(prefix="")

    async def test_remote_list_scoped_to_user(self, client, regular_user, user_token):
        """Non-admin users should only see their own remote backups."""
        mock_s3 = AsyncMock()
        mock_s3.list_backups.return_value = []

        with patch("api.routers.backups._get_s3_service", return_value=mock_s3):
            resp = await client.get(
                "/api/v1/backups/remote",
                headers=auth_header(user_token),
            )

        assert resp.status_code == 200
        # Non-admin prefix should include the user ID
        call_args = mock_s3.list_backups.call_args
        assert str(regular_user.id) in call_args.kwargs.get("prefix", call_args.args[0] if call_args.args else "")
