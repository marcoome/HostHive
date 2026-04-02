"""Domain schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class DomainCreate(BaseModel):
    domain_name: str = Field(default=None, min_length=3, max_length=255)
    document_root: Optional[str] = None
    php_version: str = Field(default="8.2", pattern=r"^\d+\.\d+$")

    # Frontend alias field
    name: Optional[str] = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def map_frontend_fields(cls, values):
        """Accept 'name' from frontend and map to 'domain_name'."""
        if isinstance(values, dict):
            if "name" in values and "domain_name" not in values:
                values["domain_name"] = values["name"]
        return values


class DomainUpdate(BaseModel):
    document_root: Optional[str] = None
    php_version: Optional[str] = Field(default=None, pattern=r"^\d+\.\d+$")
    ssl_enabled: Optional[bool] = None
    nginx_template: Optional[str] = None
    is_active: Optional[bool] = None


class DomainResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_name: str
    document_root: str
    php_version: str
    ssl_enabled: bool
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    is_active: bool
    created_at: datetime

    # Frontend-friendly alias
    name: Optional[str] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def populate_frontend_fields(self):
        """Provide 'name' as alias for 'domain_name' in the response."""
        self.name = self.domain_name
        return self
