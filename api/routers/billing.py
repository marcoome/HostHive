"""Billing router -- /api/v1/billing.

Handles WHMCS/FossBilling provisioning callbacks and Stripe integration.
Billing endpoints use IP whitelist + API key auth (not JWT).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import hash_password
from api.models.activity_log import ActivityLog
from api.models.integrations import Integration, IntegrationName
from api.models.packages import Package
from api.models.users import User, UserRole

logger = logging.getLogger("novapanel.billing")

router = APIRouter()


# ---------------------------------------------------------------------------
# IP Whitelist + API Key authentication (not JWT)
# ---------------------------------------------------------------------------

_BILLING_WHITELIST_CIDRS: set[str] = {
    "127.0.0.1", "::1",
    # Add WHMCS/FossBilling server IPs here or load from settings
}


async def _verify_billing_auth(
    request: Request,
    x_billing_key: str = Header(..., alias="X-Billing-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Verify caller IP is whitelisted and the billing API key is valid."""
    client_ip = request.client.host if request.client else "unknown"

    # Check IP whitelist
    if client_ip not in _BILLING_WHITELIST_CIDRS:
        logger.warning("Billing request from non-whitelisted IP: %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP not whitelisted for billing operations.",
        )

    # Verify API key against stored WHMCS integration config
    result = await db.execute(
        select(Integration).where(Integration.name == IntegrationName.WHMCS)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing integration not configured.",
        )

    # Decrypt config to get the expected API key
    from api.routers.integrations import _decrypt_config
    try:
        config = _decrypt_config(integration.config_json)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt billing config.",
        )

    expected_key = config.get("api_key", "")
    if not hmac.compare_digest(x_billing_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid billing API key.",
        )

    return client_ip


def _log(db: AsyncSession, ip: str, user_id: uuid.UUID | None, action: str, details: str):
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip,
    ))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProvisionRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    package_name: str = Field(..., max_length=128)
    domain: Optional[str] = Field(None, max_length=255)


class BillingActionResponse(BaseModel):
    success: bool
    detail: str


class StripeCheckoutRequest(BaseModel):
    package_id: uuid.UUID
    success_url: str
    cancel_url: str


class StripePlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    price_monthly: str
    disk_quota_mb: int
    bandwidth_gb: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# POST /provision -- billing system creates account
# ---------------------------------------------------------------------------
@router.post("/provision", response_model=BillingActionResponse, status_code=status.HTTP_201_CREATED)
async def provision_account(
    body: ProvisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(_verify_billing_auth),
):
    # Check uniqueness
    exists = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )

    # Find package
    pkg = (await db.execute(
        select(Package).where(Package.name == body.package_name)
    )).scalar_one_or_none()
    if pkg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Package '{body.package_name}' not found.",
        )

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=UserRole.USER,
        package_id=pkg.id,
    )
    db.add(user)
    await db.flush()

    # Optionally set up domain via agent
    if body.domain:
        try:
            agent = request.app.state.agent
            await agent.create_vhost(body.domain, f"/home/{body.username}/public_html")
        except Exception as exc:
            logger.warning("Failed to create vhost for %s: %s", body.domain, exc)

    _log(db, client_ip, user.id, "billing.provision", f"Provisioned {body.username} with package {body.package_name}")

    return BillingActionResponse(success=True, detail=f"Account {body.username} provisioned.")


# ---------------------------------------------------------------------------
# POST /suspend/{user_id}
# ---------------------------------------------------------------------------
@router.post("/suspend/{user_id}", response_model=BillingActionResponse, status_code=status.HTTP_200_OK)
async def suspend_account(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(_verify_billing_auth),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.is_suspended = True
    db.add(user)
    await db.flush()

    _log(db, client_ip, user.id, "billing.suspend", f"Suspended {user.username}")
    return BillingActionResponse(success=True, detail=f"User {user.username} suspended.")


# ---------------------------------------------------------------------------
# POST /terminate/{user_id}
# ---------------------------------------------------------------------------
@router.post("/terminate/{user_id}", response_model=BillingActionResponse, status_code=status.HTTP_200_OK)
async def terminate_account(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(_verify_billing_auth),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.is_active = False
    user.is_suspended = True
    db.add(user)
    await db.flush()

    _log(db, client_ip, user.id, "billing.terminate", f"Terminated {user.username}")
    return BillingActionResponse(success=True, detail=f"User {user.username} terminated.")


# ---------------------------------------------------------------------------
# POST /unsuspend/{user_id}
# ---------------------------------------------------------------------------
@router.post("/unsuspend/{user_id}", response_model=BillingActionResponse, status_code=status.HTTP_200_OK)
async def unsuspend_account(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client_ip: str = Depends(_verify_billing_auth),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.is_suspended = False
    db.add(user)
    await db.flush()

    _log(db, client_ip, user.id, "billing.unsuspend", f"Unsuspended {user.username}")
    return BillingActionResponse(success=True, detail=f"User {user.username} unsuspended.")


# ---------------------------------------------------------------------------
# POST /stripe/webhook -- Stripe webhook handler (verify signature)
# ---------------------------------------------------------------------------
@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Load Stripe config
    result = await db.execute(
        select(Integration).where(Integration.name == IntegrationName.STRIPE)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled or not integration.config_json:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe integration not configured.",
        )

    from api.routers.integrations import _decrypt_config
    try:
        config = _decrypt_config(integration.config_json)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt Stripe config.",
        )

    webhook_secret = config.get("webhook_secret", "")

    # Verify Stripe signature
    try:
        import stripe
        event = stripe.Webhook.construct_event(body, sig_header, webhook_secret)
    except Exception as exc:
        logger.warning("Stripe webhook verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe webhook signature.",
        )

    event_type = event.get("type", "")
    client_ip = request.client.host if request.client else "unknown"

    # Handle relevant events
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info("Stripe checkout completed: %s", session.get("id"))
    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        logger.warning("Stripe payment failed: %s", invoice.get("id"))
    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        logger.info("Stripe subscription cancelled: %s", subscription.get("id"))

    db.add(ActivityLog(
        user_id=None,
        action=f"billing.stripe.{event_type}",
        details=json.dumps({"event_id": event.get("id")}),
        ip_address=client_ip,
    ))

    return {"received": True}


# ---------------------------------------------------------------------------
# GET /stripe/plans -- list available plans (packages)
# ---------------------------------------------------------------------------
@router.get("/stripe/plans", status_code=status.HTTP_200_OK)
async def list_stripe_plans(
    db: AsyncSession = Depends(get_db),
) -> list[StripePlanResponse]:
    result = await db.execute(select(Package).order_by(Package.price_monthly))
    packages = result.scalars().all()
    return [
        StripePlanResponse(
            id=p.id,
            name=p.name,
            price_monthly=str(p.price_monthly),
            disk_quota_mb=p.disk_quota_mb,
            bandwidth_gb=p.bandwidth_gb,
        )
        for p in packages
    ]


# ---------------------------------------------------------------------------
# POST /stripe/checkout -- create Stripe checkout session
# ---------------------------------------------------------------------------
@router.post("/stripe/checkout", status_code=status.HTTP_200_OK)
async def create_stripe_checkout(
    body: StripeCheckoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Load Stripe config
    result = await db.execute(
        select(Integration).where(Integration.name == IntegrationName.STRIPE)
    )
    integration = result.scalar_one_or_none()
    if integration is None or not integration.is_enabled or not integration.config_json:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe integration not configured.",
        )

    from api.routers.integrations import _decrypt_config
    try:
        config = _decrypt_config(integration.config_json)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt Stripe config.",
        )

    # Find the package
    pkg = (await db.execute(
        select(Package).where(Package.id == body.package_id)
    )).scalar_one_or_none()
    if pkg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found.")

    try:
        import stripe
        stripe.api_key = config.get("secret_key", "")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(pkg.price_monthly * 100),
                    "recurring": {"interval": "month"},
                    "product_data": {"name": pkg.name},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            metadata={"package_id": str(pkg.id)},
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create Stripe checkout session.",
        )

    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=None,
        action="billing.stripe.checkout_created",
        details=f"Package: {pkg.name}",
        ip_address=client_ip,
    ))

    return {"checkout_url": session.url, "session_id": session.id}
