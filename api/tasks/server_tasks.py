"""HostHive server monitoring tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.server")


@app.task(
    name="api.tasks.server_tasks.collect_server_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(httpx.HTTPError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=300,
)
def collect_server_stats(self) -> dict:
    """Poll the HostHive agent for current server metrics and persist them."""
    from api.models.server_stats import ServerStat

    logger.info("Collecting server statistics from agent")

    try:
        response = httpx.get(
            f"{settings.AGENT_URL}/api/v1/server/stats",
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.error("Failed to collect server stats: %s", exc)
        raise self.retry(exc=exc)

    with get_sync_session() as session:
        stat = ServerStat(
            cpu_percent=data.get("cpu_percent", 0.0),
            memory_percent=data.get("memory_percent", 0.0),
            memory_used_mb=data.get("memory_used_mb", 0),
            memory_total_mb=data.get("memory_total_mb", 0),
            disk_percent=data.get("disk_percent", 0.0),
            disk_used_gb=data.get("disk_used_gb", 0.0),
            disk_total_gb=data.get("disk_total_gb", 0.0),
            load_avg_1=data.get("load_avg_1", 0.0),
            load_avg_5=data.get("load_avg_5", 0.0),
            load_avg_15=data.get("load_avg_15", 0.0),
            network_rx_bytes=data.get("network_rx_bytes", 0),
            network_tx_bytes=data.get("network_tx_bytes", 0),
            active_connections=data.get("active_connections", 0),
        )
        session.add(stat)
        session.commit()

    logger.info(
        "Server stats recorded: CPU=%.1f%%, MEM=%.1f%%, DISK=%.1f%%",
        stat.cpu_percent, stat.memory_percent, stat.disk_percent,
    )
    return {
        "cpu_percent": stat.cpu_percent,
        "memory_percent": stat.memory_percent,
        "disk_percent": stat.disk_percent,
    }


@app.task(
    name="api.tasks.server_tasks.cleanup_old_stats",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
)
def cleanup_old_stats(self) -> dict:
    """Delete server statistics older than 30 days to keep the database lean."""
    from api.models.server_stats import ServerStat

    logger.info("Cleaning up server stats older than 30 days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    with get_sync_session() as session:
        result = session.execute(
            delete(ServerStat).where(ServerStat.created_at < cutoff)
        )
        deleted = result.rowcount
        session.commit()

    logger.info("Deleted %d old server stat records (cutoff: %s)", deleted, cutoff)
    return {"deleted_count": deleted, "cutoff": cutoff.isoformat()}


# ---------------------------------------------------------------------------
# Antivirus scanning
# ---------------------------------------------------------------------------

@app.task(
    name="api.tasks.server_tasks.run_antivirus_scan",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=1800,  # 30 min soft limit
    time_limit=2100,       # 35 min hard limit
)
def run_antivirus_scan(self, scan_id: str, scan_path: str) -> dict:
    """Run a ClamAV scan on the given path, quarantining infected files.

    Updates the ScanResult record in the database with progress and results.
    Infected files are moved to /opt/hosthive/quarantine/ and recorded as
    QuarantineEntry rows.
    """
    import os
    import subprocess
    import uuid as _uuid
    from pathlib import Path

    from api.models.antivirus import QuarantineEntry, ScanResult, ScanStatus

    quarantine_dir = Path("/opt/hosthive/quarantine")
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting antivirus scan %s on path: %s", scan_id, scan_path)

    with get_sync_session() as session:
        scan = session.get(ScanResult, _uuid.UUID(scan_id))
        if scan is None:
            logger.error("Scan record %s not found", scan_id)
            return {"error": "Scan record not found"}

        scan.status = ScanStatus.RUNNING
        scan.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()

    # Run clamscan with --move to quarantine infected files
    try:
        result = subprocess.run(
            [
                "sudo", "clamscan",
                "--infected",
                "--recursive",
                f"--move={quarantine_dir}",
                "--log=/var/log/clamav/scan.log",
                scan_path,
            ],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min
        )
    except subprocess.TimeoutExpired:
        with get_sync_session() as session:
            scan = session.get(ScanResult, _uuid.UUID(scan_id))
            if scan:
                scan.status = ScanStatus.FAILED
                scan.error_message = "Scan timed out after 30 minutes"
                scan.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.commit()
        return {"error": "Scan timed out"}
    except Exception as exc:
        with get_sync_session() as session:
            scan = session.get(ScanResult, _uuid.UUID(scan_id))
            if scan:
                scan.status = ScanStatus.FAILED
                scan.error_message = str(exc)
                scan.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.commit()
        return {"error": str(exc)}

    # Parse clamscan output
    infected_files: list[dict] = []
    files_scanned = 0

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "FOUND" in line:
            # Format: /path/to/file: ThreatName FOUND
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                file_path = parts[0].strip()
                threat = parts[1].replace("FOUND", "").strip()
                infected_files.append({"file": file_path, "threat": threat})
        elif "OK" in line:
            files_scanned += 1

    # Also parse the summary section for accurate totals
    for line in result.stdout.splitlines():
        if line.startswith("Scanned files:"):
            try:
                files_scanned = int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass

    files_scanned = max(files_scanned, len(infected_files))

    # Record results and quarantine entries
    with get_sync_session() as session:
        scan = session.get(ScanResult, _uuid.UUID(scan_id))
        if scan is None:
            return {"error": "Scan record not found after scan"}

        scan.status = ScanStatus.COMPLETED
        scan.files_scanned = files_scanned
        scan.infected_count = len(infected_files)
        scan.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        scan.quarantined_files = {
            "files": infected_files,
            "clamscan_returncode": result.returncode,
        }

        for inf in infected_files:
            original = inf["file"]
            filename = os.path.basename(original)
            qpath = quarantine_dir / filename

            entry = QuarantineEntry(
                scan_id=scan.id,
                original_path=original,
                quarantine_path=str(qpath),
                threat_name=inf["threat"],
                file_size=qpath.stat().st_size if qpath.exists() else None,
            )
            session.add(entry)

        session.commit()

    logger.info(
        "Antivirus scan %s completed: %d files scanned, %d infected",
        scan_id, files_scanned, len(infected_files),
    )
    return {
        "scan_id": scan_id,
        "files_scanned": files_scanned,
        "infected_count": len(infected_files),
        "status": "completed",
    }


@app.task(
    name="api.tasks.server_tasks.scheduled_antivirus_scan",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    soft_time_limit=3600,
    time_limit=3900,
)
def scheduled_antivirus_scan(self) -> dict:
    """Nightly scheduled scan of all user home directories.

    Creates a ScanResult record attributed to the first admin user,
    then delegates to run_antivirus_scan.
    """
    import uuid as _uuid

    from sqlalchemy import select as sa_select

    from api.models.antivirus import ScanResult, ScanStatus
    from api.models.users import User, UserRole

    logger.info("Starting scheduled nightly antivirus scan")

    with get_sync_session() as session:
        # Find an admin user to attribute the scan to
        result = session.execute(
            sa_select(User).where(User.role == UserRole.ADMIN).limit(1)
        )
        admin = result.scalar_one_or_none()
        if admin is None:
            logger.error("No admin user found for scheduled scan attribution")
            return {"error": "No admin user found"}

        scan = ScanResult(
            user_id=admin.id,
            scan_path="/home",
            status=ScanStatus.PENDING,
        )
        session.add(scan)
        session.commit()
        scan_id = str(scan.id)

    # Delegate to the main scan task
    return run_antivirus_scan(scan_id, "/home")
