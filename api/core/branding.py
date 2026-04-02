"""
Centralized branding configuration for HostHive.

Change the product name, tagline, colors, and all branding
in ONE place: /opt/hosthive/config/branding.json

This module loads branding and exposes it to the entire backend.
The frontend reads the same file via the /api/v1/branding endpoint.
"""

import json
from pathlib import Path
from functools import lru_cache
from pydantic import BaseModel


class ThemeConfig(BaseModel):
    primary: str = "#6366f1"
    background: str = "#0a0a0f"
    surface: str = "#111118"
    border: str = "#1e1e2e"
    text_primary: str = "#e2e8f0"
    text_muted: str = "#64748b"
    success: str = "#22c55e"
    warning: str = "#f59e0b"
    error: str = "#ef4444"


class FontsConfig(BaseModel):
    ui: str = "Inter"
    code: str = "JetBrains Mono"


class BrandingConfig(BaseModel):
    product_name: str = "HostHive"
    product_slug: str = "hosthive"
    product_tagline: str = "Modern Hosting Control Panel"
    product_version: str = "1.0.0"
    product_url: str = "https://hosthive.io"
    support_email: str = "support@hosthive.io"
    logo_text: str = "HostHive"
    logo_icon: str = "hexagon-bee"
    copyright: str = "HostHive"
    theme: ThemeConfig = ThemeConfig()
    fonts: FontsConfig = FontsConfig()


# Search paths for branding.json (production first, then dev)
_BRANDING_PATHS = [
    Path("/opt/hosthive/config/branding.json"),
    Path(__file__).resolve().parent.parent.parent / "config" / "branding.json",
]


@lru_cache(maxsize=1)
def get_branding() -> BrandingConfig:
    """Load branding config from branding.json. Cached after first load."""
    for path in _BRANDING_PATHS:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return BrandingConfig(**data)
    return BrandingConfig()


def reload_branding() -> BrandingConfig:
    """Force reload branding config (e.g. after admin changes it)."""
    get_branding.cache_clear()
    return get_branding()


# Convenience shortcuts
branding = get_branding()
PRODUCT_NAME = branding.product_name
PRODUCT_VERSION = branding.product_version
