"""
GoAccess visitor analytics executor.

Generates HTML reports and JSON stats from Nginx access logs.
All subprocess calls use list args.  shell=True is NEVER used.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.executors._helpers import safe_domain

log = logging.getLogger("hosthive.agent.analytics")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACCESS_LOG_DIR = Path("/var/log/nginx")
_REPORT_DIR = Path("/opt/hosthive/reports")
_GOACCESS_BIN = "goaccess"

# Strict validation for period parameter
_VALID_PERIODS = frozenset({"daily", "weekly", "monthly", "1d", "7d", "30d", "90d", "365d"})
_PERIOD_RE = re.compile(r"^\d{1,3}d$")


def _validate_period(period: str) -> str:
    p = period.strip().lower()
    if p in _VALID_PERIODS or _PERIOD_RE.match(p):
        return p
    raise ValueError(f"Invalid period: {period!r}. Use 'daily', 'weekly', 'monthly', or '<N>d'.")


def _access_log_path(domain: str) -> str:
    """Return the path to the Nginx access log for a domain."""
    return str(_ACCESS_LOG_DIR / f"{domain}.access.log")


def _report_output_dir(domain: str) -> Path:
    """Return and ensure the report output directory for a domain."""
    d = _REPORT_DIR / domain
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# GoAccess report generation
# ---------------------------------------------------------------------------

async def generate_visitor_report(domain: str, period: str = "daily") -> Dict[str, Any]:
    """Generate a GoAccess HTML report for a domain.

    Parses the Nginx access log and outputs an HTML report to
    /opt/hosthive/reports/{domain}/index.html
    """
    domain = safe_domain(domain)
    period = _validate_period(period)

    log_file = _access_log_path(domain)
    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Access log not found: {log_file}")

    output_dir = _report_output_dir(domain)
    output_file = str(output_dir / "index.html")

    cmd: List[str] = [
        _GOACCESS_BIN,
        log_file,
        "--log-format=COMBINED",
        f"--output={output_file}",
        "--no-global-config",
        "--anonymize-ip",
    ]

    # Add date filter based on period
    if period in ("daily", "1d"):
        cmd.append("--keep-last=1")
    elif period in ("weekly", "7d"):
        cmd.append("--keep-last=7")
    elif period in ("monthly", "30d"):
        cmd.append("--keep-last=30")
    elif period == "90d":
        cmd.append("--keep-last=90")
    elif period == "365d":
        cmd.append("--keep-last=365")

    import asyncio
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120),
    )

    if r.returncode != 0:
        raise RuntimeError(f"GoAccess report generation failed: {r.stderr}")

    log.info("Generated visitor report for %s (period=%s)", domain, period)
    return {
        "domain": domain,
        "period": period,
        "report_path": output_file,
        "report_url": f"/reports/{domain}/index.html",
    }


async def get_visitor_stats(domain: str, period: str = "7d") -> Dict[str, Any]:
    """Get parsed visitor stats as structured JSON data.

    Uses GoAccess JSON output mode, then parses into a clean structure.
    """
    domain = safe_domain(domain)
    period = _validate_period(period)

    log_file = _access_log_path(domain)
    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Access log not found: {log_file}")

    output_dir = _report_output_dir(domain)
    json_file = str(output_dir / "stats.json")

    cmd: List[str] = [
        _GOACCESS_BIN,
        log_file,
        "--log-format=COMBINED",
        f"--output={json_file}",
        "--no-global-config",
        "--anonymize-ip",
    ]

    if period in ("daily", "1d"):
        cmd.append("--keep-last=1")
    elif period in ("weekly", "7d"):
        cmd.append("--keep-last=7")
    elif period in ("monthly", "30d"):
        cmd.append("--keep-last=30")

    import asyncio
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120),
    )

    if r.returncode != 0:
        raise RuntimeError(f"GoAccess stats generation failed: {r.stderr}")

    # Parse JSON output
    try:
        with open(json_file, "r") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        raise RuntimeError(f"Failed to parse GoAccess output: {exc}") from exc

    # Extract key metrics
    general = raw_data.get("general", {})
    stats = {
        "domain": domain,
        "period": period,
        "total_requests": general.get("total_requests", 0),
        "unique_visitors": general.get("unique_visitors", 0),
        "bandwidth_bytes": general.get("bandwidth", 0),
        "failed_requests": general.get("failed_requests", 0),
        "generation_time": general.get("generation_time", 0),
        "log_size": general.get("log_size", 0),
    }

    return stats


async def get_realtime_visitors(domain: str) -> Dict[str, Any]:
    """Get approximate count of current active visitors from the access log.

    Counts unique IPs from the last 5 minutes of log entries.
    """
    domain = safe_domain(domain)
    log_file = _access_log_path(domain)

    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Access log not found: {log_file}")

    import asyncio
    loop = asyncio.get_running_loop()

    def _count_recent_visitors() -> Dict[str, Any]:
        """Parse the tail of the access log for recent unique IPs."""
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        unique_ips: set[str] = set()
        total_hits = 0

        # Read last 10000 lines efficiently
        result = subprocess.run(
            ["tail", "-n", "10000", log_file],
            capture_output=True, text=True, timeout=10,
        )

        if result.returncode != 0:
            return {"active_visitors": 0, "hits_last_5min": 0}

        # Parse combined log format: IP - - [datetime] ...
        ip_pattern = re.compile(r'^(\S+)\s')
        time_pattern = re.compile(r'\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})')

        for line in result.stdout.splitlines():
            ip_match = ip_pattern.match(line)
            time_match = time_pattern.search(line)
            if ip_match and time_match:
                try:
                    log_time = datetime.strptime(
                        time_match.group(1), "%d/%b/%Y:%H:%M:%S",
                    )
                    if log_time >= cutoff:
                        unique_ips.add(ip_match.group(1))
                        total_hits += 1
                except ValueError:
                    continue

        return {
            "active_visitors": len(unique_ips),
            "hits_last_5min": total_hits,
        }

    data = await loop.run_in_executor(None, _count_recent_visitors)
    data["domain"] = domain
    return data


async def get_top_pages(domain: str, limit: int = 20) -> Dict[str, Any]:
    """Get top pages by number of requests."""
    domain = safe_domain(domain)
    log_file = _access_log_path(domain)

    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Access log not found: {log_file}")

    output_dir = _report_output_dir(domain)
    json_file = str(output_dir / "pages.json")

    cmd: List[str] = [
        _GOACCESS_BIN,
        log_file,
        "--log-format=COMBINED",
        f"--output={json_file}",
        "--no-global-config",
        "--anonymize-ip",
    ]

    import asyncio
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120),
    )

    if r.returncode != 0:
        raise RuntimeError(f"GoAccess failed: {r.stderr}")

    try:
        with open(json_file, "r") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        raise RuntimeError(f"Failed to parse GoAccess output: {exc}") from exc

    requests_data = raw_data.get("requests", {}).get("data", [])
    pages = []
    for entry in requests_data[:limit]:
        pages.append({
            "path": entry.get("data", ""),
            "hits": entry.get("hits", {}).get("count", 0),
            "visitors": entry.get("visitors", {}).get("count", 0),
            "bandwidth": entry.get("bytes", {}).get("count", 0),
        })

    return {
        "domain": domain,
        "top_pages": pages,
        "total": len(pages),
    }


async def get_top_countries(domain: str, limit: int = 20) -> Dict[str, Any]:
    """Get top countries by visitor count."""
    domain = safe_domain(domain)
    log_file = _access_log_path(domain)

    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Access log not found: {log_file}")

    output_dir = _report_output_dir(domain)
    json_file = str(output_dir / "geo.json")

    cmd: List[str] = [
        _GOACCESS_BIN,
        log_file,
        "--log-format=COMBINED",
        f"--output={json_file}",
        "--no-global-config",
        "--anonymize-ip",
        "--geoip-database=/usr/share/GeoIP/GeoLite2-Country.mmdb",
    ]

    import asyncio
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120),
    )

    if r.returncode != 0:
        raise RuntimeError(f"GoAccess failed: {r.stderr}")

    try:
        with open(json_file, "r") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        raise RuntimeError(f"Failed to parse GoAccess output: {exc}") from exc

    geo_data = raw_data.get("geolocation", {}).get("data", [])
    countries = []
    for entry in geo_data[:limit]:
        countries.append({
            "country": entry.get("data", ""),
            "hits": entry.get("hits", {}).get("count", 0),
            "visitors": entry.get("visitors", {}).get("count", 0),
        })

    return {
        "domain": domain,
        "top_countries": countries,
        "total": len(countries),
    }
