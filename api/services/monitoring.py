"""Advanced monitoring service -- anomaly detection, health checks, predictions."""

from __future__ import annotations

import asyncio
import logging
import math
import socket
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.agent_client import AgentClient
from api.models.domains import Domain
from api.models.monitoring import (
    AnomalyAlert,
    AnomalySeverity,
    DomainBandwidth,
    HealthCheck,
    HealthStatus,
    MonitoringIncident,
)
from api.models.server_stats import ServerStat

logger = logging.getLogger("hosthive.monitoring")

_HEALTH_CHECK_TIMEOUT = 5.0

# Services that may be auto-restarted (whitelist for safety).
_RESTARTABLE_SERVICES = frozenset({
    "nginx", "mysql", "mariadb", "postgresql",
    "exim4", "dovecot", "bind9", "redis-server",
    "proftpd", "php-fpm",
})

_CONSECUTIVE_FAILURES_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Data classes for intermediate results
# ---------------------------------------------------------------------------

@dataclass
class HealthCheckResult:
    service_name: str
    is_up: bool
    response_time_ms: float = 0.0
    error_message: Optional[str] = None

    @property
    def status(self) -> HealthStatus:
        if not self.is_up:
            return HealthStatus.DOWN
        if self.response_time_ms > 2000:
            return HealthStatus.DEGRADED
        return HealthStatus.UP


@dataclass
class Anomaly:
    metric_name: str
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    sigma_distance: float = 0.0

    @property
    def severity(self) -> AnomalySeverity:
        if self.sigma_distance >= 4:
            return AnomalySeverity.CRITICAL
        if self.sigma_distance >= 3:
            return AnomalySeverity.HIGH
        if self.sigma_distance >= 2.5:
            return AnomalySeverity.MEDIUM
        return AnomalySeverity.LOW


# ---------------------------------------------------------------------------
# Low-level health-check functions (all with timeout)
# ---------------------------------------------------------------------------

async def http_check(url: str) -> Tuple[bool, float]:
    """HTTP GET check. Returns (is_up, response_time_ms)."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT, verify=False) as client:
            resp = await client.get(url)
        elapsed = (time.monotonic() - start) * 1000
        return resp.status_code < 500, elapsed
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        return False, elapsed


async def tcp_check(host: str, port: int) -> Tuple[bool, float]:
    """TCP connect check. Returns (is_up, response_time_ms)."""
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_HEALTH_CHECK_TIMEOUT,
        )
        elapsed = (time.monotonic() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return True, elapsed
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        return False, elapsed


async def smtp_check(host: str, port: int) -> Tuple[bool, float]:
    """SMTP EHLO check. Returns (is_up, response_time_ms)."""
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_HEALTH_CHECK_TIMEOUT,
        )
        banner = await asyncio.wait_for(reader.readline(), timeout=_HEALTH_CHECK_TIMEOUT)
        writer.write(b"EHLO hosthive\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.readline(), timeout=_HEALTH_CHECK_TIMEOUT)
        elapsed = (time.monotonic() - start) * 1000
        writer.write(b"QUIT\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return response.startswith(b"250"), elapsed
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        return False, elapsed


async def dns_check(host: str) -> Tuple[bool, float]:
    """DNS query check via TCP to port 53. Returns (is_up, response_time_ms)."""
    # Simple TCP connectivity check to DNS port
    return await tcp_check(host, 53)


# ---------------------------------------------------------------------------
# Main MonitoringService
# ---------------------------------------------------------------------------

class MonitoringService:
    """Stateless monitoring service -- instantiate per request or task."""

    def __init__(
        self,
        db: AsyncSession,
        agent: Optional[AgentClient] = None,
    ) -> None:
        self._db = db
        self._agent = agent

    # ------------------------------------------------------------------
    # Anomaly detection (statistical, no AI)
    # ------------------------------------------------------------------

    async def check_anomalies(self) -> List[Anomaly]:
        """Compare current metrics against 7-day baseline (mean + 2*sigma)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        # Fetch baseline stats from last 7 days
        result = await self._db.execute(
            select(
                func.avg(ServerStat.cpu_percent).label("cpu_mean"),
                func.stddev(ServerStat.cpu_percent).label("cpu_std"),
                func.avg(ServerStat.memory_percent).label("mem_mean"),
                func.stddev(ServerStat.memory_percent).label("mem_std"),
                func.avg(ServerStat.load_avg_1).label("load_mean"),
                func.stddev(ServerStat.load_avg_1).label("load_std"),
                func.avg(ServerStat.disk_percent).label("disk_mean"),
                func.stddev(ServerStat.disk_percent).label("disk_std"),
            ).where(ServerStat.created_at >= cutoff)
        )
        row = result.one_or_none()
        if row is None:
            return []

        # Get latest stats
        latest_result = await self._db.execute(
            select(ServerStat).order_by(ServerStat.created_at.desc()).limit(1)
        )
        latest = latest_result.scalar_one_or_none()
        if latest is None:
            return []

        anomalies: List[Anomaly] = []
        metrics = [
            ("cpu_percent", latest.cpu_percent, row.cpu_mean, row.cpu_std),
            ("memory_percent", latest.memory_percent, row.mem_mean, row.mem_std),
            ("load_avg_1", latest.load_avg_1, row.load_mean, row.load_std),
            ("disk_percent", latest.disk_percent, row.disk_mean, row.disk_std),
        ]

        for metric_name, current, mean, stddev in metrics:
            if mean is None or stddev is None or stddev == 0:
                continue
            sigma_distance = abs(current - mean) / stddev
            if sigma_distance >= 2:
                anomalies.append(Anomaly(
                    metric_name=metric_name,
                    current_value=current,
                    baseline_mean=round(mean, 2),
                    baseline_stddev=round(stddev, 2),
                    sigma_distance=round(sigma_distance, 2),
                ))

        return anomalies

    # ------------------------------------------------------------------
    # Predictive disk usage (linear regression)
    # ------------------------------------------------------------------

    async def predict_disk_full(self) -> Dict[str, Any]:
        """Linear regression on 7 days of disk usage to predict when disk is full."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = await self._db.execute(
            select(ServerStat.disk_used_gb, ServerStat.disk_total_gb, ServerStat.created_at)
            .where(ServerStat.created_at >= cutoff)
            .order_by(ServerStat.created_at.asc())
        )
        rows = result.all()

        if len(rows) < 2:
            return {
                "days_until_full": None,
                "current_usage_percent": 0.0,
                "current_used_gb": 0.0,
                "total_gb": 0.0,
                "trend_gb_per_day": 0.0,
            }

        # Use hours since first sample as X, disk_used_gb as Y
        t0 = rows[0].created_at
        xs = [(r.created_at - t0).total_seconds() / 3600 for r in rows]
        ys = [r.disk_used_gb for r in rows]

        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_xx = sum(x * x for x in xs)

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            slope = 0.0
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denom

        # slope is GB per hour, convert to GB per day
        trend_gb_per_day = slope * 24

        latest = rows[-1]
        current_used = latest.disk_used_gb
        total_gb = latest.disk_total_gb
        remaining = total_gb - current_used

        days_until_full = None
        if trend_gb_per_day > 0 and remaining > 0:
            days_until_full = round(remaining / trend_gb_per_day, 1)

        current_pct = (current_used / total_gb * 100) if total_gb > 0 else 0.0

        return {
            "days_until_full": days_until_full,
            "current_usage_percent": round(current_pct, 1),
            "current_used_gb": round(current_used, 2),
            "total_gb": round(total_gb, 2),
            "trend_gb_per_day": round(trend_gb_per_day, 4),
        }

    # ------------------------------------------------------------------
    # Service health checks
    # ------------------------------------------------------------------

    async def run_health_checks(self) -> List[HealthCheckResult]:
        """Run health checks for all monitored services concurrently."""
        checks = {
            "nginx": http_check("http://127.0.0.1"),
            "mysql": tcp_check("127.0.0.1", 3306),
            "postgresql": tcp_check("127.0.0.1", 5432),
            "exim4": smtp_check("127.0.0.1", 25),
            "dovecot": tcp_check("127.0.0.1", 993),
            "bind9": dns_check("127.0.0.1"),
            "redis": tcp_check("127.0.0.1", 6379),
            "proftpd": tcp_check("127.0.0.1", 21),
        }

        results: List[HealthCheckResult] = []
        tasks = {name: asyncio.create_task(coro) for name, coro in checks.items()}

        for name, task in tasks.items():
            try:
                is_up, response_time = await task
                results.append(HealthCheckResult(
                    service_name=name,
                    is_up=is_up,
                    response_time_ms=round(response_time, 2),
                ))
            except Exception as exc:
                results.append(HealthCheckResult(
                    service_name=name,
                    is_up=False,
                    error_message=str(exc),
                ))

        return results

    # ------------------------------------------------------------------
    # Auto-restart logic
    # ------------------------------------------------------------------

    async def auto_restart_if_needed(
        self,
        service: str,
        consecutive_failures: int,
    ) -> Optional[MonitoringIncident]:
        """Auto-restart a service after N consecutive failures. Escalate if restart fails."""
        if service not in _RESTARTABLE_SERVICES:
            logger.warning("Service %s is not in the auto-restart whitelist", service)
            return None

        if consecutive_failures < _CONSECUTIVE_FAILURES_THRESHOLD:
            return None

        if self._agent is None:
            logger.error("No agent client available for auto-restart of %s", service)
            return None

        # Look for an open incident
        result = await self._db.execute(
            select(MonitoringIncident)
            .where(
                MonitoringIncident.service_name == service,
                MonitoringIncident.resolved_at.is_(None),
            )
            .order_by(MonitoringIncident.started_at.desc())
            .limit(1)
        )
        incident = result.scalar_one_or_none()

        if incident is None:
            incident = MonitoringIncident(
                service_name=service,
                description=f"Service {service} failed {consecutive_failures} consecutive health checks.",
            )
            self._db.add(incident)
            await self._db.flush()

        # Attempt restart
        try:
            await self._agent.service_action(service, "restart")
            incident.auto_restarted = True
            incident.restart_count += 1
            logger.info("Auto-restarted service %s (attempt %d)", service, incident.restart_count)
        except Exception as exc:
            logger.error("Failed to auto-restart service %s: %s", service, exc)
            incident.escalated = True
            incident.description = (
                f"{incident.description or ''} "
                f"Auto-restart failed: {exc}"
            ).strip()

        # If restarted too many times, escalate
        if incident.restart_count >= 3:
            incident.escalated = True
            incident.description = (
                f"{incident.description or ''} "
                f"Escalated after {incident.restart_count} restart attempts."
            ).strip()

        self._db.add(incident)
        await self._db.flush()
        return incident

    # ------------------------------------------------------------------
    # Domain bandwidth tracking
    # ------------------------------------------------------------------

    async def get_domain_bandwidth(
        self,
        domain: str,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Return daily bandwidth for a domain over the last N days."""
        cutoff = date.today() - timedelta(days=days)

        result = await self._db.execute(
            select(DomainBandwidth)
            .join(Domain, Domain.id == DomainBandwidth.domain_id)
            .where(
                Domain.domain_name == domain,
                DomainBandwidth.date >= cutoff,
            )
            .order_by(DomainBandwidth.date.asc())
        )
        rows = result.scalars().all()

        return [
            {
                "date": r.date.isoformat(),
                "bytes_in": r.bytes_in,
                "bytes_out": r.bytes_out,
                "requests_count": r.requests_count,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Traffic heatmap
    # ------------------------------------------------------------------

    async def get_traffic_heatmap(self, days: int = 7) -> Dict[str, Any]:
        """Aggregate request counts into a 7x24 heatmap from DomainBandwidth.

        Since DomainBandwidth is daily, this returns a simplified per-day
        view with requests spread evenly across hours.  A more precise
        implementation would parse nginx logs directly.
        """
        cutoff = date.today() - timedelta(days=days)

        result = await self._db.execute(
            select(
                DomainBandwidth.date,
                func.sum(DomainBandwidth.requests_count).label("total"),
            )
            .where(DomainBandwidth.date >= cutoff)
            .group_by(DomainBandwidth.date)
            .order_by(DomainBandwidth.date.desc())
        )
        rows = result.all()

        labels_days: List[str] = []
        data: List[List[int]] = []

        for row in rows:
            labels_days.append(row.date.isoformat())
            # Spread total evenly across 24 hours as a baseline representation
            per_hour = row.total // 24 if row.total else 0
            remainder = row.total % 24 if row.total else 0
            hourly = [per_hour] * 24
            # Distribute remainder across peak hours (9-17)
            for i in range(remainder):
                hourly[9 + (i % 9)] += 1
            data.append(hourly)

        return {
            "labels_days": labels_days,
            "labels_hours": list(range(24)),
            "data": data,
        }

    # ------------------------------------------------------------------
    # Consecutive failure counter (from recent health checks)
    # ------------------------------------------------------------------

    async def get_consecutive_failures(self, service_name: str) -> int:
        """Count how many of the most recent checks for a service were failures."""
        result = await self._db.execute(
            select(HealthCheck.status)
            .where(HealthCheck.service_name == service_name)
            .order_by(HealthCheck.checked_at.desc())
            .limit(10)
        )
        statuses = result.scalars().all()

        count = 0
        for s in statuses:
            if s == HealthStatus.DOWN:
                count += 1
            else:
                break
        return count
