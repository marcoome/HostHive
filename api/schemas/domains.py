"""Domain schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class WebserverType(str, Enum):
    nginx = "nginx"
    apache = "apache"
    nginx_apache = "nginx_apache"


class NginxTemplate(str, Enum):
    default = "default"
    wordpress = "wordpress"
    proxy = "proxy"
    static = "static"


class CacheType(str, Enum):
    fastcgi = "fastcgi"
    proxy = "proxy"
    none = "none"


class DomainCreate(BaseModel):
    domain_name: str = Field(default=None, min_length=3, max_length=255)
    document_root: Optional[str] = None
    php_version: str = Field(default="8.2", pattern=r"^\d+\.\d+$")
    webserver: WebserverType = WebserverType.nginx
    nginx_template: NginxTemplate = NginxTemplate.default
    custom_nginx_config: Optional[str] = Field(default=None, max_length=10000)
    cache_enabled: bool = False
    cache_type: CacheType = CacheType.fastcgi
    cache_ttl: int = Field(default=3600, ge=0, le=86400)
    cache_bypass_cookie: str = Field(default="wordpress_logged_in", max_length=255)

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
    webserver: Optional[WebserverType] = None
    ssl_enabled: Optional[bool] = None
    nginx_template: Optional[NginxTemplate] = None
    custom_nginx_config: Optional[str] = Field(default=None, max_length=10000)
    is_active: Optional[bool] = None
    cache_enabled: Optional[bool] = None
    cache_type: Optional[CacheType] = None
    cache_ttl: Optional[int] = Field(default=None, ge=0, le=86400)
    cache_bypass_cookie: Optional[str] = Field(default=None, max_length=255)


class CacheUpdate(BaseModel):
    cache_enabled: Optional[bool] = None
    cache_type: Optional[CacheType] = None
    cache_ttl: Optional[int] = Field(default=None, ge=0, le=86400)
    cache_bypass_cookie: Optional[str] = Field(default=None, max_length=255)


class HotlinkUpdate(BaseModel):
    hotlink_protection: Optional[bool] = None
    hotlink_allowed_domains: Optional[str] = Field(default=None, max_length=5000)
    hotlink_extensions: Optional[str] = Field(default=None, max_length=512)
    hotlink_redirect_url: Optional[str] = Field(default=None, max_length=512)


class ErrorPagesUpdate(BaseModel):
    """Mapping of HTTP status code to page path or inline HTML content."""
    error_pages: dict[int, str] = Field(
        ...,
        description="Mapping of HTTP status codes to custom page paths or HTML content. "
                    "Example: {404: '/custom_404.html', 500: '/custom_500.html'}",
    )

    @model_validator(mode="after")
    def validate_error_codes(self):
        allowed_codes = {400, 401, 403, 404, 405, 408, 410, 413, 429, 500, 501, 502, 503, 504}
        for code in self.error_pages:
            if code not in allowed_codes:
                raise ValueError(
                    f"Unsupported error code {code}. "
                    f"Allowed codes: {sorted(allowed_codes)}"
                )
        return self


# ---------------------------------------------------------------------------
# Subdomain schemas
# ---------------------------------------------------------------------------

class SubdomainCreate(BaseModel):
    """Create a subdomain under an existing domain."""
    subdomain_prefix: str = Field(
        ..., min_length=1, max_length=63,
        pattern=r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$",
        description="Subdomain prefix (e.g. 'blog' for blog.example.com)",
    )
    document_root: Optional[str] = Field(
        default=None,
        description="Custom document root. Auto-generated if omitted.",
    )
    php_version: str = Field(default="8.2", pattern=r"^\d+\.\d+$")
    enable_ssl: bool = Field(
        default=False,
        description="Automatically issue SSL via Let's Encrypt after creation.",
    )


class SubdomainUpdate(BaseModel):
    """Update subdomain settings."""
    document_root: Optional[str] = None
    php_version: Optional[str] = Field(default=None, pattern=r"^\d+\.\d+$")


class SubdomainResponse(BaseModel):
    id: uuid.UUID
    domain_name: str
    document_root: str
    php_version: str
    ssl_enabled: bool
    is_subdomain: bool = True
    parent_domain_id: Optional[uuid.UUID] = None
    webserver: str = "nginx"
    is_active: bool = True
    created_at: datetime

    # Frontend-friendly alias
    name: Optional[str] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def populate_frontend_fields(self):
        self.name = self.domain_name
        return self


# ---------------------------------------------------------------------------
# Domain response
# ---------------------------------------------------------------------------

class DomainResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    domain_name: str
    document_root: str
    php_version: str
    webserver: str = "nginx"
    ssl_enabled: bool
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    nginx_template: Optional[str] = "default"
    custom_nginx_config: Optional[str] = None
    is_active: bool
    cache_enabled: bool = False
    cache_type: str = "fastcgi"
    cache_ttl: int = 3600
    cache_bypass_cookie: str = "wordpress_logged_in"
    hotlink_protection: bool = False
    hotlink_allowed_domains: Optional[str] = None
    hotlink_extensions: str = "jpg,jpeg,png,gif,webp,svg,mp4,mp3"
    hotlink_redirect_url: Optional[str] = None
    custom_error_pages: Optional[dict] = None
    parent_domain_id: Optional[uuid.UUID] = None
    is_subdomain: bool = False
    created_at: datetime

    # Frontend-friendly alias
    name: Optional[str] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def populate_frontend_fields(self):
        """Provide 'name' as alias for 'domain_name' in the response."""
        self.name = self.domain_name
        return self
