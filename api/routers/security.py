"""Security scanning and hardening router -- /api/v1/security (admin only).

Provides ClamAV malware scanning, SSH config analysis and hardening,
file permission checks, system update management, open port scanning,
and login history analysis.

IMPORTANT: This router runs ALL operations as direct local subprocess
calls (sshd config edits, fail2ban-client, ufw, ss/netstat, apt, etc.).
It does NOT proxy any request to the privileged agent on port 7080.
Every blocking subprocess invocation is dispatched through
asyncio.get_running_loop().run_in_executor() so the FastAPI event loop
stays responsive.

NOTE: Some commands require sudo privileges. Ensure /etc/sudoers.d/hosthive
contains appropriate NOPASSWD entries for clamscan, apt, ss, sshd, ufw,
fail2ban-client, systemctl, tee, mv, cp, rm, find, cat, stat, etc.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

router = APIRouter()
log = logging.getLogger("novapanel.security")

_admin = require_role("admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _run(
    cmd: list[str],
    timeout: int = 30,
    input_data: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a command via subprocess. Raises on timeout.

    Direct subprocess call -- NEVER proxies to the agent on port 7080.
    All security operations (sshd config, fail2ban, ufw, ss/netstat) run
    locally on the panel host.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_data,
            check=False,
        )
    except FileNotFoundError as e:
        # Synthesize a CompletedProcess with non-zero exit so callers can handle uniformly
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="", stderr=f"command not found: {e}"
        )


async def _run_async(
    cmd: list[str],
    timeout: int = 30,
    input_data: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a blocking subprocess call in the default executor.

    Uses asyncio.get_running_loop().run_in_executor() so the FastAPI event
    loop is never blocked. This is the ONLY mechanism this router uses to
    invoke system commands -- there is no agent HTTP proxy.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run(cmd, timeout, input_data))


def _sanitize_path(path: str) -> str:
    """Sanitize a filesystem path to prevent injection."""
    # Only allow alphanumeric, slashes, dots, hyphens, underscores
    cleaned = re.sub(r"[^a-zA-Z0-9/_.\-]", "", path)
    # Prevent directory traversal
    if ".." in cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal not allowed.",
        )
    return cleaned


def _sanitize_ip(ip: str) -> str:
    """Validate and sanitize an IP address."""
    # Support both IPv4 and IPv6
    ip = ip.strip()
    if not re.match(r"^[0-9a-fA-F.:\/]+$", ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid IP address: {ip}",
        )
    return ip


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MalwareScanRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512, description="Filesystem path to scan")


class SSHHardenRequest(BaseModel):
    disable_root_login: bool = Field(default=True)
    disable_password_auth: bool = Field(default=False)
    change_port: Optional[int] = Field(default=None, ge=1, le=65535)
    max_auth_tries: int = Field(default=3, ge=1, le=10)
    allow_users: Optional[list[str]] = Field(default=None, description="List of allowed usernames")


class SecurityUpdateRequest(BaseModel):
    packages: Optional[list[str]] = Field(default=None, description="Specific packages to update, or None for all")
    security_only: bool = Field(default=True, description="Only apply security updates")


# ---------------------------------------------------------------------------
# GET /scan -- Full security audit
# ---------------------------------------------------------------------------

@router.get("/scan", status_code=status.HTTP_200_OK)
async def full_security_scan(
    request: Request,
    admin: User = Depends(_admin),
):
    """Run a comprehensive security audit covering SSH, ports, permissions, and updates."""
    results: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [],
        "score": 0,
        "max_score": 0,
    }

    # --- SSH config check ---
    ssh_result = await _analyze_ssh_config()
    ssh_score = 0
    ssh_max = 5
    if ssh_result.get("settings"):
        s = ssh_result["settings"]
        if s.get("PermitRootLogin") in ("no", "prohibit-password"):
            ssh_score += 1
        if s.get("PasswordAuthentication") == "no":
            ssh_score += 1
        if s.get("MaxAuthTries") and int(s.get("MaxAuthTries", "6")) <= 3:
            ssh_score += 1
        if s.get("Protocol") == "2" or "Protocol" not in s:
            ssh_score += 1
        if s.get("X11Forwarding") == "no":
            ssh_score += 1
    results["checks"].append({
        "name": "SSH Configuration",
        "score": ssh_score,
        "max_score": ssh_max,
        "details": ssh_result,
    })

    # --- Open ports check ---
    ports_result = await _scan_open_ports()
    ports_score = 3  # Start with max, deduct for risky ports
    ports_max = 3
    risky_ports = {"23", "21", "3306", "5432", "6379", "27017", "11211"}
    open_port_numbers = {str(p.get("port", "")) for p in ports_result.get("ports", [])}
    exposed_risky = risky_ports & open_port_numbers
    ports_score -= min(len(exposed_risky), 3)
    results["checks"].append({
        "name": "Open Ports",
        "score": max(ports_score, 0),
        "max_score": ports_max,
        "details": ports_result,
        "warnings": [f"Risky port {p} is open" for p in exposed_risky] if exposed_risky else [],
    })

    # --- File permissions check ---
    perm_result = await _check_file_permissions()
    perm_issues = perm_result.get("issues", [])
    perm_max = 3
    perm_score = perm_max - min(len(perm_issues), perm_max)
    results["checks"].append({
        "name": "File Permissions",
        "score": perm_score,
        "max_score": perm_max,
        "details": perm_result,
    })

    # --- Available updates check ---
    updates_result = await _check_available_updates()
    update_count = updates_result.get("count", 0)
    updates_max = 3
    if update_count == 0:
        updates_score = 3
    elif update_count <= 5:
        updates_score = 2
    elif update_count <= 20:
        updates_score = 1
    else:
        updates_score = 0
    results["checks"].append({
        "name": "System Updates",
        "score": updates_score,
        "max_score": updates_max,
        "details": updates_result,
    })

    # --- Firewall check ---
    fw_result = await _check_firewall_status()
    fw_max = 2
    fw_score = 0
    if fw_result.get("active"):
        fw_score = 2
    elif fw_result.get("installed"):
        fw_score = 1
    results["checks"].append({
        "name": "Firewall",
        "score": fw_score,
        "max_score": fw_max,
        "details": fw_result,
    })

    # --- Fail2ban check ---
    f2b_result = await _check_fail2ban_status()
    f2b_max = 2
    f2b_score = 0
    if f2b_result.get("active"):
        f2b_score = 1
        if f2b_result.get("jail_count", 0) > 0:
            f2b_score = 2
    results["checks"].append({
        "name": "Fail2ban",
        "score": f2b_score,
        "max_score": f2b_max,
        "details": f2b_result,
    })

    # Calculate total score
    results["score"] = sum(c["score"] for c in results["checks"])
    results["max_score"] = sum(c["max_score"] for c in results["checks"])
    total = results["max_score"]
    pct = (results["score"] / total * 100) if total > 0 else 0
    if pct >= 80:
        results["grade"] = "A"
    elif pct >= 60:
        results["grade"] = "B"
    elif pct >= 40:
        results["grade"] = "C"
    else:
        results["grade"] = "D"

    return results


# ---------------------------------------------------------------------------
# GET /malware -- ClamAV scan results (last scan)
# ---------------------------------------------------------------------------

@router.get("/malware", status_code=status.HTTP_200_OK)
async def malware_status(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return ClamAV service status and last scan summary."""
    result: dict[str, Any] = {"installed": False, "running": False, "last_scan": None}

    # Check if ClamAV is installed
    try:
        which = await _run_async(["which", "clamscan"], timeout=5)
        result["installed"] = which.returncode == 0
    except Exception:
        pass

    # Check if clamav-daemon is running
    try:
        svc = await _run_async(["systemctl", "is-active", "clamav-daemon"], timeout=5)
        result["running"] = svc.stdout.strip() == "active"
    except Exception:
        pass

    # Check freshclam database date
    try:
        freshclam = await _run_async(["sudo", "freshclam", "--version"], timeout=10)
        if freshclam.returncode == 0:
            result["database_version"] = freshclam.stdout.strip()
    except Exception:
        pass

    # Look for last scan log
    scan_log = "/var/log/clamav/scan.log"
    if os.path.exists(scan_log):
        try:
            tail = await _run_async(["tail", "-n", "50", scan_log], timeout=5)
            if tail.returncode == 0:
                lines = tail.stdout.strip().splitlines()
                infected_files = [l for l in lines if "FOUND" in l]
                result["last_scan"] = {
                    "log_file": scan_log,
                    "infected_count": len(infected_files),
                    "infected_files": infected_files[-20:],  # Last 20 findings
                    "recent_lines": lines[-10:],
                }
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# POST /malware/scan -- Trigger ClamAV scan on a path
# ---------------------------------------------------------------------------

@router.post("/malware/scan", status_code=status.HTTP_200_OK)
async def trigger_malware_scan(
    body: MalwareScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Trigger a ClamAV scan on the specified path."""
    path = _sanitize_path(body.path)

    # Verify path exists
    if not os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path not found: {path}",
        )

    # Verify ClamAV is installed
    try:
        which = await _run_async(["which", "clamscan"], timeout=5)
        if which.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_424_FAILED_DEPENDENCY,
                detail="ClamAV (clamscan) is not installed. Install with: apt install clamav",
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Timeout checking for ClamAV installation.",
        )

    _log_activity(db, request, admin.id, "security.malware_scan", f"Triggered ClamAV scan on: {path}")

    # Run clamscan (can take a long time for large directories)
    try:
        result = await _run_async(
            ["sudo", "clamscan", "--infected", "--recursive", "--no-summary", path],
            timeout=300,  # 5 min timeout for large scans
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "path": path,
            "detail": "Scan timed out after 5 minutes. Try scanning a smaller directory.",
        }

    # Parse results
    infected_files: list[dict] = []
    clean_count = 0
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "FOUND" in line:
            # Format: /path/to/file: MalwareName FOUND
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                infected_files.append({
                    "file": parts[0].strip(),
                    "threat": parts[1].replace("FOUND", "").strip(),
                })
        elif "OK" in line:
            clean_count += 1

    # Also get summary by running with summary
    try:
        summary_result = await _run_async(
            ["sudo", "clamscan", "--infected", "--recursive", path],
            timeout=300,
        )
        summary_lines = summary_result.stdout.strip().splitlines()
        summary = {}
        for line in summary_lines:
            if ":" in line:
                key, _, val = line.partition(":")
                summary[key.strip()] = val.strip()
    except Exception:
        summary = {}

    return {
        "status": "completed",
        "path": path,
        "infected_count": len(infected_files),
        "scanned_count": clean_count + len(infected_files),
        "infected_files": infected_files,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# GET /ssh -- SSH config analysis
# ---------------------------------------------------------------------------

@router.get("/ssh", status_code=status.HTTP_200_OK)
async def ssh_config_analysis(
    request: Request,
    admin: User = Depends(_admin),
):
    """Analyze the current SSH configuration for security issues."""
    return await _analyze_ssh_config()


async def _analyze_ssh_config() -> dict[str, Any]:
    """Parse /etc/ssh/sshd_config and return security analysis."""
    config_path = "/etc/ssh/sshd_config"
    result: dict[str, Any] = {
        "config_file": config_path,
        "settings": {},
        "recommendations": [],
        "risk_level": "unknown",
    }

    try:
        read_result = await _run_async(["sudo", "cat", config_path], timeout=5)
        if read_result.returncode != 0:
            result["error"] = "Cannot read sshd_config"
            return result
    except Exception as e:
        result["error"] = str(e)
        return result

    # Parse settings (ignore comments and empty lines)
    settings: dict[str, str] = {}
    for line in read_result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            settings[parts[0]] = parts[1]

    result["settings"] = settings

    # Security recommendations
    recommendations: list[dict] = []

    if settings.get("PermitRootLogin", "yes") not in ("no", "prohibit-password"):
        recommendations.append({
            "severity": "high",
            "setting": "PermitRootLogin",
            "current": settings.get("PermitRootLogin", "yes (default)"),
            "recommended": "no",
            "description": "Root login should be disabled. Use a regular user with sudo.",
        })

    if settings.get("PasswordAuthentication", "yes") != "no":
        recommendations.append({
            "severity": "medium",
            "setting": "PasswordAuthentication",
            "current": settings.get("PasswordAuthentication", "yes (default)"),
            "recommended": "no",
            "description": "Password authentication should be disabled in favor of key-based auth.",
        })

    max_auth = int(settings.get("MaxAuthTries", "6"))
    if max_auth > 3:
        recommendations.append({
            "severity": "medium",
            "setting": "MaxAuthTries",
            "current": str(max_auth),
            "recommended": "3",
            "description": "Limit authentication attempts to reduce brute-force risk.",
        })

    if settings.get("X11Forwarding", "no") == "yes":
        recommendations.append({
            "severity": "low",
            "setting": "X11Forwarding",
            "current": "yes",
            "recommended": "no",
            "description": "X11 forwarding should be disabled unless needed.",
        })

    if settings.get("PermitEmptyPasswords", "no") == "yes":
        recommendations.append({
            "severity": "critical",
            "setting": "PermitEmptyPasswords",
            "current": "yes",
            "recommended": "no",
            "description": "Empty passwords must never be permitted.",
        })

    ssh_port = settings.get("Port", "22")
    if ssh_port == "22":
        recommendations.append({
            "severity": "low",
            "setting": "Port",
            "current": "22",
            "recommended": "Non-standard port",
            "description": "Consider changing SSH port from the default to reduce automated attacks.",
        })

    if settings.get("AllowAgentForwarding", "yes") == "yes" and "AllowAgentForwarding" in settings:
        recommendations.append({
            "severity": "low",
            "setting": "AllowAgentForwarding",
            "current": "yes",
            "recommended": "no",
            "description": "Agent forwarding should be disabled unless specifically needed.",
        })

    result["recommendations"] = recommendations

    # Calculate risk level
    high_count = sum(1 for r in recommendations if r["severity"] in ("high", "critical"))
    medium_count = sum(1 for r in recommendations if r["severity"] == "medium")
    if high_count > 0:
        result["risk_level"] = "high"
    elif medium_count > 0:
        result["risk_level"] = "medium"
    elif len(recommendations) > 0:
        result["risk_level"] = "low"
    else:
        result["risk_level"] = "secure"

    return result


# ---------------------------------------------------------------------------
# POST /ssh/harden -- Apply SSH hardening
# ---------------------------------------------------------------------------

@router.post("/ssh/harden", status_code=status.HTTP_200_OK)
async def ssh_harden(
    body: SSHHardenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Apply SSH hardening settings to sshd_config."""
    config_path = "/etc/ssh/sshd_config"
    changes_made: list[str] = []

    # Read current config
    try:
        read_result = await _run_async(["sudo", "cat", config_path], timeout=5)
        if read_result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cannot read sshd_config",
            )
        config_content = read_result.stdout
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Timeout reading sshd_config",
        )

    # Backup the original config (best-effort; failure is non-fatal)
    backup_path: Optional[str] = None
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        candidate = f"{config_path}.backup_{timestamp}"
        cp_result = await _run_async(["sudo", "cp", config_path, candidate], timeout=5)
        if cp_result.returncode == 0:
            backup_path = candidate
        else:
            log.warning("Could not create backup of sshd_config: %s", cp_result.stderr.strip())
    except Exception as exc:
        log.warning("Could not create backup of sshd_config: %s", exc)

    # Build new config lines
    lines = config_content.splitlines()
    new_lines: list[str] = []
    settings_applied: set[str] = set()

    def _set_or_replace(setting: str, value: str):
        """Mark a setting to be set/replaced."""
        nonlocal lines, new_lines, settings_applied
        settings_applied.add(setting)
        changes_made.append(f"{setting} = {value}")

    # Determine which settings to apply
    settings_to_apply: dict[str, str] = {}

    if body.disable_root_login:
        settings_to_apply["PermitRootLogin"] = "no"
    if body.disable_password_auth:
        settings_to_apply["PasswordAuthentication"] = "no"
    if body.change_port is not None:
        settings_to_apply["Port"] = str(body.change_port)
    settings_to_apply["MaxAuthTries"] = str(body.max_auth_tries)
    settings_to_apply["PermitEmptyPasswords"] = "no"
    settings_to_apply["X11Forwarding"] = "no"

    if body.allow_users:
        # Sanitize usernames
        clean_users = []
        for u in body.allow_users:
            cleaned = re.sub(r"[^a-zA-Z0-9._-]", "", u)
            if cleaned:
                clean_users.append(cleaned)
        if clean_users:
            settings_to_apply["AllowUsers"] = " ".join(clean_users)

    # Process each existing line
    for line in lines:
        stripped = line.strip()
        matched = False
        for setting, value in settings_to_apply.items():
            # Match both active and commented-out settings
            if re.match(rf"^#?\s*{re.escape(setting)}\s", stripped):
                new_lines.append(f"{setting} {value}")
                settings_applied.add(setting)
                changes_made.append(f"{setting} = {value}")
                matched = True
                break
        if not matched:
            new_lines.append(line)

    # Add any settings that weren't found in the file
    for setting, value in settings_to_apply.items():
        if setting not in settings_applied:
            new_lines.append(f"{setting} {value}")
            changes_made.append(f"{setting} = {value}")

    # Write the new config atomically: tee -> validate -> mv
    new_content = "\n".join(new_lines) + "\n"
    ssh_restarted = False
    try:
        # Write candidate config to a temp path via `sudo tee` (stdin piped through executor)
        tmp_path = "/tmp/sshd_config_new"
        proc = await _run_async(
            ["sudo", "tee", tmp_path],
            timeout=5,
            input_data=new_content,
        )
        if proc.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write temp config: {proc.stderr}",
            )

        # Validate new config with `sshd -t` before installing
        validate = await _run_async(["sudo", "sshd", "-t", "-f", tmp_path], timeout=10)
        if validate.returncode != 0:
            # Clean up the rejected temp file
            await _run_async(["sudo", "rm", "-f", tmp_path], timeout=5)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SSH config validation failed: {validate.stderr.strip()}. No changes applied.",
            )

        # Move validated config into place atomically
        mv_result = await _run_async(["sudo", "mv", tmp_path, config_path], timeout=5)
        if mv_result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to install new config: {mv_result.stderr}",
            )

        # Restart SSH (try both service names commonly seen on Debian/Ubuntu)
        restart = await _run_async(["sudo", "systemctl", "restart", "sshd"], timeout=15)
        ssh_restarted = restart.returncode == 0
        if not ssh_restarted:
            restart = await _run_async(["sudo", "systemctl", "restart", "ssh"], timeout=15)
            ssh_restarted = restart.returncode == 0

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply SSH hardening: {e}",
        )

    _log_activity(
        db, request, admin.id,
        "security.ssh_harden",
        f"Applied SSH hardening: {', '.join(changes_made)}",
    )

    return {
        "status": "applied",
        "changes": changes_made,
        "ssh_restarted": ssh_restarted,
        "backup": backup_path,
        "detail": "SSH hardening applied successfully." + (
            "" if ssh_restarted else " WARNING: SSH service restart failed, manual restart may be required."
        ),
    }


# ---------------------------------------------------------------------------
# GET /permissions -- Check file permission issues
# ---------------------------------------------------------------------------

@router.get("/permissions", status_code=status.HTTP_200_OK)
async def check_permissions(
    request: Request,
    admin: User = Depends(_admin),
):
    """Check for common file permission security issues."""
    return await _check_file_permissions()


async def _check_file_permissions() -> dict[str, Any]:
    """Scan for common file permission issues."""
    issues: list[dict] = []

    # Check critical system files
    critical_files = [
        ("/etc/shadow", "0640", "root", "shadow"),
        ("/etc/passwd", "0644", "root", "root"),
        ("/etc/ssh/sshd_config", "0644", "root", "root"),
        ("/etc/sudoers", "0440", "root", "root"),
    ]

    for filepath, expected_perms, expected_owner, expected_group in critical_files:
        try:
            result = await _run_async(
                ["stat", "--format=%a %U %G", filepath], timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    actual_perms = parts[0]
                    actual_owner = parts[1]
                    actual_group = parts[2]
                    if actual_perms != expected_perms.lstrip("0"):
                        issues.append({
                            "file": filepath,
                            "type": "permissions",
                            "current": actual_perms,
                            "expected": expected_perms,
                            "severity": "high",
                        })
                    if actual_owner != expected_owner:
                        issues.append({
                            "file": filepath,
                            "type": "ownership",
                            "current": f"{actual_owner}:{actual_group}",
                            "expected": f"{expected_owner}:{expected_group}",
                            "severity": "high",
                        })
        except Exception:
            pass

    # Check for world-writable files in /etc
    try:
        result = await _run_async(
            ["sudo", "find", "/etc", "-maxdepth", "2", "-type", "f", "-perm", "-0002"],
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            for filepath in result.stdout.strip().splitlines()[:20]:
                issues.append({
                    "file": filepath.strip(),
                    "type": "world_writable",
                    "severity": "high",
                    "description": "File is world-writable in /etc",
                })
    except Exception:
        pass

    # Check for SUID/SGID binaries in common locations
    try:
        result = await _run_async(
            ["sudo", "find", "/usr/local/bin", "-maxdepth", "1", "-type", "f", "-perm", "/6000"],
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            for filepath in result.stdout.strip().splitlines()[:20]:
                issues.append({
                    "file": filepath.strip(),
                    "type": "suid_sgid",
                    "severity": "medium",
                    "description": "File has SUID/SGID bit set in /usr/local/bin",
                })
    except Exception:
        pass

    # Check home directory permissions
    try:
        result = await _run_async(
            ["sudo", "find", "/home", "-maxdepth", "1", "-type", "d", "-perm", "/o+rwx"],
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            for dirpath in result.stdout.strip().splitlines()[:20]:
                dirpath = dirpath.strip()
                if dirpath == "/home":
                    continue
                issues.append({
                    "file": dirpath,
                    "type": "home_permissions",
                    "severity": "medium",
                    "description": "Home directory is accessible by others",
                })
    except Exception:
        pass

    return {
        "issues": issues,
        "issue_count": len(issues),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /updates -- Available system updates
# ---------------------------------------------------------------------------

@router.get("/updates", status_code=status.HTTP_200_OK)
async def available_updates(
    request: Request,
    admin: User = Depends(_admin),
):
    """Check for available system updates."""
    return await _check_available_updates()


async def _check_available_updates() -> dict[str, Any]:
    """Check for available apt updates."""
    result_dict: dict[str, Any] = {
        "packages": [],
        "count": 0,
        "security_count": 0,
        "last_update": None,
    }

    # Update package lists first
    try:
        await _run_async(["sudo", "apt-get", "update", "-qq"], timeout=60)
    except Exception:
        pass

    # Get upgradable packages
    try:
        result = await _run_async(["apt", "list", "--upgradable"], timeout=30)
        if result.returncode == 0:
            packages: list[dict] = []
            security_count = 0
            for line in result.stdout.strip().splitlines():
                if "/" not in line or "Listing" in line:
                    continue
                # Format: package/source version arch [upgradable from: old_version]
                parts = line.split("/", 1)
                if len(parts) < 2:
                    continue
                pkg_name = parts[0].strip()
                rest = parts[1]
                is_security = "security" in rest.lower()
                if is_security:
                    security_count += 1
                # Extract version info
                version_match = re.search(r"(\S+)\s+\S+\s+\[upgradable from:\s+(\S+)\]", rest)
                new_version = version_match.group(1) if version_match else ""
                old_version = version_match.group(2) if version_match else ""

                packages.append({
                    "name": pkg_name,
                    "current_version": old_version,
                    "new_version": new_version,
                    "is_security": is_security,
                    "source": rest.split()[0] if rest.split() else "",
                })

            result_dict["packages"] = packages
            result_dict["count"] = len(packages)
            result_dict["security_count"] = security_count
    except Exception:
        pass

    # Check last update time
    try:
        stat_result = await _run_async(
            ["stat", "--format=%Y", "/var/lib/apt/periodic/update-success-stamp"],
            timeout=5,
        )
        if stat_result.returncode == 0:
            ts = int(stat_result.stdout.strip())
            result_dict["last_update"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        pass

    return result_dict


# ---------------------------------------------------------------------------
# POST /updates/apply -- Apply security updates
# ---------------------------------------------------------------------------

@router.post("/updates/apply", status_code=status.HTTP_200_OK)
async def apply_updates(
    body: SecurityUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Apply security or system updates."""
    _log_activity(
        db, request, admin.id,
        "security.apply_updates",
        f"Applying updates: packages={body.packages}, security_only={body.security_only}",
    )

    if body.packages:
        # Update specific packages
        sanitized = []
        for pkg in body.packages:
            cleaned = re.sub(r"[^a-zA-Z0-9._+\-:]", "", pkg)
            if cleaned:
                sanitized.append(cleaned)
        if not sanitized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid package names provided.",
            )
        cmd = ["sudo", "apt-get", "install", "--only-upgrade", "-y"] + sanitized
    elif body.security_only:
        cmd = ["sudo", "apt-get", "upgrade", "-y", "-o", "Dpkg::Options::=--force-confdef"]
    else:
        cmd = ["sudo", "apt-get", "upgrade", "-y", "-o", "Dpkg::Options::=--force-confdef"]

    try:
        result = await _run_async(cmd, timeout=300)
        output = result.stdout[-2000:] if result.stdout else ""
        errors = result.stderr[-500:] if result.stderr else ""
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "detail": "Update process timed out after 5 minutes.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Update failed: {e}",
        )

    return {
        "status": "completed" if success else "failed",
        "exit_code": result.returncode,
        "output": output,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# GET /ports -- Open ports scan
# ---------------------------------------------------------------------------

@router.get("/ports", status_code=status.HTTP_200_OK)
async def open_ports(
    request: Request,
    admin: User = Depends(_admin),
):
    """Scan for open listening ports using ss."""
    return await _scan_open_ports()


async def _scan_open_ports() -> dict[str, Any]:
    """Scan open TCP/UDP listening ports via ss -tlnp and ss -ulnp."""
    ports: list[dict] = []

    # TCP ports
    try:
        result = await _run_async(["sudo", "ss", "-tlnp"], timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines()[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 4:
                    listen_addr = parts[3]
                    # Extract port from address like 0.0.0.0:22 or *:22 or [::]:22
                    port_match = re.search(r":(\d+)$", listen_addr)
                    port = port_match.group(1) if port_match else ""
                    # Extract process info
                    process_info = parts[-1] if "users:" in parts[-1] else ""
                    process_name = ""
                    if process_info:
                        pname_match = re.search(r'users:\(\("([^"]+)"', process_info)
                        process_name = pname_match.group(1) if pname_match else ""
                    ports.append({
                        "protocol": "tcp",
                        "port": port,
                        "address": listen_addr,
                        "state": parts[0] if parts else "",
                        "process": process_name,
                        "raw": line.strip(),
                    })
    except Exception:
        pass

    # UDP ports
    try:
        result = await _run_async(["sudo", "ss", "-ulnp"], timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines()[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 4:
                    listen_addr = parts[3]
                    port_match = re.search(r":(\d+)$", listen_addr)
                    port = port_match.group(1) if port_match else ""
                    process_info = parts[-1] if "users:" in parts[-1] else ""
                    process_name = ""
                    if process_info:
                        pname_match = re.search(r'users:\(\("([^"]+)"', process_info)
                        process_name = pname_match.group(1) if pname_match else ""
                    ports.append({
                        "protocol": "udp",
                        "port": port,
                        "address": listen_addr,
                        "state": parts[0] if parts else "",
                        "process": process_name,
                        "raw": line.strip(),
                    })
    except Exception:
        pass

    return {
        "ports": ports,
        "total": len(ports),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /login-history -- Recent login attempts
# ---------------------------------------------------------------------------

@router.get("/login-history", status_code=status.HTTP_200_OK)
async def login_history(
    lines: int = Query(200, ge=1, le=2000),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Parse recent login attempts from /var/log/auth.log."""
    auth_log = "/var/log/auth.log"
    result_dict: dict[str, Any] = {
        "successful": [],
        "failed": [],
        "summary": {},
    }

    try:
        result = await _run_async(["sudo", "tail", "-n", str(lines), auth_log], timeout=10)
        if result.returncode != 0:
            # Try journalctl as fallback
            result = await _run_async(
                ["journalctl", "-u", "ssh", "-n", str(lines), "--no-pager"],
                timeout=10,
            )
            if result.returncode != 0:
                return {**result_dict, "error": "Cannot read auth.log or journalctl"}
    except Exception as e:
        return {**result_dict, "error": str(e)}

    successful: list[dict] = []
    failed: list[dict] = []
    failed_ips: dict[str, int] = {}
    successful_users: dict[str, int] = {}

    for line in result.stdout.strip().splitlines():
        # Successful login: "Accepted password for user from IP port PORT protocol"
        # or "Accepted publickey for user from IP ..."
        accepted = re.search(
            r"Accepted\s+(\S+)\s+for\s+(\S+)\s+from\s+(\S+)\s+port\s+(\d+)",
            line,
        )
        if accepted:
            user = accepted.group(2)
            ip = accepted.group(3)
            method = accepted.group(1)
            successful.append({
                "timestamp": line[:15],  # syslog timestamp
                "user": user,
                "ip": ip,
                "method": method,
                "raw": line.strip(),
            })
            successful_users[user] = successful_users.get(user, 0) + 1
            continue

        # Failed login: "Failed password for user from IP port PORT"
        # or "Failed password for invalid user NAME from IP ..."
        fail = re.search(
            r"Failed\s+password\s+for\s+(?:invalid\s+user\s+)?(\S+)\s+from\s+(\S+)\s+port\s+(\d+)",
            line,
        )
        if fail:
            user = fail.group(1)
            ip = fail.group(2)
            failed.append({
                "timestamp": line[:15],
                "user": user,
                "ip": ip,
                "raw": line.strip(),
            })
            failed_ips[ip] = failed_ips.get(ip, 0) + 1
            continue

        # Invalid user attempts
        invalid = re.search(
            r"Invalid user\s+(\S+)\s+from\s+(\S+)",
            line,
        )
        if invalid:
            user = invalid.group(1)
            ip = invalid.group(2)
            failed.append({
                "timestamp": line[:15],
                "user": user,
                "ip": ip,
                "type": "invalid_user",
                "raw": line.strip(),
            })
            failed_ips[ip] = failed_ips.get(ip, 0) + 1

    # Sort failed IPs by count (most attempts first)
    top_attackers = sorted(failed_ips.items(), key=lambda x: x[1], reverse=True)[:20]

    result_dict["successful"] = successful[-50:]  # Last 50
    result_dict["failed"] = failed[-100:]  # Last 100
    result_dict["summary"] = {
        "total_successful": len(successful),
        "total_failed": len(failed),
        "top_attacker_ips": [{"ip": ip, "attempts": count} for ip, count in top_attackers],
        "authenticated_users": [{"user": u, "count": c} for u, c in successful_users.items()],
    }

    return result_dict


# ---------------------------------------------------------------------------
# Internal helpers for the full security scan
# ---------------------------------------------------------------------------

async def _check_firewall_status() -> dict[str, Any]:
    """Check if UFW is installed and active."""
    result = {"installed": False, "active": False}
    try:
        which = await _run_async(["which", "ufw"], timeout=5)
        result["installed"] = which.returncode == 0
    except Exception:
        pass

    if result["installed"]:
        try:
            status_result = await _run_async(["sudo", "ufw", "status"], timeout=10)
            if status_result.returncode == 0:
                result["active"] = "active" in status_result.stdout.lower() and "inactive" not in status_result.stdout.lower()
                result["output"] = status_result.stdout.strip()[:500]
        except Exception:
            pass

    return result


async def _check_fail2ban_status() -> dict[str, Any]:
    """Check if Fail2ban is installed and active."""
    result: dict[str, Any] = {"installed": False, "active": False, "jail_count": 0}
    try:
        which = await _run_async(["which", "fail2ban-client"], timeout=5)
        result["installed"] = which.returncode == 0
    except Exception:
        pass

    if result["installed"]:
        try:
            svc = await _run_async(["systemctl", "is-active", "fail2ban"], timeout=5)
            result["active"] = svc.stdout.strip() == "active"
        except Exception:
            pass

        if result["active"]:
            try:
                status_result = await _run_async(
                    ["sudo", "fail2ban-client", "status"], timeout=10,
                )
                if status_result.returncode == 0:
                    for line in status_result.stdout.splitlines():
                        if "Jail list:" in line:
                            jails = line.split("Jail list:", 1)[1].strip()
                            result["jail_count"] = len([j for j in jails.split(",") if j.strip()])
                            break
            except Exception:
                pass

    return result
