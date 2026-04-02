"""Pydantic schemas for WordPress management."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class WPCloneRequest(BaseModel):
    target_domain: str = Field(..., min_length=3, max_length=255, description="Target domain for the clone")


class WPSearchReplaceRequest(BaseModel):
    old_domain: str = Field(..., min_length=3, max_length=255, description="Domain to replace")
    new_domain: str = Field(..., min_length=3, max_length=255, description="New domain")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class WPPluginInfo(BaseModel):
    name: str
    status: str = "unknown"
    version: str = "unknown"
    update_version: Optional[str] = None


class WPThemeInfo(BaseModel):
    name: str
    status: str = "unknown"
    version: Optional[str] = None


class WPInstallInfo(BaseModel):
    path: str
    domain: str
    owner: Optional[str] = None


class WPSiteInfo(BaseModel):
    path: str
    version: str = "unknown"
    plugins: List[Dict[str, Any]] = Field(default_factory=list)
    themes: List[Dict[str, Any]] = Field(default_factory=list)
    active_theme: str = "unknown"
    db_health: str = "unknown"


class WPUpdateResult(BaseModel):
    path: str
    stdout: str = ""
    db_update: Optional[str] = None


class WPCloneResult(BaseModel):
    source_path: str
    target_path: str
    target_domain: str
    source_url: str
    target_url: str


class WPSearchReplaceResult(BaseModel):
    path: str
    results: List[Dict[str, Any]] = Field(default_factory=list)


class WPSecurityIssue(BaseModel):
    severity: str
    type: str
    message: str


class WPSecurityReport(BaseModel):
    path: str
    total_issues: int = 0
    issues: List[WPSecurityIssue] = Field(default_factory=list)


class WPBackupResult(BaseModel):
    path: str
    backup_file: str
    size_bytes: int = 0
