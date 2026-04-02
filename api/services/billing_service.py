"""Billing integration handlers for WHMCS and Stripe."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from api.core.config import settings
from api.core.encryption import decrypt_value

logger = logging.getLogger("hosthive.billing")

_TIMEOUT = 30.0


# ═══════════════════════════════════════════════════════════════════════════
# WHMCS handler
# ═══════════════════════════════════════════════════════════════════════════


class WHMCSHandler:
    """Handle provisioning requests coming from WHMCS via its module hooks."""

    def __init__(self, encrypted_config: str) -> None:
        config = json.loads(decrypt_value(encrypted_config, settings.SECRET_KEY))
        self._api_url: str = config["api_url"].rstrip("/")
        self._api_key: str = config["api_key"]
        self._allowed_ips: list[str] = config.get("allowed_ips", [])

    def is_ip_allowed(self, ip: str) -> bool:
        """Check whether the calling IP is in the allowed list."""
        if not self._allowed_ips:
            return True  # no restriction configured
        return ip in self._allowed_ips

    async def provision(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new hosting account based on a WHMCS provisioning request."""
        username = payload.get("username", "")
        email = payload.get("email", "")
        package_id = payload.get("package_id")

        result = await create_account_from_billing(username, email, package_id)
        logger.info("WHMCS provision: created user %s", username)
        return result

    async def suspend(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Suspend an account from a WHMCS request."""
        user_id = payload.get("user_id", "")
        result = await suspend_from_billing(user_id)
        logger.info("WHMCS suspend: user %s", user_id)
        return result

    async def terminate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Terminate (delete) an account from a WHMCS request."""
        user_id = payload.get("user_id", "")
        result = await terminate_from_billing(user_id)
        logger.info("WHMCS terminate: user %s", user_id)
        return result


# ═══════════════════════════════════════════════════════════════════════════
# Stripe handler
# ═══════════════════════════════════════════════════════════════════════════


class StripeHandler:
    """Handle Stripe webhook events for subscription lifecycle."""

    def __init__(self, encrypted_config: str) -> None:
        config = json.loads(decrypt_value(encrypted_config, settings.SECRET_KEY))
        self._secret_key: str = config["secret_key"]
        self._webhook_secret: str = config["webhook_secret"]
        self._currency: str = config.get("currency", "usd")

    async def handle_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Route a Stripe event to the correct handler method.

        Supported events:
        - checkout.session.completed
        - invoice.paid
        - invoice.payment_failed
        - customer.subscription.deleted
        """
        handlers = {
            "checkout.session.completed": self._on_checkout_completed,
            "invoice.paid": self._on_invoice_paid,
            "invoice.payment_failed": self._on_payment_failed,
            "customer.subscription.deleted": self._on_subscription_deleted,
        }

        handler = handlers.get(event_type)
        if handler is None:
            logger.debug("Ignoring unhandled Stripe event: %s", event_type)
            return {"status": "ignored", "event_type": event_type}

        return await handler(data)

    async def _on_checkout_completed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """A new checkout session was completed — provision the account."""
        obj = data.get("object", {})
        email = obj.get("customer_email", "")
        metadata = obj.get("metadata", {})
        username = metadata.get("username", "")
        package_id = metadata.get("package_id")

        if username and email:
            result = await create_account_from_billing(username, email, package_id)
            logger.info("Stripe checkout completed: provisioned user %s", username)
            return result

        logger.warning("Stripe checkout completed but missing username/email")
        return {"status": "skipped", "reason": "missing metadata"}

    async def _on_invoice_paid(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Invoice paid — ensure the account is active."""
        obj = data.get("object", {})
        metadata = obj.get("metadata", {}) or obj.get("subscription_details", {}).get("metadata", {})
        user_id = metadata.get("user_id")

        if user_id:
            logger.info("Stripe invoice.paid for user %s — no action needed", user_id)
        return {"status": "ok", "event": "invoice.paid"}

    async def _on_payment_failed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Payment failed — suspend the account after grace period."""
        obj = data.get("object", {})
        metadata = obj.get("metadata", {}) or obj.get("subscription_details", {}).get("metadata", {})
        user_id = metadata.get("user_id")

        if user_id:
            result = await suspend_from_billing(user_id)
            logger.info("Stripe payment failed: suspended user %s", user_id)
            return result

        logger.warning("Stripe payment failed but no user_id in metadata")
        return {"status": "skipped", "reason": "missing user_id"}

    async def _on_subscription_deleted(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Subscription cancelled — terminate the account."""
        obj = data.get("object", {})
        metadata = obj.get("metadata", {})
        user_id = metadata.get("user_id")

        if user_id:
            result = await terminate_from_billing(user_id)
            logger.info("Stripe subscription deleted: terminated user %s", user_id)
            return result

        logger.warning("Stripe subscription deleted but no user_id in metadata")
        return {"status": "skipped", "reason": "missing user_id"}


# ═══════════════════════════════════════════════════════════════════════════
# Shared account lifecycle helpers
# ═══════════════════════════════════════════════════════════════════════════


async def create_account_from_billing(
    username: str,
    email: str,
    package_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new hosting account via the HostHive agent.

    This is a shared entry point used by both WHMCS and Stripe handlers.
    """
    payload: Dict[str, Any] = {"username": username, "email": email}
    if package_id:
        payload["package_id"] = package_id

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.AGENT_URL}/api/v1/users/provision",
            json=payload,
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
        )
        resp.raise_for_status()
        result = resp.json()

    logger.info("Provisioned billing account for %s <%s>", username, email)
    return {"status": "provisioned", "user": result}


async def suspend_from_billing(user_id: str) -> Dict[str, Any]:
    """Suspend an existing hosting account via the agent."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.AGENT_URL}/api/v1/users/{user_id}/suspend",
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
        )
        resp.raise_for_status()

    logger.info("Suspended billing account %s", user_id)
    return {"status": "suspended", "user_id": user_id}


async def terminate_from_billing(user_id: str) -> Dict[str, Any]:
    """Terminate (delete) a hosting account via the agent."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.AGENT_URL}/api/v1/users/{user_id}/terminate",
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
        )
        resp.raise_for_status()

    logger.info("Terminated billing account %s", user_id)
    return {"status": "terminated", "user_id": user_id}
