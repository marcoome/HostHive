"""Email deliverability testing service.

Performs comprehensive checks against a domain to evaluate email
deliverability: SPF, DKIM, DMARC, MX, PTR, blacklist, TLS, and HELO.
Results are cached in Redis for 1 hour.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from datetime import datetime, timezone
from typing import Any

import dns.resolver
import dns.reversename

from api.schemas.email_deliverability import CheckStatus, DeliverabilityCheck, DeliverabilityReport

logger = logging.getLogger("hosthive.email_deliverability")

_CACHE_PREFIX = "hosthive:deliverability:"
_CACHE_TTL = 3600  # 1 hour

# Common DNS-based blacklists
DNSBL_LIST = [
    "zen.spamhaus.org",
    "bl.spamcop.net",
    "b.barracudacentral.org",
    "dnsbl.sorbs.net",
]

DKIM_SELECTOR = "default"


# ---------------------------------------------------------------------------
# Individual check helpers (all sync, run via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _resolve(qname: str, rdtype: str, timeout: float = 10.0) -> list[str]:
    """Resolve DNS records, returning a list of strings."""
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        answers = resolver.resolve(qname, rdtype)
        return [rdata.to_text() for rdata in answers]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return []
    except dns.resolver.LifetimeTimeout:
        return []
    except Exception as exc:
        logger.debug("DNS resolve error for %s/%s: %s", qname, rdtype, exc)
        return []


def _check_spf(domain: str) -> DeliverabilityCheck:
    """Check SPF record existence and validity."""
    txt_records = _resolve(domain, "TXT")
    spf_records = [r for r in txt_records if "v=spf1" in r.lower()]

    if not spf_records:
        return DeliverabilityCheck(
            name="SPF Record",
            status=CheckStatus.FAIL,
            details="No SPF record found in DNS TXT records.",
            recommendation=f'Add a TXT record for {domain} with value: "v=spf1 mx a ~all"',
        )

    if len(spf_records) > 1:
        return DeliverabilityCheck(
            name="SPF Record",
            status=CheckStatus.WARN,
            details=f"Multiple SPF records found ({len(spf_records)}). Only one is allowed per RFC 7208.",
            recommendation="Merge all SPF records into a single TXT record.",
        )

    spf = spf_records[0].strip('"')
    if "+all" in spf:
        return DeliverabilityCheck(
            name="SPF Record",
            status=CheckStatus.WARN,
            details=f'SPF record uses "+all" which allows any server to send mail: {spf}',
            recommendation='Change "+all" to "~all" (softfail) or "-all" (hardfail).',
        )

    return DeliverabilityCheck(
        name="SPF Record",
        status=CheckStatus.PASS,
        details=f"Valid SPF record found: {spf}",
    )


def _check_dkim(domain: str) -> DeliverabilityCheck:
    """Check DKIM record for the default selector."""
    dkim_domain = f"{DKIM_SELECTOR}._domainkey.{domain}"
    txt_records = _resolve(dkim_domain, "TXT")

    dkim_records = [r for r in txt_records if "p=" in r]

    if not dkim_records:
        return DeliverabilityCheck(
            name="DKIM Record",
            status=CheckStatus.FAIL,
            details=f"No DKIM record found at {dkim_domain}.",
            recommendation=(
                f"Set up DKIM signing and add a TXT record for "
                f"{dkim_domain} containing your DKIM public key."
            ),
        )

    return DeliverabilityCheck(
        name="DKIM Record",
        status=CheckStatus.PASS,
        details=f"DKIM record found at {dkim_domain}.",
    )


def _check_dmarc(domain: str) -> DeliverabilityCheck:
    """Check DMARC record."""
    dmarc_domain = f"_dmarc.{domain}"
    txt_records = _resolve(dmarc_domain, "TXT")
    dmarc_records = [r for r in txt_records if "v=dmarc1" in r.lower()]

    if not dmarc_records:
        return DeliverabilityCheck(
            name="DMARC Record",
            status=CheckStatus.FAIL,
            details=f"No DMARC record found at {dmarc_domain}.",
            recommendation=(
                f'Add a TXT record for {dmarc_domain} with value: '
                f'"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}; fo=1"'
            ),
        )

    record = dmarc_records[0].strip('"')
    if "p=none" in record.lower():
        return DeliverabilityCheck(
            name="DMARC Record",
            status=CheckStatus.WARN,
            details=f"DMARC record found but policy is 'none' (monitoring only): {record}",
            recommendation="Change DMARC policy to 'quarantine' or 'reject' for better protection.",
        )

    return DeliverabilityCheck(
        name="DMARC Record",
        status=CheckStatus.PASS,
        details=f"Valid DMARC record found: {record}",
    )


def _check_mx(domain: str) -> DeliverabilityCheck:
    """Check MX records."""
    mx_records = _resolve(domain, "MX")

    if not mx_records:
        return DeliverabilityCheck(
            name="MX Records",
            status=CheckStatus.FAIL,
            details="No MX records found for the domain.",
            recommendation=f"Add MX records pointing to your mail server for {domain}.",
        )

    return DeliverabilityCheck(
        name="MX Records",
        status=CheckStatus.PASS,
        details=f"MX records found: {'; '.join(mx_records)}",
    )


def _get_server_ip(domain: str) -> str | None:
    """Get the IP address of the first MX host (or the A record of the domain)."""
    mx_records = _resolve(domain, "MX")
    if mx_records:
        # MX format: "10 mail.example.com."
        mx_host = mx_records[0].split()[-1].rstrip(".")
        a_records = _resolve(mx_host, "A")
        if a_records:
            return a_records[0].strip('"')

    # Fallback to the domain's own A record
    a_records = _resolve(domain, "A")
    if a_records:
        return a_records[0].strip('"')
    return None


def _check_ptr(domain: str) -> DeliverabilityCheck:
    """Check reverse DNS (PTR) for the server IP."""
    ip = _get_server_ip(domain)
    if not ip:
        return DeliverabilityCheck(
            name="Reverse DNS (PTR)",
            status=CheckStatus.WARN,
            details="Could not determine server IP to check PTR record.",
            recommendation="Ensure your mail server has a valid A record.",
        )

    try:
        rev_name = dns.reversename.from_address(ip)
        ptr_records = _resolve(str(rev_name), "PTR")
    except Exception:
        ptr_records = []

    if not ptr_records:
        return DeliverabilityCheck(
            name="Reverse DNS (PTR)",
            status=CheckStatus.FAIL,
            details=f"No PTR record found for {ip}.",
            recommendation=f"Set a PTR record for {ip} pointing to your mail server hostname.",
        )

    ptr_host = ptr_records[0].rstrip(".").strip('"')
    return DeliverabilityCheck(
        name="Reverse DNS (PTR)",
        status=CheckStatus.PASS,
        details=f"PTR record for {ip} resolves to {ptr_host}.",
    )


def _check_blacklists(domain: str) -> DeliverabilityCheck:
    """Check if the server IP is listed on common DNS blacklists."""
    ip = _get_server_ip(domain)
    if not ip:
        return DeliverabilityCheck(
            name="Blacklist Check",
            status=CheckStatus.WARN,
            details="Could not determine server IP to check blacklists.",
            recommendation="Ensure your mail server has a valid A/MX record.",
        )

    listed_on: list[str] = []
    checked: list[str] = []

    # Reverse the IP octets for DNSBL lookup
    reversed_ip = ".".join(reversed(ip.split(".")))

    for bl in DNSBL_LIST:
        query = f"{reversed_ip}.{bl}"
        try:
            results = _resolve(query, "A")
            if results:
                listed_on.append(bl)
        except Exception:
            pass
        checked.append(bl)

    if listed_on:
        return DeliverabilityCheck(
            name="Blacklist Check",
            status=CheckStatus.FAIL,
            details=f"IP {ip} is listed on: {', '.join(listed_on)}",
            recommendation=(
                "Request delisting from the blacklist providers. "
                "Investigate the cause (open relay, compromised account, spam)."
            ),
        )

    return DeliverabilityCheck(
        name="Blacklist Check",
        status=CheckStatus.PASS,
        details=f"IP {ip} is not listed on any of {len(checked)} checked blacklists.",
    )


def _check_tls(domain: str) -> DeliverabilityCheck:
    """Check if STARTTLS is supported on port 25."""
    ip = _get_server_ip(domain)
    target = ip or domain

    try:
        with smtplib.SMTP(target, 25, timeout=10) as smtp:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                return DeliverabilityCheck(
                    name="TLS (STARTTLS)",
                    status=CheckStatus.PASS,
                    details=f"STARTTLS is supported on {target}:25.",
                )
            else:
                return DeliverabilityCheck(
                    name="TLS (STARTTLS)",
                    status=CheckStatus.WARN,
                    details=f"Server {target}:25 does not advertise STARTTLS.",
                    recommendation="Enable STARTTLS in your mail server configuration (Exim4/Postfix).",
                )
    except (ConnectionRefusedError, OSError, smtplib.SMTPException) as exc:
        return DeliverabilityCheck(
            name="TLS (STARTTLS)",
            status=CheckStatus.WARN,
            details=f"Could not connect to {target}:25 to test STARTTLS: {exc}",
            recommendation="Ensure port 25 is open and your mail server is running.",
        )


def _check_helo(domain: str) -> DeliverabilityCheck:
    """Check that the HELO/EHLO hostname matches the server PTR/MX."""
    ip = _get_server_ip(domain)
    target = ip or domain

    try:
        with smtplib.SMTP(target, 25, timeout=10) as smtp:
            code, msg = smtp.ehlo()
            if code != 250:
                return DeliverabilityCheck(
                    name="HELO/EHLO Hostname",
                    status=CheckStatus.WARN,
                    details=f"EHLO returned code {code}.",
                    recommendation="Check your mail server EHLO configuration.",
                )

            helo_host = msg.decode("utf-8", errors="replace").split("\n")[0].strip()

            # Get expected hostnames from MX and PTR
            mx_records = _resolve(domain, "MX")
            expected_hosts = set()
            for mx in mx_records:
                parts = mx.split()
                if len(parts) >= 2:
                    expected_hosts.add(parts[-1].rstrip(".").lower())

            if ip:
                try:
                    rev_name = dns.reversename.from_address(ip)
                    ptrs = _resolve(str(rev_name), "PTR")
                    for ptr in ptrs:
                        expected_hosts.add(ptr.rstrip(".").strip('"').lower())
                except Exception:
                    pass

            helo_lower = helo_host.lower()
            if helo_lower in expected_hosts or helo_lower == domain.lower():
                return DeliverabilityCheck(
                    name="HELO/EHLO Hostname",
                    status=CheckStatus.PASS,
                    details=f"EHLO hostname '{helo_host}' matches expected records.",
                )

            return DeliverabilityCheck(
                name="HELO/EHLO Hostname",
                status=CheckStatus.WARN,
                details=(
                    f"EHLO hostname '{helo_host}' does not match MX/PTR records. "
                    f"Expected one of: {', '.join(expected_hosts) if expected_hosts else domain}"
                ),
                recommendation="Set the EHLO hostname in your MTA to match your server's PTR record or MX hostname.",
            )
    except (ConnectionRefusedError, OSError, smtplib.SMTPException) as exc:
        return DeliverabilityCheck(
            name="HELO/EHLO Hostname",
            status=CheckStatus.WARN,
            details=f"Could not connect to {target}:25 to check EHLO: {exc}",
            recommendation="Ensure port 25 is open and your mail server is running.",
        )


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------

# Weight per check (total = 100 when all pass)
_WEIGHTS: dict[str, int] = {
    "SPF Record": 15,
    "DKIM Record": 15,
    "DMARC Record": 15,
    "MX Records": 15,
    "Reverse DNS (PTR)": 10,
    "Blacklist Check": 15,
    "TLS (STARTTLS)": 10,
    "HELO/EHLO Hostname": 5,
}


def _calculate_score(checks: list[DeliverabilityCheck]) -> int:
    """Calculate a 0-100 deliverability score from individual checks."""
    score = 0
    for check in checks:
        weight = _WEIGHTS.get(check.name, 0)
        if check.status == CheckStatus.PASS:
            score += weight
        elif check.status == CheckStatus.WARN:
            score += weight // 2
        # FAIL adds 0
    return min(100, max(0, score))


def _build_expected_records(domain: str) -> dict[str, str]:
    """Generate the expected DNS records for a domain."""
    return {
        "SPF": f'v=spf1 mx a ~all',
        "SPF_name": domain,
        "SPF_type": "TXT",
        "DKIM": f"(DKIM public key -- generate via panel)",
        "DKIM_name": f"{DKIM_SELECTOR}._domainkey.{domain}",
        "DKIM_type": "TXT",
        "DMARC": f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}; fo=1",
        "DMARC_name": f"_dmarc.{domain}",
        "DMARC_type": "TXT",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_deliverability_test(domain: str, redis: Any = None) -> DeliverabilityReport:
    """Run all deliverability checks for a domain.

    If a Redis client is provided, results are cached for 1 hour.
    """
    cache_key = f"{_CACHE_PREFIX}{domain}"

    # Check cache
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return DeliverabilityReport(**data)
        except Exception as exc:
            logger.debug("Cache read failed for %s: %s", domain, exc)

    # Run all checks concurrently via thread pool (they use blocking DNS/SMTP)
    check_funcs = [
        _check_spf,
        _check_dkim,
        _check_dmarc,
        _check_mx,
        _check_ptr,
        _check_blacklists,
        _check_tls,
        _check_helo,
    ]

    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(None, fn, domain) for fn in check_funcs]
    checks: list[DeliverabilityCheck] = await asyncio.gather(*tasks)

    score = _calculate_score(checks)
    tested_at = datetime.now(timezone.utc)
    expected_records = _build_expected_records(domain)

    report = DeliverabilityReport(
        domain=domain,
        score=score,
        checks=checks,
        tested_at=tested_at,
        expected_records=expected_records,
    )

    # Cache in Redis
    if redis is not None:
        try:
            await redis.set(
                cache_key,
                report.model_dump_json(),
                ex=_CACHE_TTL,
            )
        except Exception as exc:
            logger.warning("Failed to cache deliverability report for %s: %s", domain, exc)

    return report
