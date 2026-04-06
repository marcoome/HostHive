"""Two-Factor Authentication (TOTP) schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# -- Setup ------------------------------------------------------------------

class TOTPSetupResponse(BaseModel):
    """Returned when a user initiates 2FA setup."""
    secret: str = Field(description="Base32-encoded TOTP secret (display to user).")
    otpauth_uri: str = Field(description="otpauth:// URI for QR code generation.")
    qr_code_base64: str = Field(description="Base64-encoded PNG of the QR code.")
    backup_codes: List[str] = Field(description="One-time backup codes (plain text, shown once).")


# -- Verify / Confirm Setup ------------------------------------------------

class TOTPVerifyRequest(BaseModel):
    """Verify a TOTP code to confirm 2FA setup or to complete login."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TOTPVerifyResponse(BaseModel):
    verified: bool


# -- Disable ----------------------------------------------------------------

class TOTPDisableRequest(BaseModel):
    """Disable 2FA (requires a valid TOTP code)."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


# -- Backup code verify ----------------------------------------------------

class TOTPBackupVerifyRequest(BaseModel):
    """Verify using a one-time backup code."""
    backup_code: str = Field(..., min_length=8, max_length=8)


# -- 2FA Login step ---------------------------------------------------------

class TOTP2FALoginRequest(BaseModel):
    """Complete login by providing the 2FA pending token and a TOTP code."""
    pending_token: str = Field(..., description="The 2fa_pending token from the login response.")
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TOTP2FABackupLoginRequest(BaseModel):
    """Complete login using a backup code instead of TOTP."""
    pending_token: str = Field(..., description="The 2fa_pending token from the login response.")
    backup_code: str = Field(..., min_length=8, max_length=8)


# -- 2FA Status -------------------------------------------------------------

class TOTPStatusResponse(BaseModel):
    enabled: bool
    method: Optional[str] = None
