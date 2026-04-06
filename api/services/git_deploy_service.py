"""Git deployment service -- handles clone, pull, build, and webhook verification."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger("hosthive.git_deploy")


# ---------------------------------------------------------------------------
# SSH key generation
# ---------------------------------------------------------------------------

async def generate_deploy_keypair() -> tuple[str, str]:
    """Generate an Ed25519 SSH keypair for deploy key usage.

    Returns (public_key, private_key) as strings.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = os.path.join(tmpdir, "deploy_key")
        proc = await asyncio.create_subprocess_exec(
            "ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "hosthive-deploy",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("Failed to generate SSH deploy key")

        private_key = Path(key_path).read_text()
        public_key = Path(f"{key_path}.pub").read_text().strip()

    return public_key, private_key


def generate_webhook_secret() -> str:
    """Generate a random webhook secret token."""
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

async def _run_cmd(cmd: list[str], cwd: str, env: dict | None = None,
                   timeout: int = 300) -> tuple[int, str]:
    """Run a shell command and return (return_code, combined_output)."""
    merged_env = {**os.environ, **(env or {})}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=merged_env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "Command timed out"
    return proc.returncode, stdout.decode("utf-8", errors="replace")


def _build_ssh_command(private_key_path: str) -> str:
    """Return a GIT_SSH_COMMAND that uses the deploy key."""
    return f"ssh -i {private_key_path} -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"


async def clone_or_pull(
    repo_url: str,
    branch: str,
    document_root: str,
    private_key_pem: str,
) -> tuple[int, str, str | None]:
    """Clone a repo into *document_root* or pull if it already exists.

    Returns (return_code, output_log, commit_hash).
    """
    output_parts: list[str] = []

    # Write the deploy key to a temp file
    tmpdir = tempfile.mkdtemp(prefix="hh-deploy-")
    key_path = os.path.join(tmpdir, "deploy_key")
    try:
        Path(key_path).write_text(private_key_pem)
        os.chmod(key_path, 0o600)

        git_ssh = _build_ssh_command(key_path)
        env = {"GIT_SSH_COMMAND": git_ssh}

        git_dir = os.path.join(document_root, ".git")

        if os.path.isdir(git_dir):
            # Existing repo -- fetch & reset
            rc, out = await _run_cmd(["git", "fetch", "origin", branch], cwd=document_root, env=env)
            output_parts.append(f"$ git fetch origin {branch}\n{out}")
            if rc != 0:
                return rc, "\n".join(output_parts), None

            rc, out = await _run_cmd(["git", "reset", "--hard", f"origin/{branch}"], cwd=document_root, env=env)
            output_parts.append(f"$ git reset --hard origin/{branch}\n{out}")
            if rc != 0:
                return rc, "\n".join(output_parts), None

            rc, out = await _run_cmd(["git", "clean", "-fd"], cwd=document_root, env=env)
            output_parts.append(f"$ git clean -fd\n{out}")
        else:
            # Fresh clone
            os.makedirs(document_root, exist_ok=True)
            rc, out = await _run_cmd(
                ["git", "clone", "--branch", branch, "--single-branch", repo_url, "."],
                cwd=document_root, env=env,
            )
            output_parts.append(f"$ git clone --branch {branch} {repo_url}\n{out}")
            if rc != 0:
                return rc, "\n".join(output_parts), None

        # Get current commit hash
        rc, commit_out = await _run_cmd(["git", "rev-parse", "HEAD"], cwd=document_root, env=env)
        commit_hash = commit_out.strip()[:40] if rc == 0 else None

        return 0, "\n".join(output_parts), commit_hash
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def run_build_command(
    build_command: str,
    document_root: str,
) -> tuple[int, str]:
    """Run a build command (e.g. 'npm install && npm run build') in document_root."""
    _log.info("Running build command in %s: %s", document_root, build_command)
    proc = await asyncio.create_subprocess_shell(
        build_command,
        cwd=document_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "HOME": str(Path(document_root).parent.parent)},
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "Build command timed out (10 min limit)"
    output = stdout.decode("utf-8", errors="replace")
    return proc.returncode, f"$ {build_command}\n{output}"


async def run_post_deploy_hook(
    hook_command: str,
    document_root: str,
) -> tuple[int, str]:
    """Run a post-deploy hook command."""
    _log.info("Running post-deploy hook in %s: %s", document_root, hook_command)
    proc = await asyncio.create_subprocess_shell(
        hook_command,
        cwd=document_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "Post-deploy hook timed out (2 min limit)"
    output = stdout.decode("utf-8", errors="replace")
    return proc.returncode, f"$ {hook_command}\n{output}"


# ---------------------------------------------------------------------------
# Full deploy pipeline
# ---------------------------------------------------------------------------

async def execute_deploy(
    repo_url: str,
    branch: str,
    document_root: str,
    private_key_pem: str,
    build_command: str | None = None,
    post_deploy_hook: str | None = None,
) -> dict:
    """Execute the full deployment pipeline: clone/pull -> build -> post-deploy.

    Returns a dict with keys: success, output, commit_hash, duration_seconds.
    """
    start = time.monotonic()
    output_parts: list[str] = []

    # Step 1: clone or pull
    rc, out, commit_hash = await clone_or_pull(repo_url, branch, document_root, private_key_pem)
    output_parts.append(out)
    if rc != 0:
        duration = int(time.monotonic() - start)
        return {
            "success": False,
            "output": "\n".join(output_parts),
            "commit_hash": commit_hash,
            "duration_seconds": duration,
        }

    # Step 2: build command
    if build_command:
        rc, out = await run_build_command(build_command, document_root)
        output_parts.append(out)
        if rc != 0:
            duration = int(time.monotonic() - start)
            return {
                "success": False,
                "output": "\n".join(output_parts),
                "commit_hash": commit_hash,
                "duration_seconds": duration,
            }

    # Step 3: post-deploy hook
    if post_deploy_hook:
        rc, out = await run_post_deploy_hook(post_deploy_hook, document_root)
        output_parts.append(out)
        if rc != 0:
            duration = int(time.monotonic() - start)
            return {
                "success": False,
                "output": "\n".join(output_parts),
                "commit_hash": commit_hash,
                "duration_seconds": duration,
            }

    duration = int(time.monotonic() - start)
    return {
        "success": True,
        "output": "\n".join(output_parts),
        "commit_hash": commit_hash,
        "duration_seconds": duration,
    }


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------

def verify_github_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub X-Hub-Signature-256 header."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def verify_gitlab_token(token_header: str, secret: str) -> bool:
    """Verify GitLab X-Gitlab-Token header."""
    if not token_header:
        return False
    return hmac.compare_digest(token_header, secret)


def verify_bitbucket_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify Bitbucket X-Hub-Signature header (sha256)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def extract_branch_from_webhook(body: dict, provider: str) -> str | None:
    """Extract the pushed branch name from a webhook payload."""
    if provider == "github":
        ref = body.get("ref", "")
        if ref.startswith("refs/heads/"):
            return ref.removeprefix("refs/heads/")
    elif provider == "gitlab":
        ref = body.get("ref", "")
        if ref.startswith("refs/heads/"):
            return ref.removeprefix("refs/heads/")
    elif provider == "bitbucket":
        changes = body.get("push", {}).get("changes", [])
        if changes:
            new = changes[0].get("new", {})
            return new.get("name")
    return None


def detect_webhook_provider(headers: dict) -> str:
    """Detect webhook provider from request headers."""
    if "x-github-event" in headers:
        return "github"
    if "x-gitlab-event" in headers:
        return "gitlab"
    if "x-hook-uuid" in headers:
        return "bitbucket"
    return "unknown"
