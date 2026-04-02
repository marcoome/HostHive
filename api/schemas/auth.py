"""Authentication schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.schemas.users import UserResponse


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class LoginResponse(TokenResponse):
    """Token response enriched with the authenticated user profile."""
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
