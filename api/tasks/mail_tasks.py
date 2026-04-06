"""HostHive mail-related tasks."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import httpx

from api.core.config import settings
from api.tasks import app

logger = logging.getLogger("hosthive.worker.mail")

VIRTUAL_MAILBOX_DIR = Path("/var/mail/vhosts")


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


def _get_mailbox_usage_mb(address: str) -> float:
    """Get the disk usage in MB for a single mailbox.

    Tries ``doveadm quota get`` first, falls back to ``du``.
    """
    user, domain = address.split("@")

    # Try doveadm
    try:
        result = subprocess.run(
            ["doveadm", "quota", "get", "-u", address],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts and parts[0] == "STORAGE" and len(parts) > 1:
                    return round(int(parts[1]) / 1024, 2)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Fallback: du
    maildir = VIRTUAL_MAILBOX_DIR / domain / user
    if maildir.exists():
        try:
            result = subprocess.run(
                ["du", "-sk", str(maildir)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                return round(int(result.stdout.split()[0]) / 1024, 2)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    return 0.0


@app.task(
    name="api.tasks.mail_tasks.update_quota_usage",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def update_quota_usage(self) -> dict:
    """Scan all email accounts and update their quota_used_mb in the database.

    Runs periodically via Celery Beat to keep quota usage data fresh.
    """
    from api.models.email_accounts import EmailAccount
    from api.tasks._db import get_sync_session

    logger.info("Starting quota usage scan for all mailboxes")
    updated = 0
    errors = 0

    try:
        with get_sync_session() as session:
            accounts = session.query(EmailAccount).filter(EmailAccount.is_active.is_(True)).all()

            for acct in accounts:
                try:
                    used_mb = _get_mailbox_usage_mb(acct.address)
                    acct.quota_used_mb = used_mb
                    updated += 1
                except Exception as exc:
                    logger.warning("Failed to get quota for %s: %s", acct.address, exc)
                    errors += 1

            session.commit()

        logger.info("Quota usage scan complete: %d updated, %d errors", updated, errors)
        return {"updated": updated, "errors": errors}

    except Exception as exc:
        logger.error("Quota usage scan failed: %s", exc)
        raise self.retry(exc=exc)
