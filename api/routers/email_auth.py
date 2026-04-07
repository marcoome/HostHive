"""Email authentication router -- /api/v1/email/auth.

Manages DKIM, SPF, and DMARC configuration for domains.

All operations are performed directly via the in-process mail_executor
module (which uses subprocess + dig + opendkim-genkey). This module never
proxies to the HostHive agent on port 7080 and must not import or
reference ``request.app.state.agent``.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, status

from api.core.security import get_current_user
from api.models.users import User
from api.schemas.email_auth import (
    DKIMSetupResponse,
    DNSRecordEntry,
    EmailAuthStatus,
    EmailDNSRecords,
    EmailVerifyResponse,
)

logger = logging.getLogger("hosthive.email_auth")

router = APIRouter()


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


async def _to_thread(func, *args, **kwargs):
    """Run a blocking function in the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


# --------------------------------------------------------------------------
# GET /{domain}/status -- SPF/DKIM/DMARC status
# --------------------------------------------------------------------------


@router.get("/{domain}/status", response_model=EmailAuthStatus)
async def email_auth_status(
    domain: str,
    current_user: User = Depends(get_current_user),
):
    from agent.executors.mail_executor import get_email_auth_status

    try:
        result = await _to_thread(get_email_auth_status, domain)
    except Exception as exc:
        logger.error("Failed to check email auth status for %s: %s", domain, exc)
        raise HTTPException(status_code=400, detail=f"Failed to check status: {exc}")

    return EmailAuthStatus(
        domain=result.get("domain", domain),
        spf=result.get("spf", "missing"),
        dkim=result.get("dkim", "missing"),
        dmarc=result.get("dmarc", "missing"),
    )


# --------------------------------------------------------------------------
# POST /{domain}/setup-dkim -- generate DKIM keys
# --------------------------------------------------------------------------


@router.post("/{domain}/setup-dkim", response_model=DKIMSetupResponse)
async def setup_dkim(
    domain: str,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    from agent.executors.mail_executor import setup_dkim as _setup_dkim

    try:
        result = await _to_thread(_setup_dkim, domain)
    except Exception as exc:
        logger.error("DKIM setup failed for %s: %s", domain, exc)
        raise HTTPException(status_code=400, detail=f"DKIM setup failed: {exc}")

    return DKIMSetupResponse(
        domain=result.get("domain", domain),
        dkim_selector=result.get("dkim_selector", "default"),
        public_key=result.get("public_key", ""),
        dns_record=result.get("dns_record", ""),
        private_key_path=result.get("private_key_path", ""),
    )


# --------------------------------------------------------------------------
# GET /{domain}/dns-records -- required DNS records for email auth
# --------------------------------------------------------------------------


@router.get("/{domain}/dns-records", response_model=EmailDNSRecords)
async def email_dns_records(
    domain: str,
    current_user: User = Depends(get_current_user),
):
    """Return the SPF, DKIM, and DMARC DNS records the user should publish."""
    from agent.executors.mail_executor import (
        generate_dmarc_record,
        generate_spf_record,
        get_dkim_record,
    )

    records: list[DNSRecordEntry] = []

    # SPF — always generatable
    try:
        spf = await _to_thread(generate_spf_record, domain)
        records.append(DNSRecordEntry(
            type=spf.get("dns_type", "TXT"),
            name=spf.get("dns_name", domain),
            value=spf.get("dns_value", ""),
            description="SPF — authorizes mail servers permitted to send for this domain.",
        ))
    except Exception as exc:
        logger.warning("SPF record generation failed for %s: %s", domain, exc)

    # DKIM — only available once setup_dkim has been run
    try:
        dkim = await _to_thread(get_dkim_record, domain)
        records.append(DNSRecordEntry(
            type=dkim.get("dns_type", "TXT"),
            name=dkim.get("dns_name", f"default._domainkey.{domain}"),
            value=dkim.get("dns_value", ""),
            description="DKIM — public key matching the private key used to sign outgoing mail.",
        ))
    except FileNotFoundError:
        logger.info("DKIM keys not yet generated for %s", domain)
    except Exception as exc:
        logger.warning("DKIM record fetch failed for %s: %s", domain, exc)

    # DMARC
    try:
        dmarc = await _to_thread(generate_dmarc_record, domain)
        records.append(DNSRecordEntry(
            type=dmarc.get("dns_type", "TXT"),
            name=dmarc.get("dns_name", f"_dmarc.{domain}"),
            value=dmarc.get("dns_value", ""),
            description="DMARC — policy telling receivers what to do with unauthenticated mail.",
        ))
    except Exception as exc:
        logger.warning("DMARC record generation failed for %s: %s", domain, exc)

    return EmailDNSRecords(domain=domain, records=records)


# --------------------------------------------------------------------------
# POST /{domain}/verify -- check all email auth records
# --------------------------------------------------------------------------


@router.post("/{domain}/verify", response_model=EmailVerifyResponse)
async def verify_email_auth(
    domain: str,
    current_user: User = Depends(get_current_user),
):
    from agent.executors.mail_executor import (
        check_dmarc,
        check_spf,
        get_email_auth_status,
    )

    try:
        status_result = await _to_thread(get_email_auth_status, domain)
        spf_detail = await _to_thread(check_spf, domain)
        dmarc_detail = await _to_thread(check_dmarc, domain)
    except Exception as exc:
        logger.error("Email auth verification failed for %s: %s", domain, exc)
        raise HTTPException(status_code=400, detail=f"Verification failed: {exc}")

    spf_status = status_result.get("spf", "missing")
    dkim_status = status_result.get("dkim", "missing")
    dmarc_status = status_result.get("dmarc", "missing")

    return EmailVerifyResponse(
        domain=domain,
        spf=spf_status,
        dkim=dkim_status,
        dmarc=dmarc_status,
        all_ok=(spf_status == "ok" and dkim_status == "ok" and dmarc_status == "ok"),
        details={
            "spf_txt": spf_detail.get("txt_records", ""),
            "dmarc_txt": dmarc_detail.get("txt_records", ""),
        },
    )
