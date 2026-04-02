"""Prometheus metrics exporter in text exposition format.

Exposes system and application metrics that can be scraped by Prometheus
or displayed in Grafana.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from api.core.config import settings

logger = logging.getLogger("hosthive.prometheus")

_TIMEOUT = 10.0


def _metric_line(name: str, value: Any, help_text: str, metric_type: str = "gauge") -> str:
    """Format a single Prometheus metric with HELP and TYPE comments."""
    return (
        f"# HELP {name} {help_text}\n"
        f"# TYPE {name} {metric_type}\n"
        f"{name} {value}\n"
    )


async def generate_metrics() -> str:
    """Collect and return all HostHive metrics in Prometheus text format.

    Metrics are gathered from the system agent and, where possible, from
    the database.
    """
    lines: List[str] = []
    agent_data = await _fetch_agent_stats()

    # ── System metrics ─────────────────────────────────────────────────
    lines.append(_metric_line(
        "hosthive_cpu_percent",
        agent_data.get("cpu_percent", 0),
        "Current CPU utilisation percentage.",
    ))
    lines.append(_metric_line(
        "hosthive_ram_percent",
        agent_data.get("ram_percent", 0),
        "Current RAM utilisation percentage.",
    ))
    lines.append(_metric_line(
        "hosthive_disk_percent",
        agent_data.get("disk_percent", 0),
        "Current disk utilisation percentage.",
    ))
    lines.append(_metric_line(
        "hosthive_network_in_bytes",
        agent_data.get("network_in_bytes", 0),
        "Total network bytes received since boot.",
        metric_type="counter",
    ))
    lines.append(_metric_line(
        "hosthive_network_out_bytes",
        agent_data.get("network_out_bytes", 0),
        "Total network bytes transmitted since boot.",
        metric_type="counter",
    ))

    # ── Application metrics ────────────────────────────────────────────
    lines.append(_metric_line(
        "hosthive_domains_total",
        agent_data.get("domains_total", 0),
        "Total number of domains managed by the panel.",
    ))
    lines.append(_metric_line(
        "hosthive_users_active",
        agent_data.get("users_active", 0),
        "Number of active (non-suspended) user accounts.",
    ))
    lines.append(_metric_line(
        "hosthive_backup_last_success_timestamp",
        agent_data.get("backup_last_success_ts", 0),
        "Unix timestamp of the last successful backup.",
    ))

    return "\n".join(lines) + "\n"


async def _fetch_agent_stats() -> Dict[str, Any]:
    """Call the HostHive agent to retrieve system statistics.

    Falls back to zeros if the agent is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{settings.AGENT_URL}/api/v1/server/stats",
                headers={"X-Agent-Secret": settings.AGENT_SECRET},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch agent stats for Prometheus: %s", exc)
        return {}
