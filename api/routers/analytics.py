"""Analytics router -- /api/v1/analytics

GoAccess-powered visitor analytics: reports, stats, real-time visitors,
top pages, top countries.

This router runs GoAccess directly against per-domain Nginx access logs.
No agent proxying is required.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.core.security import get_current_user, require_role
from api.models.users import User
from api.schemas.analytics import (
    CountryEntry,
    PageEntry,
    RealtimeVisitorsResponse,
    ReportGenerate,
    ReportResponse,
    TopCountriesResponse,
    TopPagesResponse,
    VisitorStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_admin_or_reseller = require_role("admin", "reseller")


# ---------------------------------------------------------------------------
# Helpers -- log discovery and GoAccess invocation
# ---------------------------------------------------------------------------

_NGINX_LOG_DIRS = (
    "/var/log/nginx",
    "/var/log/apache2",
)

_REPORT_DIR = Path("/var/lib/hosthive/analytics")


def _validate_domain(domain: str) -> None:
    if not re.match(r"^[a-zA-Z0-9._-]+$", domain) or ".." in domain:
        raise HTTPException(status_code=400, detail="Invalid domain name.")


def _find_access_log(domain: str) -> Path | None:
    """Return the most recent access log for a domain, if any."""
    candidates = [
        f"{domain}.access.log",
        f"{domain}-access.log",
        f"access-{domain}.log",
    ]
    for base in _NGINX_LOG_DIRS:
        base_path = Path(base)
        if not base_path.exists():
            continue
        for name in candidates:
            candidate = base_path / name
            if candidate.exists():
                return candidate
        # Fallback: scan for any file containing the domain in the name
        for entry in base_path.glob(f"*{domain}*access*.log"):
            return entry
    # Ultimate fallback: the default Nginx access log
    default = Path("/var/log/nginx/access.log")
    if default.exists():
        return default
    return None


async def _run(cmd: list[str], *, timeout: int = 60, stdin_bytes: bytes | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "GoAccess timed out"
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _run_goaccess_json(log_path: Path, *, extra_args: list[str] | None = None) -> dict[str, Any]:
    """Invoke GoAccess on a log file and return its parsed JSON output.

    Falls back to an empty dict if GoAccess is not installed or the log
    cannot be read -- callers should handle empty results gracefully.
    """
    if not shutil.which("goaccess"):
        logger.warning("goaccess binary not found on PATH -- returning empty analytics")
        return {}

    if not log_path.exists():
        return {}

    args = [
        "goaccess",
        str(log_path),
        "--log-format=COMBINED",
        "--output=json",
        "--no-global-config",
        "--jobs=1",
    ]
    if extra_args:
        args.extend(extra_args)

    rc, out, err = await _run(args, timeout=120)
    if rc != 0:
        logger.warning("goaccess failed (rc=%s): %s", rc, err.strip())
        return {}
    try:
        return json.loads(out) if out.strip() else {}
    except json.JSONDecodeError as exc:
        logger.warning("goaccess produced invalid JSON: %s", exc)
        return {}


async def _run_goaccess_html(log_path: Path, report_file: Path) -> bool:
    if not shutil.which("goaccess"):
        return False
    if not log_path.exists():
        return False

    report_file.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "goaccess",
        str(log_path),
        "--log-format=COMBINED",
        "--output",
        str(report_file),
        "--no-global-config",
        "--jobs=1",
    ]
    rc, _out, err = await _run(args, timeout=180)
    if rc != 0:
        logger.warning("goaccess HTML report failed: %s", err.strip())
        return False
    return True


# ---------------------------------------------------------------------------
# GET /{domain}/report -- get or generate GoAccess report
# ---------------------------------------------------------------------------

@router.get("/{domain}/report", response_model=ReportResponse)
async def get_report(
    domain: str,
    period: str = Query("daily", description="Report period"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _validate_domain(domain)
    log_path = _find_access_log(domain)
    if log_path is None:
        raise HTTPException(status_code=404, detail=f"No access log found for {domain}")

    report_file = _REPORT_DIR / domain / f"{period}.html"
    ok = await _run_goaccess_html(log_path, report_file)
    if not ok:
        raise HTTPException(
            status_code=500,
            detail="Report generation failed. Ensure 'goaccess' is installed.",
        )

    return ReportResponse(
        domain=domain,
        period=period,
        report_path=str(report_file),
        report_url=f"/analytics/reports/{domain}/{period}.html",
    )


# ---------------------------------------------------------------------------
# GET /{domain}/stats -- parsed visitor stats (JSON)
# ---------------------------------------------------------------------------

@router.get("/{domain}/stats", response_model=VisitorStatsResponse)
async def get_stats(
    domain: str,
    period: str = Query("7d", description="Stats period"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _validate_domain(domain)
    log_path = _find_access_log(domain)
    if log_path is None:
        return VisitorStatsResponse(domain=domain, period=period)

    t0 = time.time()
    data = await _run_goaccess_json(log_path)
    general = data.get("general", {}) if isinstance(data, dict) else {}

    return VisitorStatsResponse(
        domain=domain,
        period=period,
        total_requests=int(general.get("total_requests", 0) or 0),
        unique_visitors=int(general.get("unique_visitors", 0) or 0),
        bandwidth_bytes=int(general.get("bandwidth", 0) or 0),
        failed_requests=int(general.get("failed_requests", 0) or 0),
        generation_time=int((time.time() - t0) * 1000),
        log_size=log_path.stat().st_size if log_path.exists() else 0,
    )


# ---------------------------------------------------------------------------
# GET /{domain}/visitors -- real-time visitor count
# ---------------------------------------------------------------------------

@router.get("/{domain}/visitors", response_model=RealtimeVisitorsResponse)
async def get_visitors(
    domain: str,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _validate_domain(domain)
    log_path = _find_access_log(domain)
    if log_path is None:
        return RealtimeVisitorsResponse(domain=domain)

    # Approximate real-time by tailing the last 2000 lines and counting
    # entries within the past 5 minutes.
    try:
        rc, out, _ = await _run(["tail", "-n", "2000", str(log_path)], timeout=10)
    except Exception as exc:
        logger.warning("tail failed: %s", exc)
        return RealtimeVisitorsResponse(domain=domain)

    if rc != 0:
        return RealtimeVisitorsResponse(domain=domain)

    now = time.time()
    cutoff = now - 300  # 5 minutes
    unique_ips: set[str] = set()
    hits = 0
    ts_re = re.compile(r"\[([^\]]+)\]")
    ip_re = re.compile(r"^(\d+\.\d+\.\d+\.\d+)")
    for line in out.splitlines():
        m = ts_re.search(line)
        if not m:
            continue
        try:
            # e.g. "06/Apr/2026:12:34:56 +0000"
            ts_struct = time.strptime(m.group(1).split()[0], "%d/%b/%Y:%H:%M:%S")
            ts = time.mktime(ts_struct)
        except Exception:
            continue
        if ts < cutoff:
            continue
        hits += 1
        ip_m = ip_re.match(line)
        if ip_m:
            unique_ips.add(ip_m.group(1))

    return RealtimeVisitorsResponse(
        domain=domain,
        active_visitors=len(unique_ips),
        hits_last_5min=hits,
    )


# ---------------------------------------------------------------------------
# GET /{domain}/top-pages -- top pages by visits
# ---------------------------------------------------------------------------

@router.get("/{domain}/top-pages", response_model=TopPagesResponse)
async def get_top_pages(
    domain: str,
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _validate_domain(domain)
    log_path = _find_access_log(domain)
    if log_path is None:
        return TopPagesResponse(domain=domain, top_pages=[], total=0)

    data = await _run_goaccess_json(log_path)
    requests_block = data.get("requests", {}) if isinstance(data, dict) else {}
    raw_items = requests_block.get("data", []) if isinstance(requests_block, dict) else []

    pages: list[PageEntry] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict):
            continue
        pages.append(
            PageEntry(
                path=str(item.get("data", "")),
                hits=int((item.get("hits") or {}).get("count", 0) or 0),
                visitors=int((item.get("visitors") or {}).get("count", 0) or 0),
                bandwidth=int((item.get("bytes") or {}).get("count", 0) or 0),
            )
        )

    return TopPagesResponse(domain=domain, top_pages=pages, total=len(pages))


# ---------------------------------------------------------------------------
# GET /{domain}/top-countries -- top countries
# ---------------------------------------------------------------------------

@router.get("/{domain}/top-countries", response_model=TopCountriesResponse)
async def get_top_countries(
    domain: str,
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _validate_domain(domain)
    log_path = _find_access_log(domain)
    if log_path is None:
        return TopCountriesResponse(domain=domain, top_countries=[], total=0)

    data = await _run_goaccess_json(log_path)
    # GoAccess reports geolocation under "geolocation" when --geoip-database is provided.
    geo_block = data.get("geolocation", {}) if isinstance(data, dict) else {}
    raw_items = geo_block.get("data", []) if isinstance(geo_block, dict) else []

    countries: list[CountryEntry] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict):
            continue
        countries.append(
            CountryEntry(
                country=str(item.get("data", "Unknown")),
                hits=int((item.get("hits") or {}).get("count", 0) or 0),
                visitors=int((item.get("visitors") or {}).get("count", 0) or 0),
            )
        )

    return TopCountriesResponse(domain=domain, top_countries=countries, total=len(countries))


# ---------------------------------------------------------------------------
# POST /{domain}/generate -- force regenerate report
# ---------------------------------------------------------------------------

@router.post("/{domain}/generate", response_model=ReportResponse)
async def generate_report(
    domain: str,
    body: ReportGenerate = None,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    period = body.period if body else "daily"
    _validate_domain(domain)

    log_path = _find_access_log(domain)
    if log_path is None:
        raise HTTPException(status_code=404, detail=f"No access log found for {domain}")

    report_file = _REPORT_DIR / domain / f"{period}.html"
    ok = await _run_goaccess_html(log_path, report_file)
    if not ok:
        raise HTTPException(
            status_code=500,
            detail="Report generation failed. Ensure 'goaccess' is installed.",
        )

    return ReportResponse(
        domain=domain,
        period=period,
        report_path=str(report_file),
        report_url=f"/analytics/reports/{domain}/{period}.html",
    )
