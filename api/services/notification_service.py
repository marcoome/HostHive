"""Multi-channel notification dispatcher (Telegram, Slack, Discord)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from api.core.config import settings
from api.core.encryption import decrypt_value

logger = logging.getLogger("hosthive.notifications")

_TIMEOUT = 30.0

# Recognised alert types — kept as constants so callers can reference them.
ALERT_SERVICE_DOWN = "service_down"
ALERT_DISK_CRITICAL = "disk_critical"
ALERT_SSL_EXPIRING = "ssl_expiring"
ALERT_BRUTE_FORCE = "brute_force"
ALERT_BACKUP_FAILED = "backup_failed"
ALERT_USER_CREATED = "user_created"

_SEVERITY_EMOJI = {
    "critical": "\u26a0\ufe0f",  # warning sign
    "warning": "\u26a1",         # lightning
    "info": "\u2139\ufe0f",      # info
}


class NotificationDispatcher:
    """Sends alerts to all enabled notification channels."""

    # ------------------------------------------------------------------
    # Individual channel senders
    # ------------------------------------------------------------------

    @staticmethod
    async def send_telegram(bot_token: str, chat_id: str, message: str) -> Dict[str, Any]:
        """Send a message via the Telegram Bot API."""
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
        logger.info("Telegram message sent to chat %s", chat_id)
        return result

    @staticmethod
    async def send_slack(webhook_url: str, message: str) -> int:
        """Post a message to a Slack incoming webhook."""
        payload = {"text": message}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("Slack message sent")
        return resp.status_code

    @staticmethod
    async def send_discord(webhook_url: str, message: str) -> int:
        """Post a message to a Discord webhook."""
        payload = {"content": message}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("Discord message sent")
        return resp.status_code

    # ------------------------------------------------------------------
    # Unified dispatcher
    # ------------------------------------------------------------------

    @staticmethod
    async def dispatch_alert(
        alert_type: str,
        message: str,
        severity: str = "info",
        *,
        integrations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send an alert to ALL enabled notification channels.

        Parameters
        ----------
        alert_type:
            One of the ``ALERT_*`` constants.
        message:
            Human-readable alert body.
        severity:
            ``"info"``, ``"warning"``, or ``"critical"``.
        integrations:
            Pre-loaded list of integration dicts with keys ``name``,
            ``is_enabled``, and ``config_json`` (encrypted). If *None*, the
            caller must supply them — this method does NOT query the DB
            directly so it can be used from both async and Celery contexts.
        """
        if integrations is None:
            integrations = []

        emoji = _SEVERITY_EMOJI.get(severity, "")
        formatted = f"{emoji} [{severity.upper()}] {alert_type}: {message}"

        results: Dict[str, Any] = {}
        dispatcher = NotificationDispatcher()

        for integration in integrations:
            name = integration.get("name")
            if not integration.get("is_enabled"):
                continue

            encrypted_cfg = integration.get("config_json")
            if not encrypted_cfg:
                continue

            try:
                config = json.loads(
                    decrypt_value(encrypted_cfg, settings.SECRET_KEY)
                )
            except Exception:
                logger.warning("Failed to decrypt config for %s", name)
                continue

            try:
                if name == "telegram":
                    await dispatcher.send_telegram(
                        config["bot_token"], config["chat_id"], formatted
                    )
                    results["telegram"] = "sent"
                elif name == "slack":
                    await dispatcher.send_slack(config["webhook_url"], formatted)
                    results["slack"] = "sent"
                elif name == "discord":
                    await dispatcher.send_discord(config["webhook_url"], formatted)
                    results["discord"] = "sent"
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Failed to send %s notification: %s %s",
                    name, exc.response.status_code, exc.response.text,
                )
                results[name] = f"error:{exc.response.status_code}"
            except Exception as exc:
                logger.error("Failed to send %s notification: %s", name, exc)
                results[name] = f"error:{exc}"

        logger.info(
            "Dispatched alert [%s] severity=%s results=%s",
            alert_type, severity, results,
        )
        return results
