"""SSL certificate schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SslCertificateResponse(BaseModel):
    id: uuid.UUID
    domain_id: uuid.UUID
    cert_path: str
    key_path: str
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    auto_renew: bool

    model_config = {"from_attributes": True}


class CustomCertInstall(BaseModel):
    domain_id: uuid.UUID
    certificate: str = Field(..., min_length=1, description="PEM-encoded certificate.")
    private_key: str = Field(..., min_length=1, description="PEM-encoded private key.")
    chain: Optional[str] = Field(default=None, description="PEM-encoded CA chain.")
