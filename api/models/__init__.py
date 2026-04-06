"""Export all ORM models so Alembic and the app can discover them."""

from api.models.activity_log import ActivityLog
from api.models.ai import (
    AiConversation,
    AiInsight,
    AiInsightSeverity,
    AiMessage,
    AiMessageRole,
    AiSettings,
    AiTokenUsage,
)
from api.models.backups import Backup, BackupType
from api.models.base import TimestampedBase
from api.models.cron_jobs import CronJob
from api.models.databases import Database, DatabaseUser, DbType
from api.models.dns_records import DnsRecord
from api.models.dns_zones import DnsZone
from api.models.domains import Domain
from api.models.email_accounts import EmailAccount
from api.models.email_aliases import EmailAlias
from api.models.mailing_list import MailingList, MailingListMember
from api.models.ftp_accounts import FtpAccount
from api.models.directory_privacy import DirectoryPrivacy
from api.models.git_deploy import DeployLog, GitDeployment
from api.models.packages import Package
from api.models.redirects import Redirect
from api.models.server_stats import ServerStat
from api.models.ssl_certificates import SSLCertificate as SslCertificate
from api.models.users import BackupFrequency, User, UserRole
from api.models.monitoring import (
    AnomalyAlert,
    AnomalySeverity,
    DomainBandwidth,
    HealthCheck,
    HealthStatus,
    MonitoringIncident,
)
from api.models.reseller import ResellerBranding, ResellerLimit
from api.models.docker import DockerContainer
from api.models.user_environment import UserEnvironment
from api.models.apps import App
from api.models.runtime_app import RuntimeApp
from api.models.notifications import Notification, NotificationLevel
from api.models.resources import ResourceLimit
from api.models.webauthn import WebAuthnCredential
from api.models.antivirus import QuarantineEntry, ScanResult, ScanStatus
from api.models.cluster import ClusterAssignment, ClusterNode
from api.models.dns_cluster import DnsClusterNode
from api.models.integrations import (
    ApiKey,
    ApiKeyScope,
    IncidentSeverity,
    IncidentStatus,
    Integration,
    IntegrationName,
    StatusIncident,
    WebhookDirection,
    WebhookLog,
)

__all__ = [
    "ActivityLog",
    "QuarantineEntry",
    "ScanResult",
    "ScanStatus",
    "AiConversation",
    "App",
    "AiInsight",
    "AiInsightSeverity",
    "AiMessage",
    "AiMessageRole",
    "AiSettings",
    "AiTokenUsage",
    "AnomalyAlert",
    "AnomalySeverity",
    "ApiKey",
    "ApiKeyScope",
    "Backup",
    "BackupFrequency",
    "BackupType",
    "ClusterAssignment",
    "ClusterNode",
    "CronJob",
    "Database",
    "DatabaseUser",
    "DbType",
    "DirectoryPrivacy",
    "DockerContainer",
    "DnsClusterNode",
    "DnsRecord",
    "DnsZone",
    "Domain",
    "DomainBandwidth",
    "EmailAccount",
    "EmailAlias",
    "FtpAccount",
    "GitDeployment",
    "DeployLog",
    "HealthCheck",
    "HealthStatus",
    "IncidentSeverity",
    "IncidentStatus",
    "Integration",
    "IntegrationName",
    "MonitoringIncident",
    "Notification",
    "NotificationLevel",
    "Package",
    "Redirect",
    "ResellerBranding",
    "ResellerLimit",
    "ResourceLimit",
    "RuntimeApp",
    "ServerStat",
    "SslCertificate",
    "StatusIncident",
    "TimestampedBase",
    "User",
    "UserRole",
    "UserEnvironment",
    "WebAuthnCredential",
    "WebhookDirection",
    "WebhookLog",
]
