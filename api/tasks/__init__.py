"""HostHive Celery application initialization."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from celery import Celery

from api.core.config import settings

# ---------------------------------------------------------------------------
# Logging setup -- all worker output goes to /opt/hosthive/logs/worker.log
# ---------------------------------------------------------------------------
_LOG_DIR = Path("/opt/hosthive/logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_handler = logging.FileHandler(_LOG_DIR / "worker.log")
_log_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
_log_handler.setLevel(logging.INFO)

logger = logging.getLogger("hosthive.worker")
logger.addHandler(_log_handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------
app = Celery("hosthive")

app.config_from_object("api.tasks.celeryconfig")

# Broker & result backend from central settings
app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_hijack_root_logger=False,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks in all api.tasks.* modules
app.autodiscover_tasks([
    "api.tasks.ai_tasks",
    "api.tasks.backup_tasks",
    "api.tasks.ssl_tasks",
    "api.tasks.server_tasks",
    "api.tasks.mail_tasks",
    "api.tasks.notification_tasks",
    "api.tasks.monitoring_tasks",
    "api.tasks.integration_tasks",
    "api.tasks.dns_cluster_tasks",
    "api.tasks.waf_tasks",
    "api.tasks.migration_tasks",
])
