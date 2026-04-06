"""WAF-related Celery tasks -- GeoIP database updates."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from api.tasks import app

logger = logging.getLogger("hosthive.worker")

GEOIP_DB_PATH = Path("/usr/share/GeoIP/GeoLite2-Country.mmdb")


@app.task(name="api.tasks.waf_tasks.update_geoip_database", bind=True, max_retries=3)
def update_geoip_database(self) -> dict:
    """Run geoipupdate to refresh the MaxMind GeoLite2-Country database.

    Scheduled weekly by Celery Beat.  Retries up to 3 times on failure
    (MaxMind servers may be temporarily unavailable).
    """
    logger.info("Starting weekly GeoIP database update")

    # Check that geoipupdate is installed
    which = subprocess.run(
        ["which", "geoipupdate"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if which.returncode != 0:
        logger.warning("geoipupdate not installed, skipping GeoIP update")
        return {"ok": False, "error": "geoipupdate not installed"}

    # Run the update
    result = subprocess.run(
        ["geoipupdate", "-v"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        error_msg = result.stderr or result.stdout
        logger.error("geoipupdate failed: %s", error_msg)
        raise self.retry(
            exc=RuntimeError(f"geoipupdate failed: {error_msg}"),
            countdown=300,  # retry after 5 minutes
        )

    logger.info("GeoIP database updated successfully")

    # Reload nginx so it picks up the new database
    test = subprocess.run(
        ["nginx", "-t"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if test.returncode == 0:
        subprocess.run(
            ["systemctl", "reload", "nginx"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info("nginx reloaded after GeoIP database update")
    else:
        logger.warning("nginx config test failed, skipping reload: %s", test.stderr)

    db_exists = GEOIP_DB_PATH.exists()
    return {
        "ok": True,
        "output": result.stdout,
        "db_exists": db_exists,
    }
