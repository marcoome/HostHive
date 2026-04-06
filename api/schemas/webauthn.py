"""Pydantic schemas for WebAuthn / Passkey endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class RegistrationOptionsRequest(BaseModel):
    """Client sends this to start passkey registration."""
    device_name: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Friendly name for the credential (e.g. 'MacBook TouchID').",
    )


class RegistrationOptionsResponse(BaseModel):
    """Server returns PublicKeyCredentialCreationOptions as JSON."""
    options: dict = Field(
        description="Serialised PublicKeyCredentialCreationOptions for navigator.credentials.create().",
    )


class RegistrationVerifyRequest(BaseModel):
    """Client sends the attestation response from navigator.credentials.create()."""
    credential: dict = Field(
        description="The full PublicKeyCredential JSON from the browser.",
    )
    device_name: Optional[str] = Field(
        default=None,
        max_length=128,
    )


class RegistrationVerifyResponse(BaseModel):
    id: uuid.UUID
    credential_id: str = Field(description="Base64url-encoded credential ID.")
    device_name: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class AuthenticationOptionsRequest(BaseModel):
    """Client may optionally provide a username to narrow the allowed credentials."""
    username: Optional[str] = Field(default=None, max_length=64)


class AuthenticationOptionsResponse(BaseModel):
    """Server returns PublicKeyCredentialRequestOptions as JSON."""
    options: dict = Field(
        description="Serialised PublicKeyCredentialRequestOptions for navigator.credentials.get().",
    )


class AuthenticationVerifyRequest(BaseModel):
    """Client sends the assertion response from navigator.credentials.get()."""
    credential: dict = Field(
        description="The full PublicKeyCredential JSON from the browser.",
    )


class AuthenticationVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------

class CredentialResponse(BaseModel):
    id: uuid.UUID
    credential_id: str
    device_name: Optional[str]
    sign_count: int
    created_at: datetime
    last_used_at: Optional[datetime]
    is_active: bool

    model_config = {"from_attributes": True}


class CredentialListResponse(BaseModel):
    credentials: list[CredentialResponse]
