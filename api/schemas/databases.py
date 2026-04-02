"""Database schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from api.models.databases import DbType


class DatabaseCreate(BaseModel):
    db_name: str = Field(default=None, min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_]+$")
    db_user: str = Field(default=None, min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_]+$")
    db_password: str = Field(default=None, min_length=8, max_length=128)
    db_type: DbType = DbType.MYSQL

    # Frontend alias fields (accepted but mapped to canonical names)
    name: Optional[str] = Field(default=None, exclude=True)
    username: Optional[str] = Field(default=None, exclude=True)
    password: Optional[str] = Field(default=None, exclude=True)
    type: Optional[str] = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def map_frontend_fields(cls, values):
        """Accept frontend field names and map them to backend field names."""
        if isinstance(values, dict):
            # Map 'name' -> 'db_name'
            if "name" in values and "db_name" not in values:
                values["db_name"] = values["name"]
            # Map 'username' -> 'db_user'
            if "username" in values and "db_user" not in values:
                values["db_user"] = values["username"]
            # Map 'password' -> 'db_password'
            if "password" in values and "db_password" not in values:
                values["db_password"] = values["password"]
            # Map 'type' -> 'db_type'
            if "type" in values and "db_type" not in values:
                values["db_type"] = values["type"]
        return values


class DatabaseResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    db_name: str
    db_user: str
    db_type: DbType
    created_at: datetime

    # Frontend-friendly aliases included in JSON output
    name: Optional[str] = None
    username: Optional[str] = None
    type: Optional[str] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def populate_frontend_fields(self):
        """Provide frontend-friendly field names in the response."""
        self.name = self.db_name
        self.username = self.db_user
        self.type = self.db_type.value if self.db_type else None
        return self
