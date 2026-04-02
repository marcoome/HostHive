"""HostHive mail-related tasks."""

from __future__ import annotations

import logging

import httpx

from api.core.config import settings
from api.tasks import app

logger = logging.getLogger("hosthive.worker.mail")


@app.task(
    name="api.tasks.mail_tasks.update_spam_rules",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
)
def update_spam_rules(self) -> dict:
    """Invoke ``sa-update`` via the HostHive agent to refresh SpamAssassin rules.

    This keeps spam filtering rules up-to-date with the latest definitions
    published by the SpamAssassin project.
    """
    logger.info("Triggering SpamAssassin rule update via agent")

    try:
        response = httpx.post(
            f"{settings.AGENT_URL}/api/v1/mail/update-spam-rules",
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
            timeout=300.0,
        )
        response.raise_for_status()
        result = response.json()

        updated = result.get("rules_updated", False)
        channel = result.get("channel", "unknown")

        logger.info(
            "SpamAssassin update %s (channel: %s)",
            "succeeded" if updated else "no new rules",
            channel,
        )
        return {
            "rules_updated": updated,
            "channel": channel,
            "detail": result.get("detail", ""),
        }

    except Exception as exc:
        logger.error("SpamAssassin rule update failed: %s", exc)
        raise self.retry(exc=exc)
