"""HostHive SSL certificate management tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.ssl")


@app.task(
    name="api.tasks.ssl_tasks.auto_renew_expiring_certs",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    retry_backoff=True,
    retry_backoff_max=600,
)
def auto_renew_expiring_certs(self) -> dict:
    """Find SSL certificates expiring within 30 days and renew them via the agent.

    Only certificates with ``auto_renew=True`` are renewed.
    """
    from api.models.ssl_certificates import SSLCertificate, CertProvider

    logger.info("Checking for SSL certificates expiring within 30 days")
    cutoff = datetime.utcnow() + timedelta(days=30)

    with get_sync_session() as session:
        expiring = session.execute(
            select(SSLCertificate).where(
                SSLCertificate.expires_at < cutoff,
                SSLCertificate.auto_renew.is_(True),
                SSLCertificate.provider == CertProvider.LETS_ENCRYPT,
            )
        ).scalars().all()

        renewed = 0
        failed = 0
        for cert in expiring:
            try:
                response = httpx.post(
                    f"{settings.AGENT_URL}/api/v1/ssl/renew",
                    json={
                        "domain": cert.domain_name,
                        "cert_id": str(cert.id),
                    },
                    headers={"X-Agent-Secret": settings.AGENT_SECRET},
                    timeout=120.0,
                )
                response.raise_for_status()
                result = response.json()

                cert.cert_path = result.get("cert_path", cert.cert_path)
                cert.key_path = result.get("key_path", cert.key_path)
                cert.expires_at = datetime.fromisoformat(result["expires_at"])
                cert.last_renewed_at = datetime.utcnow()
                renewed += 1

                logger.info(
                    "Renewed SSL certificate for %s (expires %s)",
                    cert.domain_name, cert.expires_at,
                )
            except Exception as exc:
                failed += 1
                logger.error(
                    "Failed to renew SSL for %s: %s", cert.domain_name, exc,
                )

        session.commit()

    logger.info(
        "SSL renewal complete: %d renewed, %d failed out of %d expiring",
        renewed, failed, len(expiring),
    )
    return {"renewed": renewed, "failed": failed, "total_expiring": len(expiring)}


@app.task(
    name="api.tasks.ssl_tasks.check_cert_expiry",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
)
def check_cert_expiry(self) -> dict:
    """Find certificates expiring within 14 days and create alert notifications.

    This is an informational check -- it does not attempt renewal, just
    notifies the domain owner so they can take action.
    """
    from api.models.ssl_certificates import SSLCertificate
    from api.tasks.notification_tasks import send_notification

    logger.info("Checking for SSL certificates expiring within 14 days")
    cutoff = datetime.utcnow() + timedelta(days=14)

    with get_sync_session() as session:
        expiring = session.execute(
            select(SSLCertificate).where(
                SSLCertificate.expires_at < cutoff,
                SSLCertificate.expires_at > datetime.utcnow(),
            )
        ).scalars().all()

        alerted = 0
        for cert in expiring:
            days_left = (cert.expires_at - datetime.utcnow()).days
            message = (
                f"SSL certificate for {cert.domain_name} expires in "
                f"{days_left} day{'s' if days_left != 1 else ''}. "
                f"{'Auto-renewal is enabled.' if cert.auto_renew else 'Please renew manually.'}"
            )
            # Fetch domain owner -- domain_id links to domains table
            from api.models.domains import Domain

            domain = session.get(Domain, cert.domain_id)
            if domain:
                level = "critical" if days_left <= 3 else "warning"
                send_notification.delay(str(domain.user_id), message, level)
                alerted += 1
                logger.info(
                    "Alert sent for %s (%d days remaining)",
                    cert.domain_name, days_left,
                )

    logger.info("Expiry check complete: %d alerts sent", alerted)
    return {"alerted": alerted, "total_expiring": len(expiring)}
