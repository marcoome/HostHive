"""HostHive notification and expiry-alert tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.notifications")


@app.task(
    name="api.tasks.notification_tasks.send_expiry_alerts",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
)
def send_expiry_alerts(self) -> dict:
    """Check SSL certificates and domains for upcoming expiry and notify owners.

    Runs daily at 09:00 UTC via beat.  Generates warnings for:
    - SSL certificates expiring within 14 days
    - Domains nearing any configured expiry window
    """
    from api.models.ssl_certificates import SSLCertificate
    from api.models.domains import Domain

    logger.info("Checking for expiring SSL certificates and domains")
    now = datetime.utcnow()
    ssl_cutoff = now + timedelta(days=14)
    alerts_sent = 0

    with get_sync_session() as session:
        # --- SSL expiry alerts ---
        expiring_certs = session.execute(
            select(SSLCertificate).where(
                SSLCertificate.expires_at < ssl_cutoff,
                SSLCertificate.expires_at > now,
            )
        ).scalars().all()

        for cert in expiring_certs:
            days_left = (cert.expires_at - now).days
            domain = session.get(Domain, cert.domain_id)
            if not domain:
                continue

            level = "critical" if days_left <= 3 else "warning"
            message = (
                f"SSL certificate for {cert.domain_name} expires in "
                f"{days_left} day{'s' if days_left != 1 else ''}."
            )
            send_notification.delay(str(domain.user_id), message, level)
            alerts_sent += 1

        # --- Domain expiry alerts (if domain model gains expires_at) ---
        # Future extension point: check domain registration expiry.

    logger.info("Expiry alert check complete: %d notifications dispatched", alerts_sent)
    return {"alerts_sent": alerts_sent}


@app.task(
    name="api.tasks.notification_tasks.send_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    retry_backoff=True,
    retry_backoff_max=300,
)
def send_notification(
    self,
    user_id: str,
    message: str,
    level: str = "info",
) -> dict:
    """Persist a notification record for the given user.

    Args:
        user_id: UUID of the recipient user.
        message: Human-readable notification text.
        level: One of info, warning, error, critical.

    Returns:
        Dict with the created notification id.
    """
    from api.models.notifications import Notification, NotificationLevel

    logger.info("Creating %s notification for user %s", level, user_id)

    with get_sync_session() as session:
        notification = Notification(
            user_id=user_id,
            message=message,
            level=NotificationLevel(level),
        )
        session.add(notification)
        session.commit()
        notif_id = str(notification.id)

    logger.info("Notification %s created for user %s", notif_id, user_id)
    return {"notification_id": notif_id, "user_id": user_id, "level": level}
