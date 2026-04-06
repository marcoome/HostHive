"""Git deployment router -- /api/v1/domains/{domain_id}/git.

Provides push-to-deploy functionality: setup deploy keys, trigger deploys,
receive webhooks from GitHub / GitLab / Bitbucket.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.domains import Domain
from api.models.git_deploy import DeployLog, GitDeployment
from api.models.users import User
from api.schemas.git_deploy import (
    DeployLogEntry,
    DeployTriggerRequest,
    GitDeployCreate,
    GitDeployResponse,
    GitDeployUpdate,
)
from api.services import git_deploy_service

router = APIRouter()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


async def _get_domain_or_403(
    domain_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> Domain:
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    if not _is_admin(current_user) and domain.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return domain


async def _get_deployment_or_404(
    domain_id: uuid.UUID,
    db: AsyncSession,
) -> GitDeployment:
    result = await db.execute(
        select(GitDeployment).where(GitDeployment.domain_id == domain_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Git deployment not configured for this domain.",
        )
    return deployment


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _build_response(deployment: GitDeployment, request: Request) -> GitDeployResponse:
    """Build a GitDeployResponse, injecting the webhook URL."""
    resp = GitDeployResponse.model_validate(deployment)
    base_url = str(request.base_url).rstrip("/")
    resp.webhook_url = f"{base_url}/api/v1/domains/{deployment.domain_id}/git/webhook"
    return resp


# --------------------------------------------------------------------------
# POST /domains/{id}/git/setup -- setup git deployment
# --------------------------------------------------------------------------
@router.post(
    "/domains/{domain_id}/git/setup",
    response_model=GitDeployResponse,
    status_code=status.HTTP_201_CREATED,
)
async def setup_git_deploy(
    domain_id: uuid.UUID,
    body: GitDeployCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set up Git push-to-deploy for a domain. Generates an SSH deploy key pair."""
    domain = await _get_domain_or_403(domain_id, db, current_user)

    # Check if already configured
    existing = await db.execute(
        select(GitDeployment).where(GitDeployment.domain_id == domain_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Git deployment already configured for this domain. Remove it first to reconfigure.",
        )

    # Generate SSH deploy keypair
    public_key, private_key = await git_deploy_service.generate_deploy_keypair()

    # Encrypt private key for storage
    encrypted_private = encrypt_value(private_key, settings.SECRET_KEY)

    # Generate webhook secret
    webhook_secret = git_deploy_service.generate_webhook_secret()

    deployment = GitDeployment(
        domain_id=domain_id,
        repo_url=body.repo_url,
        branch=body.branch,
        deploy_key_public=public_key,
        deploy_key_private=encrypted_private,
        auto_deploy=body.auto_deploy,
        build_command=body.build_command,
        post_deploy_hook=body.post_deploy_hook,
        webhook_secret=webhook_secret,
    )
    db.add(deployment)
    await db.flush()

    _log(db, request, current_user.id, "git_deploy.setup", f"Git deploy configured for {domain.domain_name}")

    return _build_response(deployment, request)


# --------------------------------------------------------------------------
# GET /domains/{id}/git/status -- get current deployment status
# --------------------------------------------------------------------------
@router.get(
    "/domains/{domain_id}/git/status",
    response_model=GitDeployResponse,
)
async def get_git_status(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current git deployment configuration and status."""
    await _get_domain_or_403(domain_id, db, current_user)
    deployment = await _get_deployment_or_404(domain_id, db)
    return _build_response(deployment, request)


# --------------------------------------------------------------------------
# PUT /domains/{id}/git/update -- update deployment config
# --------------------------------------------------------------------------
@router.put(
    "/domains/{domain_id}/git/update",
    response_model=GitDeployResponse,
)
async def update_git_deploy(
    domain_id: uuid.UUID,
    body: GitDeployUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update git deployment settings (repo URL, branch, build command, etc.)."""
    domain = await _get_domain_or_403(domain_id, db, current_user)
    deployment = await _get_deployment_or_404(domain_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(deployment, field, value)

    db.add(deployment)
    await db.flush()

    _log(db, request, current_user.id, "git_deploy.update", f"Git deploy settings updated for {domain.domain_name}")

    return _build_response(deployment, request)


# --------------------------------------------------------------------------
# POST /domains/{id}/git/deploy -- trigger manual deploy
# --------------------------------------------------------------------------
@router.post(
    "/domains/{domain_id}/git/deploy",
    status_code=status.HTTP_200_OK,
)
async def trigger_deploy(
    domain_id: uuid.UUID,
    request: Request,
    body: DeployTriggerRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger a manual git deployment (clone/pull + build)."""
    domain = await _get_domain_or_403(domain_id, db, current_user)
    deployment = await _get_deployment_or_404(domain_id, db)

    # Decrypt private key
    try:
        private_key = decrypt_value(deployment.deploy_key_private, settings.SECRET_KEY)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt deploy key. Try removing and re-setting up git deploy.",
        )

    # Mark as deploying
    deployment.last_deploy_status = "deploying"
    db.add(deployment)
    await db.flush()

    # Determine build command (body override or saved config)
    build_cmd = (body.build_command if body and body.build_command else deployment.build_command)

    # Execute deploy
    result = await git_deploy_service.execute_deploy(
        repo_url=deployment.repo_url,
        branch=deployment.branch,
        document_root=domain.document_root,
        private_key_pem=private_key,
        build_command=build_cmd,
        post_deploy_hook=deployment.post_deploy_hook,
    )

    # Update deployment record
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deploy_status = "success" if result["success"] else "failed"
    deployment.last_deploy_at = now
    deployment.last_deploy_status = deploy_status
    deployment.last_commit_hash = result.get("commit_hash")
    db.add(deployment)

    # Create deploy log entry
    log_entry = DeployLog(
        deployment_id=deployment.id,
        commit_hash=result.get("commit_hash"),
        status=deploy_status,
        trigger="manual",
        output=result.get("output", ""),
        duration_seconds=result.get("duration_seconds"),
    )
    db.add(log_entry)
    await db.flush()

    _log(db, request, current_user.id, "git_deploy.deploy", f"Manual deploy for {domain.domain_name}: {deploy_status}")

    return {
        "success": result["success"],
        "status": deploy_status,
        "commit_hash": result.get("commit_hash"),
        "duration_seconds": result.get("duration_seconds"),
        "output": result.get("output", ""),
    }


# --------------------------------------------------------------------------
# POST /domains/{id}/git/webhook -- webhook endpoint
# --------------------------------------------------------------------------
@router.post(
    "/domains/{domain_id}/git/webhook",
    status_code=status.HTTP_200_OK,
)
async def webhook_handler(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive push webhooks from GitHub, GitLab, or Bitbucket and trigger deploy."""
    # Load deployment config (no auth required -- verified via webhook secret)
    result = await db.execute(
        select(GitDeployment).where(GitDeployment.domain_id == domain_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Git deployment not configured.")

    if not deployment.auto_deploy:
        return {"ok": True, "message": "Auto-deploy is disabled, ignoring webhook."}

    # Read raw body for signature verification
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # Detect provider
    provider = git_deploy_service.detect_webhook_provider(headers)

    # Verify webhook signature/token
    secret = deployment.webhook_secret or ""
    verified = False
    if provider == "github":
        sig = headers.get("x-hub-signature-256", "")
        verified = git_deploy_service.verify_github_signature(raw_body, sig, secret)
    elif provider == "gitlab":
        token = headers.get("x-gitlab-token", "")
        verified = git_deploy_service.verify_gitlab_token(token, secret)
    elif provider == "bitbucket":
        sig = headers.get("x-hub-signature", "")
        verified = git_deploy_service.verify_bitbucket_signature(raw_body, sig, secret)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown webhook provider.")

    if not verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature.")

    # Parse body to check branch
    try:
        body = await request.json()
    except Exception:
        body = {}

    pushed_branch = git_deploy_service.extract_branch_from_webhook(body, provider)
    if pushed_branch and pushed_branch != deployment.branch:
        return {"ok": True, "message": f"Push to '{pushed_branch}' ignored (tracking '{deployment.branch}')."}

    # Load domain for document_root
    domain_result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = domain_result.scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")

    # Decrypt private key
    try:
        private_key = decrypt_value(deployment.deploy_key_private, settings.SECRET_KEY)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Deploy key decryption failed.",
        )

    # Mark as deploying
    deployment.last_deploy_status = "deploying"
    db.add(deployment)
    await db.flush()

    # Execute deploy
    deploy_result = await git_deploy_service.execute_deploy(
        repo_url=deployment.repo_url,
        branch=deployment.branch,
        document_root=domain.document_root,
        private_key_pem=private_key,
        build_command=deployment.build_command,
        post_deploy_hook=deployment.post_deploy_hook,
    )

    # Update deployment record
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deploy_status = "success" if deploy_result["success"] else "failed"
    deployment.last_deploy_at = now
    deployment.last_deploy_status = deploy_status
    deployment.last_commit_hash = deploy_result.get("commit_hash")
    db.add(deployment)

    # Create deploy log entry
    log_entry = DeployLog(
        deployment_id=deployment.id,
        commit_hash=deploy_result.get("commit_hash"),
        status=deploy_status,
        trigger=f"webhook:{provider}",
        output=deploy_result.get("output", ""),
        duration_seconds=deploy_result.get("duration_seconds"),
    )
    db.add(log_entry)
    await db.flush()

    return {
        "ok": True,
        "status": deploy_status,
        "commit_hash": deploy_result.get("commit_hash"),
    }


# --------------------------------------------------------------------------
# DELETE /domains/{id}/git/remove -- remove git deployment config
# --------------------------------------------------------------------------
@router.delete(
    "/domains/{domain_id}/git/remove",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_git_deploy(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove git deployment configuration for a domain."""
    domain = await _get_domain_or_403(domain_id, db, current_user)
    deployment = await _get_deployment_or_404(domain_id, db)

    _log(db, request, current_user.id, "git_deploy.remove", f"Git deploy removed for {domain.domain_name}")

    # Delete all deploy logs first, then the deployment
    await db.execute(
        DeployLog.__table__.delete().where(DeployLog.deployment_id == deployment.id)
    )
    await db.delete(deployment)
    await db.flush()


# --------------------------------------------------------------------------
# GET /domains/{id}/git/logs -- deployment history
# --------------------------------------------------------------------------
@router.get(
    "/domains/{domain_id}/git/logs",
    status_code=status.HTTP_200_OK,
)
async def get_deploy_logs(
    domain_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get deployment history for a domain."""
    await _get_domain_or_403(domain_id, db, current_user)
    deployment = await _get_deployment_or_404(domain_id, db)

    result = await db.execute(
        select(DeployLog)
        .where(DeployLog.deployment_id == deployment.id)
        .order_by(DeployLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    logs = result.scalars().all()

    return {
        "items": [DeployLogEntry.model_validate(log) for log in logs],
    }
