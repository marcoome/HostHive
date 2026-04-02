"""File manager schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class FileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int = 0
    modified: Optional[str] = None
    permissions: Optional[str] = None
    owner: Optional[str] = None


class FileListResponse(BaseModel):
    path: str
    items: List[FileItem]
    total: int


class FileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    content: str
    encoding: str = Field(default="utf-8")
