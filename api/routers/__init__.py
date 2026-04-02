"""API router registry -- imports all routers for easy inclusion in main."""

from api.routers.ai import router as ai_router
from api.routers.auth import router as auth_router
from api.routers.users import router as users_router
from api.routers.domains import router as domains_router
from api.routers.databases import router as databases_router
from api.routers.email import router as email_router
from api.routers.dns import router as dns_router
from api.routers.ftp import router as ftp_router
from api.routers.cron import router as cron_router
from api.routers.ssl import router as ssl_router
from api.routers.backups import router as backups_router
from api.routers.packages import router as packages_router
from api.routers.server import router as server_router
from api.routers.files import router as files_router
from api.routers.branding import router as branding_router
from api.routers.integrations import router as integrations_router
from api.routers.audit import router as audit_router
from api.routers.api_keys import router as api_keys_router
from api.routers.status import router as status_router
from api.routers.billing import router as billing_router
from api.routers.metrics import router as metrics_router
from api.routers.admin import router as admin_router
from api.routers.monitoring import router as monitoring_router
from api.routers.reseller import router as reseller_router
from api.routers.wireguard import router as wireguard_router
from api.routers.docker import router as docker_router
from api.routers.wordpress import router as wordpress_router
from api.routers.environments import router as environments_router
from api.routers.analytics import router as analytics_router
from api.routers.waf import router as waf_router
from api.routers.resources import router as resources_router
from api.routers.apps import router as apps_router
from api.routers.email_auth import router as email_auth_router

__all__ = [
    "ai_router",
    "auth_router",
    "users_router",
    "domains_router",
    "databases_router",
    "email_router",
    "dns_router",
    "ftp_router",
    "cron_router",
    "ssl_router",
    "backups_router",
    "packages_router",
    "server_router",
    "files_router",
    "branding_router",
    "integrations_router",
    "audit_router",
    "api_keys_router",
    "status_router",
    "billing_router",
    "metrics_router",
    "monitoring_router",
    "reseller_router",
    "admin_router",
    "wireguard_router",
    "docker_router",
    "wordpress_router",
    "environments_router",
    "analytics_router",
    "waf_router",
    "resources_router",
    "apps_router",
    "email_auth_router",
]
