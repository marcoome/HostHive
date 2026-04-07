"""WebAuthn / FIDO2 (Passkeys) router -- /api/v1/auth/webauthn."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from api.core.config import settings
from api.core.database import get_db
from api.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
)
from api.models.users import User
from api.models.webauthn import WebAuthnCredential
from api.schemas.webauthn import (
    AuthenticationOptionsRequest,
    AuthenticationOptionsResponse,
    AuthenticationVerifyRequest,
    AuthenticationVerifyResponse,
    CredentialListResponse,
    CredentialResponse,
    RegistrationOptionsRequest,
    RegistrationOptionsResponse,
    RegistrationVerifyRequest,
    RegistrationVerifyResponse,
)

router = APIRouter()

_CHALLENGE_PREFIX = "webauthn:challenge:"
_CHALLENGE_TTL = 300  # 5 minutes


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _store_challenge(redis, key: str, challenge: bytes, extra: dict | None = None) -> None:
    """Store a WebAuthn challenge in Redis with a 5-minute TTL."""
    data = {"challenge": bytes_to_base64url(challenge)}
    if extra:
        data.update(extra)
    await redis.set(
        f"{_CHALLENGE_PREFIX}{key}",
        json.dumps(data),
        ex=_CHALLENGE_TTL,
    )


async def _pop_challenge(redis, key: str) -> dict:
    """Retrieve and delete a stored challenge. Raises 400 if expired/missing."""
    raw = await redis.get(f"{_CHALLENGE_PREFIX}{key}")
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Challenge expired or not found. Please restart the process.",
        )
    await redis.delete(f"{_CHALLENGE_PREFIX}{key}")
    return json.loads(raw)


def _options_to_dict(options) -> dict:
    """Serialise a py_webauthn options object to a JSON-safe dict."""
    return json.loads(options.model_dump_json())


# ---------------------------------------------------------------------------
# POST /register/options
# ---------------------------------------------------------------------------
@router.post("/register/options", response_model=RegistrationOptionsResponse)
async def registration_options(
    request: Request,
    body: Optional[RegistrationOptionsRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate PublicKeyCredentialCreationOptions for a logged-in user."""
    # Fetch existing credentials to exclude
    result = await db.execute(
        select(WebAuthnCredential)
        .where(
            WebAuthnCredential.user_id == current_user.id,
            WebAuthnCredential.is_active.is_(True),
        )
    )
    existing = result.scalars().all()
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=c.credential_id)
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(current_user.id).encode(),
        user_name=current_user.username,
        user_display_name=current_user.username,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    # Store challenge in Redis keyed by user ID
    challenge_key = f"reg:{current_user.id}"
    device_name = body.device_name if body else None
    await _store_challenge(
        request.app.state.redis,
        challenge_key,
        options.challenge,
        extra={"device_name": device_name},
    )

    return RegistrationOptionsResponse(options=_options_to_dict(options))


# ---------------------------------------------------------------------------
# POST /register/verify
# ---------------------------------------------------------------------------
@router.post("/register/verify", response_model=RegistrationVerifyResponse)
async def registration_verify(
    body: RegistrationVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify the attestation response and store the new credential."""
    redis = request.app.state.redis
    challenge_key = f"reg:{current_user.id}"
    stored = await _pop_challenge(redis, challenge_key)
    expected_challenge = base64url_to_bytes(stored["challenge"])
    device_name = body.device_name or stored.get("device_name")

    try:
        verification = verify_registration_response(
            credential=body.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration verification failed: {exc}",
        )

    # Check for duplicate credential
    exists = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == verification.credential_id,
        )
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This credential is already registered.",
        )

    credential = WebAuthnCredential(
        user_id=current_user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        device_name=device_name,
    )
    db.add(credential)
    await db.flush()

    return RegistrationVerifyResponse(
        id=credential.id,
        credential_id=bytes_to_base64url(credential.credential_id),
        device_name=credential.device_name,
        created_at=credential.created_at,
    )


# ---------------------------------------------------------------------------
# POST /login/options
# ---------------------------------------------------------------------------
@router.post("/login/options", response_model=AuthenticationOptionsResponse)
async def authentication_options(
    body: AuthenticationOptionsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate PublicKeyCredentialRequestOptions (no auth required)."""
    allow_credentials: list[PublicKeyCredentialDescriptor] = []
    user_id_hint: str | None = None

    if body.username:
        result = await db.execute(
            select(User).where(User.username == body.username)
        )
        user = result.scalar_one_or_none()
        if user is not None:
            user_id_hint = str(user.id)
            cred_result = await db.execute(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.user_id == user.id,
                    WebAuthnCredential.is_active.is_(True),
                )
            )
            creds = cred_result.scalars().all()
            allow_credentials = [
                PublicKeyCredentialDescriptor(id=c.credential_id)
                for c in creds
            ]

    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials if allow_credentials else None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    # Store challenge keyed by a temporary session token
    session_token = uuid.uuid4().hex
    await _store_challenge(
        request.app.state.redis,
        f"auth:{session_token}",
        options.challenge,
        extra={"user_id_hint": user_id_hint},
    )

    opts_dict = _options_to_dict(options)
    # Include session_token so the client can send it back during verify
    opts_dict["session_token"] = session_token
    return AuthenticationOptionsResponse(options=opts_dict)


# ---------------------------------------------------------------------------
# POST /login/verify
# ---------------------------------------------------------------------------
@router.post("/login/verify", response_model=AuthenticationVerifyResponse)
async def authentication_verify(
    body: AuthenticationVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify the assertion response and return a JWT."""
    redis = request.app.state.redis

    # The session_token should be passed back in the credential envelope
    session_token = body.credential.get("session_token")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing session_token in credential payload.",
        )

    stored = await _pop_challenge(redis, f"auth:{session_token}")
    expected_challenge = base64url_to_bytes(stored["challenge"])

    # Look up the credential by the raw ID sent by the authenticator
    raw_id_b64 = body.credential.get("rawId") or body.credential.get("id", "")
    try:
        credential_id_bytes = base64url_to_bytes(raw_id_b64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid credential ID encoding.",
        )

    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == credential_id_bytes,
            WebAuthnCredential.is_active.is_(True),
        )
    )
    db_credential = result.scalar_one_or_none()
    if db_credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credential not found or disabled.",
        )

    # Load the owning user
    user_result = await db.execute(
        select(User).where(User.id == db_credential.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or suspended.",
        )

    try:
        verification = verify_authentication_response(
            credential=body.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=db_credential.public_key,
            credential_current_sign_count=db_credential.sign_count,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication verification failed: {exc}",
        )

    # Update sign count and last_used_at
    db_credential.sign_count = verification.new_sign_count
    db_credential.last_used_at = _utcnow()
    db.add(db_credential)

    # Issue JWT tokens
    access_token = create_access_token(
        user.id, user.role.value, user.password_changed_at,
    )
    refresh_token = create_refresh_token(user.id)

    # Store refresh token in Redis (same pattern as auth.py)
    refresh_key = f"hosthive:refresh:{user.id}:{refresh_token[-16:]}"
    await redis.set(
        refresh_key,
        "1",
        ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return AuthenticationVerifyResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# GET /credentials
# ---------------------------------------------------------------------------
@router.get("/credentials", response_model=CredentialListResponse)
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all WebAuthn credentials for the current user."""
    result = await db.execute(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == current_user.id)
        .order_by(WebAuthnCredential.created_at.desc())
    )
    creds = result.scalars().all()
    return CredentialListResponse(
        credentials=[
            CredentialResponse(
                id=c.id,
                credential_id=bytes_to_base64url(c.credential_id),
                device_name=c.device_name,
                sign_count=c.sign_count,
                created_at=c.created_at,
                last_used_at=c.last_used_at,
                is_active=c.is_active,
            )
            for c in creds
        ]
    )


# ---------------------------------------------------------------------------
# DELETE /credentials/{credential_id}
# ---------------------------------------------------------------------------
@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a WebAuthn credential belonging to the current user."""
    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.id == credential_id,
            WebAuthnCredential.user_id == current_user.id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found.",
        )
    await db.delete(credential)
