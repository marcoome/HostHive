"""Tests for the git deploy router -- /api/v1/domains/{domain_id}/git."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _create_domain(client, token, domain_name="git-test.com"):
    """Create a domain and return its id."""
    with patch("api.routers.domains.nginx_service") as mock_nginx:
        mock_nginx.create_vhost = AsyncMock(return_value={"warnings": []})
        mock_nginx.list_templates.return_value = ["default"]
        resp = await client.post(
            "/api/v1/domains",
            json={"domain_name": domain_name, "php_version": "8.2"},
            headers=auth_header(token),
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _patch_git_service(**overrides):
    """Patch git_deploy_service functions."""
    defaults = {
        "generate_deploy_keypair": AsyncMock(return_value=(
            "ssh-ed25519 AAAA... deploy@hosthive",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nfakeprivatekey\n-----END OPENSSH PRIVATE KEY-----",
        )),
        "generate_webhook_secret": MagicMock(return_value="whsec_test1234567890"),
        "execute_deploy": AsyncMock(return_value={
            "success": True,
            "commit_hash": "abc123def456",
            "output": "Cloned and built successfully",
            "duration_seconds": 12,
        }),
        "detect_webhook_provider": MagicMock(return_value="github"),
        "verify_github_signature": MagicMock(return_value=True),
        "verify_gitlab_token": MagicMock(return_value=True),
        "verify_bitbucket_signature": MagicMock(return_value=True),
        "extract_branch_from_webhook": MagicMock(return_value="main"),
    }
    defaults.update(overrides)
    return patch.multiple("api.routers.git_deploy.git_deploy_service", **defaults)


def _patch_encryption():
    """Patch encrypt/decrypt used for deploy keys."""
    return patch.multiple(
        "api.routers.git_deploy",
        encrypt_value=MagicMock(side_effect=lambda v, k: f"enc:{v}"),
        decrypt_value=MagicMock(side_effect=lambda v, k: v.replace("enc:", "")),
    )


async def _setup_git(client, token, domain_id, **overrides):
    """Set up git deploy for a domain and return the response."""
    payload = {
        "repo_url": "git@github.com:user/repo.git",
        "branch": "main",
        "auto_deploy": True,
        "build_command": "npm install && npm run build",
    }
    payload.update(overrides)
    with _patch_git_service(), _patch_encryption():
        resp = await client.post(
            f"/api/v1/domains/{domain_id}/git/setup",
            json=payload,
            headers=auth_header(token),
        )
    return resp


# --------------------------------------------------------------------------
# POST /git/setup -- setup git deployment
# --------------------------------------------------------------------------


class TestSetupGit:
    async def test_setup_git(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token)
        resp = await _setup_git(client, admin_token, domain_id)
        assert resp.status_code == 201
        body = resp.json()
        assert body["repo_url"] == "git@github.com:user/repo.git"
        assert body["branch"] == "main"
        assert body["auto_deploy"] is True
        assert body["deploy_key_public"] is not None
        assert body["webhook_secret"] is not None
        assert "webhook_url" in body
        assert "id" in body

    async def test_setup_git_duplicate_rejected(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-dup.com")
        await _setup_git(client, admin_token, domain_id)
        resp = await _setup_git(client, admin_token, domain_id)
        assert resp.status_code == 409


# --------------------------------------------------------------------------
# GET /git/status -- get deployment status
# --------------------------------------------------------------------------


class TestGetStatus:
    async def test_get_status(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-status.com")
        await _setup_git(client, admin_token, domain_id)

        resp = await client.get(
            f"/api/v1/domains/{domain_id}/git/status",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["repo_url"] == "git@github.com:user/repo.git"
        assert body["branch"] == "main"
        assert "webhook_url" in body

    async def test_get_status_no_setup(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-no-setup.com")
        resp = await client.get(
            f"/api/v1/domains/{domain_id}/git/status",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# POST /git/deploy -- trigger manual deploy
# --------------------------------------------------------------------------


class TestManualDeploy:
    async def test_manual_deploy(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-deploy.com")
        await _setup_git(client, admin_token, domain_id)

        with _patch_git_service(), _patch_encryption():
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/git/deploy",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["status"] == "success"
        assert body["commit_hash"] == "abc123def456"
        assert body["duration_seconds"] == 12

    async def test_manual_deploy_with_build_override(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-override.com")
        await _setup_git(client, admin_token, domain_id)

        with _patch_git_service(), _patch_encryption():
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/git/deploy",
                json={"build_command": "make build"},
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_manual_deploy_failure(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-fail.com")
        await _setup_git(client, admin_token, domain_id)

        failed_result = {
            "success": False,
            "commit_hash": None,
            "output": "Build failed: exit code 1",
            "duration_seconds": 5,
        }
        with _patch_git_service(execute_deploy=AsyncMock(return_value=failed_result)), _patch_encryption():
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/git/deploy",
                headers=auth_header(admin_token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["status"] == "failed"


# --------------------------------------------------------------------------
# POST /git/webhook -- GitHub webhook
# --------------------------------------------------------------------------


class TestWebhookGitHub:
    async def test_webhook_github(self, client, admin_user, admin_token, db_session):
        domain_id = await _create_domain(client, admin_token, "git-webhook.com")
        await _setup_git(client, admin_token, domain_id)

        webhook_body = json.dumps({"ref": "refs/heads/main"}).encode()

        with _patch_git_service(), _patch_encryption():
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/git/webhook",
                content=webhook_body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": "sha256=fakesig",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "success"

    async def test_webhook_invalid_signature(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-badsig.com")
        await _setup_git(client, admin_token, domain_id)

        webhook_body = json.dumps({"ref": "refs/heads/main"}).encode()

        with _patch_git_service(verify_github_signature=MagicMock(return_value=False)):
            resp = await client.post(
                f"/api/v1/domains/{domain_id}/git/webhook",
                content=webhook_body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )
        assert resp.status_code == 403

    async def test_webhook_auto_deploy_disabled(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-no-auto.com")
        await _setup_git(client, admin_token, domain_id, auto_deploy=False)

        webhook_body = json.dumps({"ref": "refs/heads/main"}).encode()

        resp = await client.post(
            f"/api/v1/domains/{domain_id}/git/webhook",
            content=webhook_body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=anything",
            },
        )
        assert resp.status_code == 200
        assert "disabled" in resp.json()["message"].lower()


# --------------------------------------------------------------------------
# DELETE /git/remove -- remove git deployment
# --------------------------------------------------------------------------


class TestRemoveGit:
    async def test_remove_git(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-remove.com")
        await _setup_git(client, admin_token, domain_id)

        resp = await client.delete(
            f"/api/v1/domains/{domain_id}/git/remove",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 204

        # Verify it is gone
        resp = await client.get(
            f"/api/v1/domains/{domain_id}/git/status",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404

    async def test_remove_git_not_configured(self, client, admin_user, admin_token):
        domain_id = await _create_domain(client, admin_token, "git-rm-none.com")
        resp = await client.delete(
            f"/api/v1/domains/{domain_id}/git/remove",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404
