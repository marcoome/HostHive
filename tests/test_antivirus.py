"""Tests for the antivirus router -- /api/v1/antivirus."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# POST /scan -- trigger full scan
# --------------------------------------------------------------------------


class TestAntivirusScanTrigger:
    async def test_scan_trigger_returns_202(self, client, admin_user, admin_token):
        """Triggering a full scan should dispatch to Celery and return 202."""
        mock_task = MagicMock()
        mock_task.id = "celery-task-id-123"

        with patch(
            "api.routers.antivirus.run_antivirus_scan",
            create=True,
        ) as mock_module:
            # We need to patch the import inside the function
            with patch.dict(
                "sys.modules",
                {
                    "api.tasks.server_tasks": MagicMock(
                        run_antivirus_scan=MagicMock(delay=MagicMock(return_value=mock_task))
                    ),
                },
            ):
                resp = await client.post(
                    "/api/v1/antivirus/scan",
                    headers=auth_header(admin_token),
                )

        assert resp.status_code == 202
        body = resp.json()
        assert "scan_id" in body
        assert body["status"] == "pending"
        assert "celery_task_id" in body

    async def test_scan_trigger_requires_admin(self, client, regular_user, user_token):
        """Non-admin users should be rejected."""
        resp = await client.post(
            "/api/v1/antivirus/scan",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# GET /scans -- list scans
# --------------------------------------------------------------------------


class TestAntivirusScanList:
    async def test_scan_list(self, client, admin_user, admin_token):
        """Listing scans should return a paginated response."""
        resp = await client.get(
            "/api/v1/antivirus/scans",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)
        assert body["total"] >= 0

    async def test_scan_list_requires_admin(self, client, regular_user, user_token):
        """Non-admin users should be rejected."""
        resp = await client.get(
            "/api/v1/antivirus/scans",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# GET /status -- ClamAV service status
# --------------------------------------------------------------------------


class TestAntivirusStatus:
    async def test_status_endpoint(self, client, admin_user, admin_token):
        """Status endpoint should return ClamAV state information."""
        with patch(
            "api.routers.antivirus._run_async",
            new_callable=AsyncMock,
        ) as mock_run:
            # Mock all the subprocess calls
            mock_which = MagicMock()
            mock_which.returncode = 0
            mock_which.stdout = "/usr/bin/clamscan"

            mock_daemon = MagicMock()
            mock_daemon.returncode = 0
            mock_daemon.stdout = "active"

            mock_freshclam_svc = MagicMock()
            mock_freshclam_svc.returncode = 0
            mock_freshclam_svc.stdout = "active"

            mock_freshclam_ver = MagicMock()
            mock_freshclam_ver.returncode = 0
            mock_freshclam_ver.stdout = "ClamAV 1.2.0/27100/Thu Jan 1 2026"

            mock_run.side_effect = [
                mock_which,
                mock_daemon,
                mock_freshclam_svc,
                mock_freshclam_ver,
            ]

            with patch("api.routers.antivirus.QUARANTINE_DIR") as mock_qdir:
                mock_qdir.exists.return_value = False
                mock_qdir.__str__ = lambda self: "/opt/hosthive/quarantine"

                resp = await client.get(
                    "/api/v1/antivirus/status",
                    headers=auth_header(admin_token),
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "installed" in body
        assert "daemon_running" in body
        assert "freshclam_running" in body
        assert "database_version" in body

    async def test_status_requires_admin(self, client, regular_user, user_token):
        """Non-admin users should be rejected."""
        resp = await client.get(
            "/api/v1/antivirus/status",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST /update -- trigger freshclam DB update
# --------------------------------------------------------------------------


class TestAntivirusUpdate:
    async def test_update_endpoint(self, client, admin_user, admin_token, db_session):
        """Update endpoint should trigger freshclam and return status."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Database updated successfully"
        mock_result.stderr = ""

        with patch(
            "api.routers.antivirus._run_async",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.post(
                "/api/v1/antivirus/update",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "updated"
        assert body["returncode"] == 0

    async def test_update_requires_admin(self, client, regular_user, user_token):
        """Non-admin users should be rejected."""
        resp = await client.post(
            "/api/v1/antivirus/update",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST /quarantine/{file_id}/restore
# --------------------------------------------------------------------------


class TestAntivirusQuarantineRestore:
    async def test_quarantine_restore(self, client, admin_user, admin_token, db_session):
        """Restoring a quarantined file should move it back to its original location."""
        from api.models.antivirus import QuarantineEntry, ScanResult, ScanStatus

        # Create a scan and quarantine entry in DB
        scan = ScanResult(
            user_id=admin_user.id,
            scan_path="/home",
            status=ScanStatus.COMPLETED,
        )
        db_session.add(scan)
        await db_session.flush()

        entry = QuarantineEntry(
            scan_id=scan.id,
            original_path="/home/testuser/malware.php",
            quarantine_path="/opt/hosthive/quarantine/malware.php.quarantine",
            threat_name="Eicar-Test-Signature",
        )
        db_session.add(entry)
        await db_session.flush()
        await db_session.refresh(entry)

        with patch("api.routers.antivirus.Path") as MockPath:
            mock_quarantine_file = MagicMock()
            mock_quarantine_file.exists.return_value = True

            mock_original_path = MagicMock()
            mock_original_parent = MagicMock()
            mock_original_path.parent = mock_original_parent

            MockPath.side_effect = lambda p: (
                mock_quarantine_file if "quarantine" in str(p) else mock_original_path
            )

            resp = await client.post(
                f"/api/v1/antivirus/quarantine/{entry.id}/restore",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "restored"
        assert body["original_path"] == "/home/testuser/malware.php"

    async def test_quarantine_restore_not_found(self, client, admin_user, admin_token):
        """Restoring a nonexistent quarantine entry should return 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/antivirus/quarantine/{fake_id}/restore",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# POST /quarantine/{file_id}/delete
# --------------------------------------------------------------------------


class TestAntivirusQuarantineDelete:
    async def test_quarantine_delete(self, client, admin_user, admin_token, db_session):
        """Permanently deleting a quarantined file should remove it from disk."""
        from api.models.antivirus import QuarantineEntry, ScanResult, ScanStatus

        scan = ScanResult(
            user_id=admin_user.id,
            scan_path="/home",
            status=ScanStatus.COMPLETED,
        )
        db_session.add(scan)
        await db_session.flush()

        entry = QuarantineEntry(
            scan_id=scan.id,
            original_path="/home/testuser/trojan.sh",
            quarantine_path="/opt/hosthive/quarantine/trojan.sh.quarantine",
            threat_name="Unix.Trojan.Agent",
        )
        db_session.add(entry)
        await db_session.flush()
        await db_session.refresh(entry)

        with patch("api.routers.antivirus.Path") as MockPath:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            MockPath.return_value = mock_file

            resp = await client.post(
                f"/api/v1/antivirus/quarantine/{entry.id}/delete",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "deleted"
        assert body["original_path"] == "/home/testuser/trojan.sh"

    async def test_quarantine_delete_not_found(self, client, admin_user, admin_token):
        """Deleting a nonexistent quarantine entry should return 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/antivirus/quarantine/{fake_id}/delete",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404
