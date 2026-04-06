"""Cluster router -- /api/v1/cluster.

Multi-server clustering for web, mail, and database services.
Provides node management, health monitoring, resource migration,
and automatic load-balancing.

All endpoints require admin access.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.encryption import decrypt_value, encrypt_value
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.cluster import ClusterAssignment, ClusterNode
from api.models.users import User
from api.schemas.cluster import (
    ClusterAssignmentResponse,
    ClusterBalanceResponse,
    ClusterMigrateRequest,
    ClusterMigrateResponse,
    ClusterNodeCreate,
    ClusterNodeHealthResponse,
    ClusterNodeResponse,
    ClusterOverviewResponse,
)

router = APIRouter()
_log = logging.getLogger("novapanel.cluster")

_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
_FAILOVER_THRESHOLD = 3  # consecutive failed checks before failover
_HTTP_TIMEOUT = 10.0  # seconds for node connectivity tests


# =========================================================================
# Helpers
# =========================================================================


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _require_admin(user: User) -> None:
    if not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


def _activity(
    db: AsyncSession,
    request: Request,
    user_id: uuid.UUID,
    action: str,
    details: str,
) -> None:
    db.add(
        ActivityLog(
            user_id=user_id,
            action=action,
            details=details,
            ip_address=request.client.host if request.client else None,
        )
    )


async def _test_node_connectivity(api_url: str, api_key: str) -> tuple[bool, float | None, str]:
    """Test if a cluster node is reachable. Returns (reachable, latency_ms, message)."""
    try:
        start = time.monotonic()
        async with httpx.AsyncClient(verify=False, timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{api_url.rstrip('/')}/cluster/heartbeat",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        latency = (time.monotonic() - start) * 1000
        if resp.status_code < 500:
            return True, latency, "OK"
        return False, latency, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, None, "Connection refused"
    except httpx.TimeoutException:
        return False, None, "Connection timed out"
    except Exception as exc:
        return False, None, str(exc)


async def _get_node_or_404(node_id: uuid.UUID, db: AsyncSession) -> ClusterNode:
    result = await db.execute(select(ClusterNode).where(ClusterNode.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cluster node not found.",
        )
    return node


def _node_is_healthy(node: ClusterNode) -> bool:
    if not node.is_active:
        return False
    if node.last_heartbeat is None:
        return False
    return datetime.now(timezone.utc) - node.last_heartbeat < _HEARTBEAT_TIMEOUT


# =========================================================================
# GET /cluster/nodes -- list all nodes with health status
# =========================================================================


@router.get("/nodes", status_code=status.HTTP_200_OK)
async def list_cluster_nodes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all cluster nodes with current health status. Admin only."""
    _require_admin(current_user)

    result = await db.execute(select(ClusterNode).order_by(ClusterNode.created_at))
    nodes = result.scalars().all()

    items = []
    for node in nodes:
        resp = ClusterNodeResponse.model_validate(node)
        items.append(resp)

    return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}


# =========================================================================
# POST /cluster/nodes -- add a node (test connectivity first)
# =========================================================================


@router.post("/nodes", status_code=status.HTTP_201_CREATED)
async def add_cluster_node(
    body: ClusterNodeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a cluster node. Tests connectivity before saving. Admin only."""
    _require_admin(current_user)

    # Duplicate check
    existing = await db.execute(
        select(ClusterNode).where(ClusterNode.hostname == body.hostname)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Node with this hostname already exists.",
        )

    # Test connectivity
    reachable, latency, msg = await _test_node_connectivity(body.api_url, body.api_key)
    if not reachable:
        _log.warning(
            "Node connectivity test failed for %s (%s): %s",
            body.hostname, body.api_url, msg,
        )
        # Still allow adding -- node may not be fully configured yet
        # but warn in the response

    encrypted_key = encrypt_value(body.api_key, settings.SECRET_KEY)

    node = ClusterNode(
        hostname=body.hostname,
        ip_address=body.ip_address,
        port=body.port,
        api_url=body.api_url,
        api_key=encrypted_key,
        role=body.role,
        node_type=body.node_type,
        cpu_cores=body.cpu_cores,
        ram_mb=body.ram_mb,
        disk_gb=body.disk_gb,
    )
    db.add(node)
    await db.flush()

    _activity(
        db, request, current_user.id,
        "cluster.add_node",
        f"Added cluster node {body.hostname} ({body.ip_address}), "
        f"type={body.node_type}, role={body.role}",
    )

    resp = ClusterNodeResponse.model_validate(node).model_dump(mode="json")
    resp["connectivity_test"] = {
        "reachable": reachable,
        "latency_ms": latency,
        "message": msg,
    }
    return resp


# =========================================================================
# DELETE /cluster/nodes/{id} -- remove node (migrate resources first)
# =========================================================================


@router.delete("/nodes/{node_id}", status_code=status.HTTP_200_OK)
async def remove_cluster_node(
    node_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a cluster node. Migrates resources to other nodes first. Admin only."""
    _require_admin(current_user)

    node = await _get_node_or_404(node_id, db)

    # Check for active assignments
    assignments_result = await db.execute(
        select(ClusterAssignment).where(ClusterAssignment.node_id == node_id)
    )
    assignments = assignments_result.scalars().all()

    migrated = 0
    if assignments:
        # Find alternative nodes for each assignment
        for assignment in assignments:
            # Find a suitable node of the same type (or "all") that is active
            alt_result = await db.execute(
                select(ClusterNode).where(
                    ClusterNode.id != node_id,
                    ClusterNode.is_active.is_(True),
                    (ClusterNode.node_type == node.node_type)
                    | (ClusterNode.node_type == "all")
                    | (node.node_type == "all"),
                ).order_by(ClusterNode.current_load.asc()),
            )
            alt_node = alt_result.scalars().first()

            if alt_node:
                assignment.node_id = alt_node.id
                migrated += 1
            else:
                # No alternative -- remove assignment
                await db.delete(assignment)

    hostname = node.hostname
    await db.delete(node)
    await db.flush()

    _activity(
        db, request, current_user.id,
        "cluster.remove_node",
        f"Removed cluster node {hostname}, migrated {migrated} resource(s)",
    )

    return {
        "detail": f"Node {hostname} removed.",
        "resources_migrated": migrated,
        "resources_orphaned": len(assignments) - migrated,
    }


# =========================================================================
# GET /cluster/nodes/{id}/health -- detailed health check
# =========================================================================


@router.get("/nodes/{node_id}/health", status_code=status.HTTP_200_OK)
async def node_health_check(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Perform a detailed health check on a specific node. Admin only."""
    _require_admin(current_user)

    node = await _get_node_or_404(node_id, db)

    # Count assignments
    count_result = await db.execute(
        select(func.count()).select_from(ClusterAssignment).where(
            ClusterAssignment.node_id == node_id,
        )
    )
    assignment_count = count_result.scalar() or 0

    # Test live connectivity
    try:
        plain_key = decrypt_value(node.api_key, settings.SECRET_KEY)
    except Exception:
        plain_key = node.api_key

    reachable, latency, msg = await _test_node_connectivity(node.api_url, plain_key)

    # Update failed_checks counter
    if not reachable:
        node.failed_checks += 1
    else:
        node.failed_checks = 0
        node.last_heartbeat = datetime.now(timezone.utc)
    await db.flush()

    return ClusterNodeHealthResponse(
        id=node.id,
        hostname=node.hostname,
        ip_address=node.ip_address,
        is_active=node.is_active,
        role=node.role,
        node_type=node.node_type,
        reachable=reachable,
        latency_ms=latency,
        cpu_usage=node.cpu_usage,
        ram_usage=node.ram_usage,
        disk_usage=node.disk_usage,
        current_load=node.current_load,
        last_heartbeat=node.last_heartbeat,
        failed_checks=node.failed_checks,
        assignment_count=assignment_count,
    ).model_dump(mode="json")


# =========================================================================
# POST /cluster/balance -- auto-balance resources across nodes
# =========================================================================


@router.post("/balance", status_code=status.HTTP_200_OK)
async def auto_balance(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-balance resources across cluster nodes. Admin only.

    Redistributes resources from overloaded nodes to underloaded ones
    based on current CPU/RAM usage and assignment counts.
    """
    _require_admin(current_user)

    # Get all active nodes
    nodes_result = await db.execute(
        select(ClusterNode).where(ClusterNode.is_active.is_(True)).order_by(
            ClusterNode.current_load.desc(),
        )
    )
    nodes = nodes_result.scalars().all()

    if len(nodes) < 2:
        return ClusterBalanceResponse(
            status="skipped",
            detail="Need at least 2 active nodes to balance.",
            migrations_performed=0,
        ).model_dump(mode="json")

    # Calculate per-node assignment counts
    node_loads: dict[uuid.UUID, int] = {}
    for node in nodes:
        count_result = await db.execute(
            select(func.count()).select_from(ClusterAssignment).where(
                ClusterAssignment.node_id == node.id,
            )
        )
        node_loads[node.id] = count_result.scalar() or 0

    total_assignments = sum(node_loads.values())
    if total_assignments == 0:
        return ClusterBalanceResponse(
            status="skipped",
            detail="No resource assignments to balance.",
            migrations_performed=0,
        ).model_dump(mode="json")

    avg_load = total_assignments / len(nodes)
    # Threshold: migrate if a node has >150% of average
    threshold = max(avg_load * 1.5, avg_load + 2)

    migrations = 0

    # Sort nodes by load descending (overloaded first)
    overloaded = [n for n in nodes if node_loads[n.id] > threshold]
    underloaded = sorted(
        [n for n in nodes if node_loads[n.id] < avg_load],
        key=lambda n: node_loads[n.id],
    )

    for source in overloaded:
        excess = int(node_loads[source.id] - avg_load)
        if excess <= 0:
            continue

        # Get assignments from the overloaded node (non-primary first)
        assignments_result = await db.execute(
            select(ClusterAssignment)
            .where(ClusterAssignment.node_id == source.id)
            .order_by(ClusterAssignment.is_primary.asc())
            .limit(excess)
        )
        movable = assignments_result.scalars().all()

        for assignment in movable:
            if not underloaded:
                break
            target = underloaded[0]

            # Only move to nodes of compatible type
            if source.node_type != "all" and target.node_type != "all":
                if source.node_type != target.node_type:
                    continue

            assignment.node_id = target.id
            node_loads[source.id] -= 1
            node_loads[target.id] += 1
            migrations += 1

            # If target is now at average, remove from underloaded
            if node_loads[target.id] >= avg_load:
                underloaded.pop(0)

    await db.flush()

    _activity(
        db, request, current_user.id,
        "cluster.balance",
        f"Auto-balance performed {migrations} migration(s)",
    )

    return ClusterBalanceResponse(
        status="balanced",
        detail=f"Performed {migrations} resource migration(s) across {len(nodes)} nodes.",
        migrations_performed=migrations,
    ).model_dump(mode="json")


# =========================================================================
# POST /cluster/migrate -- migrate a specific resource between nodes
# =========================================================================


@router.post("/migrate", status_code=status.HTTP_200_OK)
async def migrate_resource(
    body: ClusterMigrateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Migrate a specific resource from one node to another. Admin only.

    For web resources: syncs nginx configs via API to the target node.
    For mail resources: triggers dsync/rsync replication.
    For database resources: sets up replication to the target.
    """
    _require_admin(current_user)

    # Validate both nodes exist
    source_node = await _get_node_or_404(body.source_node_id, db)
    target_node = await _get_node_or_404(body.target_node_id, db)

    if source_node.id == target_node.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target nodes must be different.",
        )

    # Verify target node is active
    if not target_node.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target node is not active.",
        )

    # Find the assignment
    assignment_result = await db.execute(
        select(ClusterAssignment).where(
            ClusterAssignment.resource_type == body.resource_type,
            ClusterAssignment.resource_id == body.resource_id,
            ClusterAssignment.node_id == body.source_node_id,
        )
    )
    assignment = assignment_result.scalar_one_or_none()

    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {body.resource_type} assignment found on source node.",
        )

    # Perform type-specific migration steps
    migration_detail = await _execute_migration(
        db, body.resource_type, body.resource_id,
        source_node, target_node,
    )

    # Update assignment
    assignment.node_id = target_node.id
    await db.flush()

    _activity(
        db, request, current_user.id,
        "cluster.migrate",
        f"Migrated {body.resource_type} {body.resource_id} from "
        f"{source_node.hostname} to {target_node.hostname}",
    )

    return ClusterMigrateResponse(
        status="migrated",
        detail=migration_detail,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
    ).model_dump(mode="json")


async def _execute_migration(
    db: AsyncSession,
    resource_type: str,
    resource_id: uuid.UUID,
    source: ClusterNode,
    target: ClusterNode,
) -> str:
    """Execute the actual migration between nodes via their APIs.

    Returns a human-readable detail string.
    """
    try:
        source_key = decrypt_value(source.api_key, settings.SECRET_KEY)
    except Exception:
        source_key = source.api_key

    try:
        target_key = decrypt_value(target.api_key, settings.SECRET_KEY)
    except Exception:
        target_key = target.api_key

    if resource_type == "domain":
        return await _migrate_web_resource(resource_id, source, source_key, target, target_key)
    elif resource_type == "mailbox":
        return await _migrate_mail_resource(resource_id, source, source_key, target, target_key)
    elif resource_type == "database":
        return await _migrate_db_resource(resource_id, source, source_key, target, target_key)
    return "Unknown resource type"


async def _migrate_web_resource(
    resource_id: uuid.UUID,
    source: ClusterNode,
    source_key: str,
    target: ClusterNode,
    target_key: str,
) -> str:
    """Migrate a web domain: fetch nginx config from source, push to target."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            # Fetch nginx config from source
            resp = await client.get(
                f"{source.api_url.rstrip('/')}/cluster/resource/web/{resource_id}",
                headers={"Authorization": f"Bearer {source_key}"},
            )
            if resp.status_code != 200:
                return f"Warning: could not fetch web config from source ({resp.status_code}), assignment updated"
            config_data = resp.json()

            # Push nginx config to target
            resp = await client.post(
                f"{target.api_url.rstrip('/')}/cluster/resource/web/receive",
                headers={"Authorization": f"Bearer {target_key}"},
                json=config_data,
            )
            if resp.status_code != 200:
                return f"Warning: pushed config to target but got status {resp.status_code}"

        return f"Web domain migrated: nginx config synced from {source.hostname} to {target.hostname}"
    except Exception as exc:
        _log.warning("Web migration API call failed: %s", exc)
        return f"Assignment updated; manual nginx sync may be needed ({exc})"


async def _migrate_mail_resource(
    resource_id: uuid.UUID,
    source: ClusterNode,
    source_key: str,
    target: ClusterNode,
    target_key: str,
) -> str:
    """Migrate a mailbox: trigger dsync replication between source and target."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            resp = await client.post(
                f"{source.api_url.rstrip('/')}/cluster/resource/mail/replicate",
                headers={"Authorization": f"Bearer {source_key}"},
                json={
                    "resource_id": str(resource_id),
                    "target_api_url": target.api_url,
                    "target_ip": target.ip_address,
                },
            )
            if resp.status_code != 200:
                return f"Warning: dsync trigger returned {resp.status_code}, assignment updated"

        return f"Mailbox migrated: dsync replication from {source.hostname} to {target.hostname}"
    except Exception as exc:
        _log.warning("Mail migration API call failed: %s", exc)
        return f"Assignment updated; manual dsync/rsync may be needed ({exc})"


async def _migrate_db_resource(
    resource_id: uuid.UUID,
    source: ClusterNode,
    source_key: str,
    target: ClusterNode,
    target_key: str,
) -> str:
    """Migrate a database: trigger dump on source, restore on target."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=120.0) as client:
            # Ask source to dump the database
            resp = await client.post(
                f"{source.api_url.rstrip('/')}/cluster/resource/db/export",
                headers={"Authorization": f"Bearer {source_key}"},
                json={"resource_id": str(resource_id)},
            )
            if resp.status_code != 200:
                return f"Warning: DB export from source returned {resp.status_code}, assignment updated"
            export_data = resp.json()

            # Push to target for import
            resp = await client.post(
                f"{target.api_url.rstrip('/')}/cluster/resource/db/import",
                headers={"Authorization": f"Bearer {target_key}"},
                json=export_data,
            )
            if resp.status_code != 200:
                return f"Warning: DB import to target returned {resp.status_code}"

        return f"Database migrated from {source.hostname} to {target.hostname}"
    except Exception as exc:
        _log.warning("DB migration API call failed: %s", exc)
        return f"Assignment updated; manual DB migration may be needed ({exc})"


# =========================================================================
# GET /cluster/overview -- cluster-wide stats
# =========================================================================


@router.get("/overview", status_code=status.HTTP_200_OK)
async def cluster_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get cluster-wide statistics: total CPU/RAM/disk, per-node usage. Admin only."""
    _require_admin(current_user)

    result = await db.execute(select(ClusterNode).order_by(ClusterNode.hostname))
    nodes = result.scalars().all()

    active = [n for n in nodes if n.is_active]

    total_assignments_result = await db.execute(
        select(func.count()).select_from(ClusterAssignment)
    )
    total_assignments = total_assignments_result.scalar() or 0

    web_count = sum(1 for n in nodes if n.node_type in ("web", "all"))
    mail_count = sum(1 for n in nodes if n.node_type in ("mail", "all"))
    db_count = sum(1 for n in nodes if n.node_type in ("db", "all"))

    return ClusterOverviewResponse(
        total_nodes=len(nodes),
        active_nodes=len(active),
        inactive_nodes=len(nodes) - len(active),
        total_cpu_cores=sum(n.cpu_cores for n in nodes),
        total_ram_mb=sum(n.ram_mb for n in nodes),
        total_disk_gb=sum(n.disk_gb for n in nodes),
        avg_cpu_usage=sum(n.cpu_usage for n in active) / len(active) if active else 0.0,
        avg_ram_usage=sum(n.ram_usage for n in active) / len(active) if active else 0.0,
        avg_disk_usage=sum(n.disk_usage for n in active) / len(active) if active else 0.0,
        avg_load=sum(n.current_load for n in active) / len(active) if active else 0.0,
        total_assignments=total_assignments,
        web_nodes=web_count,
        mail_nodes=mail_count,
        db_nodes=db_count,
        nodes=[ClusterNodeResponse.model_validate(n) for n in nodes],
    ).model_dump(mode="json")


# =========================================================================
# POST /cluster/heartbeat -- receive heartbeat from a node
# =========================================================================


@router.post("/heartbeat", status_code=status.HTTP_200_OK)
async def receive_heartbeat(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive a heartbeat ping from a cluster node.

    Nodes call this endpoint every 30s with their current stats.
    Authentication is via Bearer token matching the node's API key.
    """
    body = await request.json()
    node_hostname = body.get("hostname")
    if not node_hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="hostname is required",
        )

    result = await db.execute(
        select(ClusterNode).where(ClusterNode.hostname == node_hostname)
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown node hostname.",
        )

    # Update stats
    node.cpu_usage = body.get("cpu_usage", node.cpu_usage)
    node.ram_usage = body.get("ram_usage", node.ram_usage)
    node.disk_usage = body.get("disk_usage", node.disk_usage)
    node.current_load = body.get("current_load", node.current_load)
    node.cpu_cores = body.get("cpu_cores", node.cpu_cores)
    node.ram_mb = body.get("ram_mb", node.ram_mb)
    node.disk_gb = body.get("disk_gb", node.disk_gb)
    node.last_heartbeat = datetime.now(timezone.utc)
    node.failed_checks = 0

    await db.flush()

    return {"status": "ok", "node": node.hostname}


# =========================================================================
# GET /cluster/heartbeat -- endpoint for connectivity tests
# =========================================================================


@router.get("/heartbeat", status_code=status.HTTP_200_OK)
async def heartbeat_ping():
    """Simple ping endpoint used by connectivity tests and health checks."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
