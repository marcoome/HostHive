"""Celery tasks for multi-server cluster management.

Handles heartbeat collection, health checks, automatic failover,
and periodic load-balancing across web/mail/DB cluster nodes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.cluster")

_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
_FAILOVER_THRESHOLD = 3
_HTTP_TIMEOUT = 10.0


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ping_node(api_url: str, api_key: str) -> tuple[bool, dict]:
    """Ping a node's heartbeat endpoint and return (reachable, stats)."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{api_url.rstrip('/')}/cluster/heartbeat",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return True, resp.json()
            return False, {}
    except Exception as exc:
        logger.debug("Ping failed for %s: %s", api_url, exc)
        return False, {}


async def _collect_stats_from_node(api_url: str, api_key: str) -> tuple[bool, dict]:
    """Request detailed stats from a node."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{api_url.rstrip('/')}/server/stats",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                return True, resp.json()
            return False, {}
    except Exception as exc:
        logger.debug("Stats collection failed for %s: %s", api_url, exc)
        return False, {}


# =========================================================================
# Heartbeat -- every 30 seconds
# =========================================================================


@app.task(
    name="api.tasks.cluster_tasks.cluster_heartbeat",
    bind=True,
    max_retries=0,
)
def cluster_heartbeat(self) -> dict:
    """Periodic task: collect stats from all active cluster nodes.

    Runs every 30 seconds. Contacts each node, updates metrics in DB.
    """
    from api.core.config import settings
    from api.core.encryption import decrypt_value
    from api.models.cluster import ClusterNode

    logger.info("Starting cluster heartbeat collection")

    with get_sync_session() as session:
        nodes = session.execute(
            select(ClusterNode).where(ClusterNode.is_active.is_(True))
        ).scalars().all()

        if not nodes:
            logger.debug("No active cluster nodes")
            return {"status": "skipped", "reason": "no_active_nodes"}

        reachable = 0
        unreachable = 0

        for node in nodes:
            try:
                plain_key = decrypt_value(node.api_key, settings.SECRET_KEY)
            except Exception:
                plain_key = node.api_key

            ok, stats = _run_async(_collect_stats_from_node(node.api_url, plain_key))

            if ok:
                node.cpu_usage = stats.get("cpu_usage", node.cpu_usage)
                node.ram_usage = stats.get("ram_usage", node.ram_usage)
                node.disk_usage = stats.get("disk_usage", node.disk_usage)
                node.current_load = stats.get("load_average", node.current_load)
                if stats.get("cpu_cores"):
                    node.cpu_cores = stats["cpu_cores"]
                if stats.get("ram_mb"):
                    node.ram_mb = stats["ram_mb"]
                if stats.get("disk_gb"):
                    node.disk_gb = stats["disk_gb"]
                node.last_heartbeat = datetime.now(timezone.utc)
                node.failed_checks = 0
                reachable += 1
            else:
                node.failed_checks += 1
                unreachable += 1
                logger.warning(
                    "Heartbeat failed for node %s (%s), consecutive failures: %d",
                    node.hostname, node.ip_address, node.failed_checks,
                )

        session.commit()

    logger.info(
        "Cluster heartbeat complete: %d reachable, %d unreachable",
        reachable, unreachable,
    )
    return {
        "status": "collected",
        "reachable": reachable,
        "unreachable": unreachable,
    }


# =========================================================================
# Health check -- every 5 minutes
# =========================================================================


@app.task(
    name="api.tasks.cluster_tasks.cluster_health_check",
    bind=True,
    max_retries=0,
)
def cluster_health_check(self) -> dict:
    """Periodic task: verify all nodes responding, handle failover.

    Runs every 5 minutes. If a primary node has failed health checks
    N times consecutively, triggers failover to a slave node.
    """
    from api.core.config import settings
    from api.core.encryption import decrypt_value
    from api.models.cluster import ClusterAssignment, ClusterNode

    logger.info("Starting cluster health check")

    with get_sync_session() as session:
        nodes = session.execute(
            select(ClusterNode).where(ClusterNode.is_active.is_(True))
        ).scalars().all()

        if not nodes:
            return {"status": "skipped", "reason": "no_active_nodes"}

        healthy = 0
        unhealthy = 0
        failovers = 0

        for node in nodes:
            try:
                plain_key = decrypt_value(node.api_key, settings.SECRET_KEY)
            except Exception:
                plain_key = node.api_key

            ok, _ = _run_async(_ping_node(node.api_url, plain_key))

            if ok:
                node.failed_checks = 0
                node.last_heartbeat = datetime.now(timezone.utc)
                healthy += 1
            else:
                node.failed_checks += 1
                unhealthy += 1

                logger.warning(
                    "Health check failed for node %s (failures: %d/%d)",
                    node.hostname, node.failed_checks, _FAILOVER_THRESHOLD,
                )

                # Failover: if primary node fails 3 consecutive checks
                if node.failed_checks >= _FAILOVER_THRESHOLD:
                    logger.error(
                        "Node %s exceeded failure threshold (%d), initiating failover",
                        node.hostname, _FAILOVER_THRESHOLD,
                    )
                    failovers += _perform_failover(session, node)

        session.commit()

    logger.info(
        "Cluster health check complete: %d healthy, %d unhealthy, %d failovers",
        healthy, unhealthy, failovers,
    )
    return {
        "status": "checked",
        "healthy": healthy,
        "unhealthy": unhealthy,
        "failovers": failovers,
    }


def _perform_failover(session, failed_node) -> int:
    """Move resources from a failed node to the best available slave.

    Returns the number of assignments migrated.
    """
    from api.models.cluster import ClusterAssignment, ClusterNode

    # Mark the failed node as inactive
    failed_node.is_active = False

    # Find assignments on the failed node
    assignments = session.execute(
        select(ClusterAssignment).where(
            ClusterAssignment.node_id == failed_node.id,
        )
    ).scalars().all()

    if not assignments:
        logger.info("No assignments on failed node %s, nothing to migrate", failed_node.hostname)
        return 0

    # Find the best available node (active, lowest load, compatible type)
    candidates = session.execute(
        select(ClusterNode).where(
            ClusterNode.id != failed_node.id,
            ClusterNode.is_active.is_(True),
            ClusterNode.failed_checks < _FAILOVER_THRESHOLD,
            (ClusterNode.node_type == failed_node.node_type)
            | (ClusterNode.node_type == "all")
            | (failed_node.node_type == "all"),
        ).order_by(ClusterNode.current_load.asc())
    ).scalars().all()

    if not candidates:
        logger.error(
            "CRITICAL: No available nodes for failover from %s! "
            "%d assignments left stranded.",
            failed_node.hostname, len(assignments),
        )
        return 0

    migrated = 0
    for assignment in assignments:
        # Round-robin across candidates to spread load
        target = candidates[migrated % len(candidates)]
        old_node_id = assignment.node_id
        assignment.node_id = target.id
        assignment.is_primary = True
        migrated += 1

        logger.info(
            "Failover: %s %s moved from %s to %s",
            assignment.resource_type, assignment.resource_id,
            failed_node.hostname, target.hostname,
        )

    logger.warning(
        "Failover complete for node %s: %d assignments migrated to %d candidates",
        failed_node.hostname, migrated, len(candidates),
    )
    return migrated


# =========================================================================
# Auto-balance -- daily
# =========================================================================


@app.task(
    name="api.tasks.cluster_tasks.cluster_auto_balance",
    bind=True,
    max_retries=0,
)
def cluster_auto_balance(self) -> dict:
    """Periodic task: redistribute resources if load imbalance detected.

    Runs daily. Checks assignment counts and node metrics, then migrates
    resources from overloaded to underloaded nodes.
    """
    from api.models.cluster import ClusterAssignment, ClusterNode

    logger.info("Starting cluster auto-balance")

    with get_sync_session() as session:
        nodes = session.execute(
            select(ClusterNode).where(ClusterNode.is_active.is_(True))
        ).scalars().all()

        if len(nodes) < 2:
            return {"status": "skipped", "reason": "insufficient_nodes"}

        # Build per-node assignment counts
        node_counts: dict = {}
        for node in nodes:
            count = session.execute(
                select(func.count()).select_from(ClusterAssignment).where(
                    ClusterAssignment.node_id == node.id,
                )
            ).scalar() or 0
            node_counts[node.id] = {"node": node, "count": count}

        total = sum(v["count"] for v in node_counts.values())
        if total == 0:
            return {"status": "skipped", "reason": "no_assignments"}

        avg = total / len(nodes)
        threshold = max(avg * 1.5, avg + 2)

        migrations = 0

        # Find overloaded and underloaded nodes
        overloaded = [
            v for v in node_counts.values()
            if v["count"] > threshold
        ]
        underloaded = sorted(
            [v for v in node_counts.values() if v["count"] < avg],
            key=lambda v: v["count"],
        )

        for source_info in overloaded:
            source = source_info["node"]
            excess = int(source_info["count"] - avg)
            if excess <= 0 or not underloaded:
                continue

            assignments = session.execute(
                select(ClusterAssignment)
                .where(ClusterAssignment.node_id == source.id)
                .order_by(ClusterAssignment.is_primary.asc())
                .limit(excess)
            ).scalars().all()

            for assignment in assignments:
                if not underloaded:
                    break

                target_info = underloaded[0]
                target = target_info["node"]

                # Type compatibility check
                if source.node_type != "all" and target.node_type != "all":
                    if source.node_type != target.node_type:
                        continue

                assignment.node_id = target.id
                source_info["count"] -= 1
                target_info["count"] += 1
                migrations += 1

                if target_info["count"] >= avg:
                    underloaded.pop(0)

        session.commit()

    logger.info("Cluster auto-balance complete: %d migration(s)", migrations)
    return {
        "status": "balanced",
        "migrations": migrations,
        "total_nodes": len(nodes),
    }
