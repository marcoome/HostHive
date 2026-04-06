"""HostHive Celery Beat schedule configuration."""

from __future__ import annotations

from celery.schedules import crontab

# ---------------------------------------------------------------------------
# Beat schedule -- all periodic tasks for the HostHive control panel
# ---------------------------------------------------------------------------
beat_schedule = {
    # ── Server monitoring ──────────────────────────────────────────────
    "collect_server_stats": {
        "task": "api.tasks.server_tasks.collect_server_stats",
        "schedule": 300.0,  # every 5 minutes
        "options": {"queue": "monitoring"},
    },
    "cleanup_old_stats": {
        "task": "api.tasks.server_tasks.cleanup_old_stats",
        "schedule": crontab(
            hour=5, minute=0, day_of_week="sunday",
        ),  # weekly on Sunday at 05:00 UTC
        "options": {"queue": "maintenance"},
    },

    # ── SSL certificates ───────────────────────────────────────────────
    "auto_renew_expiring_certs": {
        "task": "api.tasks.ssl_tasks.auto_renew_expiring_certs",
        "schedule": crontab(hour=3, minute=0),  # daily at 03:00 UTC
        "options": {"queue": "ssl"},
    },
    "check_cert_expiry": {
        "task": "api.tasks.ssl_tasks.check_cert_expiry",
        "schedule": crontab(hour=8, minute=0),  # daily at 08:00 UTC
        "options": {"queue": "ssl"},
    },

    # ── Backups ────────────────────────────────────────────────────────
    "create_scheduled_backups": {
        "task": "api.tasks.backup_tasks.create_scheduled_backups",
        "schedule": crontab(hour=2, minute=0),  # daily at 02:00 UTC
        "options": {"queue": "backups"},
    },
    "cleanup_old_backups": {
        "task": "api.tasks.backup_tasks.cleanup_old_backups",
        "schedule": crontab(hour=4, minute=0),  # daily at 04:00 UTC
        "options": {"queue": "maintenance"},
    },

    # ── Mail ───────────────────────────────────────────────────────────
    "update_spam_rules": {
        "task": "api.tasks.mail_tasks.update_spam_rules",
        "schedule": crontab(
            hour=6, minute=0, day_of_week="sunday",
        ),  # weekly on Sunday at 06:00 UTC
        "options": {"queue": "mail"},
    },

    "update_quota_usage": {
        "task": "api.tasks.mail_tasks.update_quota_usage",
        "schedule": 900.0,  # every 15 minutes
        "options": {"queue": "mail"},
    },
    # ── Antivirus ─────────────────────────────────────────────────────
    "scheduled_antivirus_scan": {
        "task": "api.tasks.server_tasks.scheduled_antivirus_scan",
        "schedule": crontab(hour=1, minute=30),  # nightly at 01:30 UTC
        "options": {"queue": "security"},
    },

    # ── Notifications ──────────────────────────────────────────────────
    "send_expiry_alerts": {
        "task": "api.tasks.notification_tasks.send_expiry_alerts",
        "schedule": crontab(hour=9, minute=0),  # daily at 09:00 UTC
        "options": {"queue": "notifications"},
    },

    # ── Smart monitoring ──────────────────────────────────────────────
    "run_health_checks": {
        "task": "api.tasks.monitoring_tasks.run_health_checks",
        "schedule": 60.0,  # every 60 seconds
        "options": {"queue": "monitoring"},
    },
    "check_anomalies": {
        "task": "api.tasks.monitoring_tasks.check_anomalies",
        "schedule": 300.0,  # every 5 minutes
        "options": {"queue": "monitoring"},
    },
    "update_disk_prediction": {
        "task": "api.tasks.monitoring_tasks.update_disk_prediction",
        "schedule": 3600.0,  # every hour
        "options": {"queue": "monitoring"},
    },
    "aggregate_domain_bandwidth": {
        "task": "api.tasks.monitoring_tasks.aggregate_domain_bandwidth",
        "schedule": 3600.0,  # every hour
        "options": {"queue": "monitoring"},
    },
    "aggregate_reseller_bandwidth": {
        "task": "api.tasks.monitoring_tasks.aggregate_reseller_bandwidth",
        "schedule": 3600.0,  # every hour (runs after domain bandwidth)
        "options": {"queue": "monitoring"},
    },
    "cleanup_old_health_checks": {
        "task": "api.tasks.monitoring_tasks.cleanup_old_health_checks",
        "schedule": crontab(hour=4, minute=30),  # daily at 04:30 UTC
        "options": {"queue": "maintenance"},
    },

    # ── DNS Cluster ────────────────────────────────────────────────────
    "dns_cluster_verify_sync": {
        "task": "api.tasks.dns_cluster_tasks.verify_cluster_sync",
        "schedule": 900.0,  # every 15 minutes
        "options": {"queue": "dns"},
    },

    # ── WAF / GeoIP ─────────────────────────────────────────────────────
    "update_geoip_database": {
        "task": "api.tasks.waf_tasks.update_geoip_database",
        "schedule": crontab(
            hour=3, minute=30, day_of_week="wednesday",
        ),  # weekly on Wednesday at 03:30 UTC
        "options": {"queue": "security"},
    },

    # ── AI ─────────────────────────────────────────────────────────────
    "ai_analyze_logs_periodic": {
        "task": "api.tasks.ai_tasks.analyze_logs_periodic",
        "schedule": 21600.0,  # every 6 hours (default; configurable via AiSettings)
        "options": {"queue": "ai"},
    },
    "ai_security_scan_daily": {
        "task": "api.tasks.ai_tasks.security_scan_daily",
        "schedule": crontab(hour=4, minute=0),  # daily at 04:00 UTC
        "options": {"queue": "ai"},
    },
    "ai_cleanup_conversations": {
        "task": "api.tasks.ai_tasks.cleanup_ai_conversations",
        "schedule": crontab(hour=5, minute=30),  # daily at 05:30 UTC
        "options": {"queue": "maintenance"},
    },
}

# ---------------------------------------------------------------------------
# Task routing
# ---------------------------------------------------------------------------
task_routes = {
    "api.tasks.server_tasks.*": {"queue": "monitoring"},
    "api.tasks.ssl_tasks.*": {"queue": "ssl"},
    "api.tasks.backup_tasks.*": {"queue": "backups"},
    "api.tasks.mail_tasks.*": {"queue": "mail"},
    "api.tasks.notification_tasks.*": {"queue": "notifications"},
    "api.tasks.monitoring_tasks.*": {"queue": "monitoring"},
    "api.tasks.ai_tasks.*": {"queue": "ai"},
    "api.tasks.dns_cluster_tasks.*": {"queue": "dns"},
    "api.tasks.waf_tasks.*": {"queue": "security"},
    "api.tasks.migration_tasks.*": {"queue": "migration"},
}
