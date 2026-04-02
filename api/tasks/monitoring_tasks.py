"""HostHive smart monitoring Celery tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.monitoring")


# ---------------------------------------------------------------------------
# Health checks -- every 60 seconds
# ---------------------------------------------------------------------------

@app.task(
    name="api.tasks.monitoring_tasks.run_health_checks",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def run_health_checks(self) -> dict:
    """Run health checks for all monitored services and persist results.

    Uses synchronous wrappers around the async check functions because
    Celery tasks run in a sync context.
    """
    import asyncio

    from api.models.monitoring import HealthCheck, HealthStatus, MonitoringIncident
    from api.services.monitoring import MonitoringService, HealthCheckResult

    logger.info("Running periodic health checks")

    # Run async health checks from sync context
    loop = asyncio.new_event_loop()
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from api.core.database import engine, async_session_factory

        async def _run():
            async with async_session_factory() as session:
                svc = MonitoringService(session)
                results = await svc.run_health_checks()

                for r in results:
                    hc = HealthCheck(
                        service_name=r.service_name,
                        status=r.status,
                        response_time_ms=r.response_time_ms,
                        error_message=r.error_message,
                    )
                    session.add(hc)

                # Check for consecutive failures and auto-restart
                from api.core.agent_client import AgentClient
                agent = AgentClient()
                try:
                    for r in results:
                        if not r.is_up:
                            failures = await svc.get_consecutive_failures(r.service_name)
                            # Add 1 for the current failure (not yet persisted when we check)
                            svc._agent = agent
                            await svc.auto_restart_if_needed(
                                r.service_name, failures + 1,
                            )
                finally:
                    await agent.close()

                await session.commit()
                return results

        results = loop.run_until_complete(_run())
    finally:
        loop.close()

    summary = {r.service_name: r.status.value for r in results}
    down = [name for name, st in summary.items() if st == "down"]
    if down:
        logger.warning("Services DOWN: %s", ", ".join(down))
    else:
        logger.info("All services healthy")

    return {"checks": summary, "down_services": down}


# ---------------------------------------------------------------------------
# Anomaly detection -- every 5 minutes
# ---------------------------------------------------------------------------

@app.task(
    name="api.tasks.monitoring_tasks.check_anomalies",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def check_anomalies(self) -> dict:
    """Detect statistical anomalies in server metrics and create alerts."""
    import asyncio

    from api.models.monitoring import AnomalyAlert
    from api.services.monitoring import MonitoringService

    logger.info("Checking for metric anomalies")

    loop = asyncio.new_event_loop()
    try:
        from api.core.database import async_session_factory

        async def _run():
            async with async_session_factory() as session:
                svc = MonitoringService(session)
                anomalies = await svc.check_anomalies()

                for a in anomalies:
                    alert = AnomalyAlert(
                        metric_name=a.metric_name,
                        current_value=a.current_value,
                        baseline_mean=a.baseline_mean,
                        baseline_stddev=a.baseline_stddev,
                        severity=a.severity,
                    )
                    session.add(alert)

                await session.commit()
                return anomalies

        anomalies = loop.run_until_complete(_run())
    finally:
        loop.close()

    if anomalies:
        logger.warning(
            "Detected %d anomalies: %s",
            len(anomalies),
            ", ".join(f"{a.metric_name}={a.current_value}" for a in anomalies),
        )
    else:
        logger.info("No anomalies detected")

    return {"anomaly_count": len(anomalies)}


# ---------------------------------------------------------------------------
# Disk prediction -- every hour
# ---------------------------------------------------------------------------

@app.task(
    name="api.tasks.monitoring_tasks.update_disk_prediction",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def update_disk_prediction(self) -> dict:
    """Compute disk-full prediction and log if critical."""
    import asyncio

    from api.services.monitoring import MonitoringService

    logger.info("Updating disk prediction")

    loop = asyncio.new_event_loop()
    try:
        from api.core.database import async_session_factory

        async def _run():
            async with async_session_factory() as session:
                svc = MonitoringService(session)
                return await svc.predict_disk_full()

        prediction = loop.run_until_complete(_run())
    finally:
        loop.close()

    days = prediction.get("days_until_full")
    if days is not None and days < 7:
        logger.warning(
            "DISK WARNING: predicted full in %.1f days (%.1f%% used, trend %.4f GB/day)",
            days,
            prediction["current_usage_percent"],
            prediction["trend_gb_per_day"],
        )
    else:
        logger.info("Disk prediction: %s", prediction)

    return prediction


# ---------------------------------------------------------------------------
# Domain bandwidth aggregation -- every hour
# ---------------------------------------------------------------------------

@app.task(
    name="api.tasks.monitoring_tasks.aggregate_domain_bandwidth",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def aggregate_domain_bandwidth(self) -> dict:
    """Parse nginx access logs and aggregate bandwidth per domain.

    This is a stub that will be expanded once the nginx log format is
    finalized.  For now it reads the agent's bandwidth endpoint.
    """
    import asyncio
    from datetime import date

    from api.models.monitoring import DomainBandwidth
    from api.models.domains import Domain

    logger.info("Aggregating domain bandwidth")

    loop = asyncio.new_event_loop()
    try:
        from api.core.database import async_session_factory
        from api.core.agent_client import AgentClient

        async def _run():
            async with async_session_factory() as session:
                # Get all active domains
                result = await session.execute(
                    select(Domain).where(Domain.is_active.is_(True))
                )
                domains = result.scalars().all()

                agent = AgentClient()
                today = date.today()
                count = 0

                try:
                    for domain in domains:
                        try:
                            data = await agent._request(
                                "GET",
                                f"/bandwidth/{domain.domain_name}",
                            )
                            # Upsert bandwidth record for today
                            from sqlalchemy import select as sa_select
                            existing = await session.execute(
                                sa_select(DomainBandwidth).where(
                                    DomainBandwidth.domain_id == domain.id,
                                    DomainBandwidth.date == today,
                                )
                            )
                            bw = existing.scalar_one_or_none()
                            if bw is None:
                                bw = DomainBandwidth(
                                    domain_id=domain.id,
                                    date=today,
                                )
                            bw.bytes_in = data.get("bytes_in", 0)
                            bw.bytes_out = data.get("bytes_out", 0)
                            bw.requests_count = data.get("requests_count", 0)
                            session.add(bw)
                            count += 1
                        except Exception as exc:
                            logger.warning(
                                "Failed to get bandwidth for %s: %s",
                                domain.domain_name, exc,
                            )
                finally:
                    await agent.close()

                await session.commit()
                return count

        from sqlalchemy import select
        count = loop.run_until_complete(_run())
    finally:
        loop.close()

    logger.info("Aggregated bandwidth for %d domains", count)
    return {"domains_processed": count}


# ---------------------------------------------------------------------------
# Cleanup -- daily (keep 7 days of health checks)
# ---------------------------------------------------------------------------

@app.task(
    name="api.tasks.monitoring_tasks.cleanup_old_health_checks",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
)
def cleanup_old_health_checks(self) -> dict:
    """Delete health-check records older than 7 days."""
    from api.models.monitoring import AnomalyAlert, HealthCheck

    logger.info("Cleaning up old health checks and acknowledged anomalies")
    cutoff = datetime.utcnow() - timedelta(days=7)

    with get_sync_session() as session:
        hc_result = session.execute(
            delete(HealthCheck).where(HealthCheck.checked_at < cutoff)
        )
        hc_deleted = hc_result.rowcount

        # Also clean up old acknowledged anomalies
        anomaly_cutoff = datetime.utcnow() - timedelta(days=30)
        an_result = session.execute(
            delete(AnomalyAlert).where(
                AnomalyAlert.created_at < anomaly_cutoff,
                AnomalyAlert.is_acknowledged.is_(True),
            )
        )
        an_deleted = an_result.rowcount
        session.commit()

    logger.info(
        "Deleted %d old health checks and %d old anomaly alerts",
        hc_deleted, an_deleted,
    )
    return {"health_checks_deleted": hc_deleted, "anomalies_deleted": an_deleted}
