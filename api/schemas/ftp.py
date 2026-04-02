"""FTP account schemas."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class FtpAccountCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    home_dir: str = Field(default="", min_length=0, max_length=512)

    @model_validator(mode="before")
    @classmethod
    def accept_frontend_field_names(cls, data):
        """Accept ``home_directory`` / ``directory`` as aliases for ``home_dir``."""
        if isinstance(data, dict):
            if "home_directory" in data and "home_dir" not in data:
                data["home_dir"] = data.pop("home_directory")
            elif "directory" in data and "home_dir" not in data:
                data["home_dir"] = data.pop("directory")
        return data


class FtpAccountResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    home_dir: str
    home_directory: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _copy_home_dir_to_home_directory(self):
        """Expose ``home_directory`` so the frontend can read it."""
        if not self.home_directory:
            self.home_directory = self.home_dir
        return self
