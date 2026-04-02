"""System information router -- /api/v1/system (admin only).

Provides detailed system information: OS, kernel, CPU, RAM, disk, network,
top processes, SMART disk health, hostname management, and reboot control.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

router = APIRouter()
log = logging.getLogger("novapanel.system")

_admin = require_role("admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def _run_async(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run(cmd, timeout))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class HostnameUpdate(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.\-]*$")


class RebootRequest(BaseModel):
    confirm: bool = Field(..., description="Must be true to confirm reboot")
    delay_minutes: int = Field(default=0, ge=0, le=60, description="Delay in minutes before reboot")


# ---------------------------------------------------------------------------
# GET /info -- Detailed system information
# ---------------------------------------------------------------------------

@router.get("/info", status_code=status.HTTP_200_OK)
async def system_info(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return comprehensive system information: OS, kernel, CPU, RAM, disks."""
    info: dict[str, Any] = {}

    # OS release info
    try:
        result = await _run_async(["cat", "/etc/os-release"], timeout=5)
        if result.returncode == 0:
            os_info: dict[str, str] = {}
            for line in result.stdout.strip().splitlines():
                if "=" in line:
                    key, _, val = line.partition("=")
                    os_info[key.strip()] = val.strip().strip('"')
            info["os"] = {
                "name": os_info.get("PRETTY_NAME", "Unknown"),
                "id": os_info.get("ID", ""),
                "version": os_info.get("VERSION_ID", ""),
                "codename": os_info.get("VERSION_CODENAME", ""),
            }
    except Exception:
        info["os"] = {"name": "Unknown"}

    # Kernel info
    try:
        result = await _run_async(["uname", "-a"], timeout=5)
        if result.returncode == 0:
            info["kernel"] = result.stdout.strip()

        result = await _run_async(["uname", "-r"], timeout=5)
        if result.returncode == 0:
            info["kernel_version"] = result.stdout.strip()
    except Exception:
        pass

    # CPU info
    try:
        result = await _run_async(["lscpu"], timeout=5)
        if result.returncode == 0:
            cpu_info: dict[str, str] = {}
            for line in result.stdout.strip().splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    cpu_info[key.strip()] = val.strip()
            info["cpu"] = {
                "model": cpu_info.get("Model name", "Unknown"),
                "architecture": cpu_info.get("Architecture", ""),
                "cores": int(cpu_info.get("CPU(s)", "0")) if cpu_info.get("CPU(s)", "").isdigit() else 0,
                "threads_per_core": int(cpu_info.get("Thread(s) per core", "1")) if cpu_info.get("Thread(s) per core", "").isdigit() else 1,
                "sockets": int(cpu_info.get("Socket(s)", "1")) if cpu_info.get("Socket(s)", "").isdigit() else 1,
                "max_mhz": cpu_info.get("CPU max MHz", ""),
                "min_mhz": cpu_info.get("CPU min MHz", ""),
                "cache_l2": cpu_info.get("L2 cache", ""),
                "cache_l3": cpu_info.get("L3 cache", ""),
                "virtualization": cpu_info.get("Virtualization", ""),
                "hypervisor_vendor": cpu_info.get("Hypervisor vendor", ""),
            }
    except Exception:
        info["cpu"] = {"model": "Unknown", "cores": os.cpu_count() or 0}

    # Memory info
    try:
        result = await _run_async(["free", "-m"], timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            for line in lines:
                if line.startswith("Mem:"):
                    parts = line.split()
                    if len(parts) >= 7:
                        info["memory"] = {
                            "total_mb": int(parts[1]),
                            "used_mb": int(parts[2]),
                            "free_mb": int(parts[3]),
                            "shared_mb": int(parts[4]),
                            "buff_cache_mb": int(parts[5]),
                            "available_mb": int(parts[6]),
                            "percent_used": round(int(parts[2]) / int(parts[1]) * 100, 1) if int(parts[1]) > 0 else 0,
                        }
                elif line.startswith("Swap:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        info["swap"] = {
                            "total_mb": int(parts[1]),
                            "used_mb": int(parts[2]),
                            "free_mb": int(parts[3]) if len(parts) > 3 else 0,
                        }
    except Exception:
        pass

    # Disk info
    try:
        result = await _run_async(["lsblk", "-Jb", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL"], timeout=5)
        if result.returncode == 0:
            import json
            try:
                lsblk_data = json.loads(result.stdout)
                info["disks"] = lsblk_data.get("blockdevices", [])
            except json.JSONDecodeError:
                info["disks"] = []
        else:
            # Fallback: plain lsblk
            result = await _run_async(["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE"], timeout=5)
            if result.returncode == 0:
                info["disks_raw"] = result.stdout.strip()
    except Exception:
        pass

    # Disk usage (df)
    try:
        result = await _run_async(["df", "-h", "--output=source,size,used,avail,pcent,target"], timeout=5)
        if result.returncode == 0:
            filesystems: list[dict] = []
            for line in result.stdout.strip().splitlines()[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 6 and not parts[0].startswith("tmpfs") and not parts[0].startswith("udev"):
                    filesystems.append({
                        "filesystem": parts[0],
                        "size": parts[1],
                        "used": parts[2],
                        "available": parts[3],
                        "use_percent": parts[4],
                        "mount": parts[5],
                    })
            info["filesystems"] = filesystems
    except Exception:
        pass

    # Uptime
    try:
        result = await _run_async(["cat", "/proc/uptime"], timeout=5)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if parts:
                uptime_seconds = float(parts[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                info["uptime"] = {
                    "seconds": int(uptime_seconds),
                    "human": f"{days}d {hours}h {minutes}m",
                }
    except Exception:
        pass

    # Load average
    try:
        result = await _run_async(["cat", "/proc/loadavg"], timeout=5)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                info["load_average"] = {
                    "1min": float(parts[0]),
                    "5min": float(parts[1]),
                    "15min": float(parts[2]),
                }
    except Exception:
        pass

    # Hostname
    try:
        result = await _run_async(["hostname", "-f"], timeout=5)
        if result.returncode == 0:
            info["hostname"] = result.stdout.strip()
        else:
            result = await _run_async(["hostname"], timeout=5)
            if result.returncode == 0:
                info["hostname"] = result.stdout.strip()
    except Exception:
        pass

    # Timezone
    try:
        result = await _run_async(["timedatectl", "show", "--property=Timezone", "--value"], timeout=5)
        if result.returncode == 0:
            info["timezone"] = result.stdout.strip()
    except Exception:
        pass

    info["collected_at"] = datetime.now(timezone.utc).isoformat()

    return info


# ---------------------------------------------------------------------------
# GET /processes -- Top processes by CPU/RAM
# ---------------------------------------------------------------------------

@router.get("/processes", status_code=status.HTTP_200_OK)
async def top_processes(
    sort_by: str = Query("cpu", pattern="^(cpu|mem)$"),
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Return top processes sorted by CPU or memory usage."""
    sort_flag = "-%cpu" if sort_by == "cpu" else "-%mem"

    try:
        result = await _run_async(
            ["ps", "aux", f"--sort={sort_flag}"],
            timeout=10,
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list processes: {result.stderr.strip()}",
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Timeout listing processes.",
        )

    lines = result.stdout.strip().splitlines()
    if not lines:
        return {"processes": [], "total": 0}

    # Parse header and rows
    header = lines[0]
    processes: list[dict] = []

    for line in lines[1:limit + 1]:
        parts = line.split(None, 10)
        if len(parts) >= 11:
            processes.append({
                "user": parts[0],
                "pid": int(parts[1]) if parts[1].isdigit() else parts[1],
                "cpu_percent": float(parts[2]) if _is_float(parts[2]) else 0.0,
                "mem_percent": float(parts[3]) if _is_float(parts[3]) else 0.0,
                "vsz_kb": int(parts[4]) if parts[4].isdigit() else 0,
                "rss_kb": int(parts[5]) if parts[5].isdigit() else 0,
                "tty": parts[6],
                "state": parts[7],
                "start": parts[8],
                "time": parts[9],
                "command": parts[10],
            })

    # Total process count
    try:
        count_result = await _run_async(["ps", "aux", "--no-headers"], timeout=5)
        total = len(count_result.stdout.strip().splitlines()) if count_result.returncode == 0 else len(lines) - 1
    except Exception:
        total = len(lines) - 1

    return {
        "processes": processes,
        "total": total,
        "sort_by": sort_by,
    }


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# GET /network -- Network interfaces and IPs
# ---------------------------------------------------------------------------

@router.get("/network", status_code=status.HTTP_200_OK)
async def network_info(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return network interfaces, IPs, and routing information."""
    info: dict[str, Any] = {"interfaces": [], "routes": [], "dns": []}

    # Network interfaces via ip addr
    try:
        result = await _run_async(["ip", "-j", "addr", "show"], timeout=10)
        if result.returncode == 0:
            import json
            try:
                interfaces_data = json.loads(result.stdout)
                interfaces: list[dict] = []
                for iface in interfaces_data:
                    addresses: list[dict] = []
                    for addr_info in iface.get("addr_info", []):
                        addresses.append({
                            "family": addr_info.get("family", ""),
                            "address": addr_info.get("local", ""),
                            "prefix_len": addr_info.get("prefixlen", 0),
                            "scope": addr_info.get("scope", ""),
                        })
                    interfaces.append({
                        "name": iface.get("ifname", ""),
                        "state": iface.get("operstate", "UNKNOWN"),
                        "mtu": iface.get("mtu", 0),
                        "mac": iface.get("address", ""),
                        "addresses": addresses,
                        "flags": iface.get("flags", []),
                    })
                info["interfaces"] = interfaces
            except json.JSONDecodeError:
                # Fallback to plain text parsing
                info["interfaces_raw"] = result.stdout.strip()
        else:
            # Fallback: plain ip addr
            result = await _run_async(["ip", "addr", "show"], timeout=10)
            if result.returncode == 0:
                info["interfaces_raw"] = result.stdout.strip()
    except Exception:
        pass

    # Routes
    try:
        result = await _run_async(["ip", "-j", "route", "show"], timeout=5)
        if result.returncode == 0:
            import json
            try:
                routes_data = json.loads(result.stdout)
                routes: list[dict] = []
                for route in routes_data:
                    routes.append({
                        "destination": route.get("dst", ""),
                        "gateway": route.get("gateway", ""),
                        "device": route.get("dev", ""),
                        "protocol": route.get("protocol", ""),
                        "scope": route.get("scope", ""),
                        "metric": route.get("metric", 0),
                    })
                info["routes"] = routes
            except json.JSONDecodeError:
                pass
        else:
            result = await _run_async(["ip", "route", "show"], timeout=5)
            if result.returncode == 0:
                info["routes_raw"] = result.stdout.strip()
    except Exception:
        pass

    # DNS resolvers
    try:
        result = await _run_async(["cat", "/etc/resolv.conf"], timeout=5)
        if result.returncode == 0:
            dns_servers: list[str] = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        dns_servers.append(parts[1])
            info["dns"] = dns_servers
    except Exception:
        pass

    # Public IP (try multiple sources)
    try:
        result = await _run_async(["curl", "-s", "--max-time", "3", "https://ifconfig.me"], timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            info["public_ip"] = result.stdout.strip()
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# GET /disk/smart -- SMART disk health
# ---------------------------------------------------------------------------

@router.get("/disk/smart", status_code=status.HTTP_200_OK)
async def disk_smart(
    device: str = Query("/dev/sda", max_length=64),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Return SMART disk health information (requires smartmontools)."""
    # Sanitize device path
    device = device.strip()
    if not re.match(r"^/dev/[a-zA-Z0-9]+$", device):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid device path: {device}",
        )

    result_dict: dict[str, Any] = {
        "device": device,
        "available": False,
    }

    # Check if smartctl is available
    try:
        which = await _run_async(["which", "smartctl"], timeout=5)
        if which.returncode != 0:
            result_dict["error"] = "smartmontools not installed. Install with: apt install smartmontools"
            return result_dict
    except Exception:
        result_dict["error"] = "Cannot check for smartctl"
        return result_dict

    result_dict["available"] = True

    # Get SMART info
    try:
        result = await _run_async(["sudo", "smartctl", "-a", device], timeout=15)
        output = result.stdout

        # Parse key fields
        smart_info: dict[str, Any] = {"raw_output": output[:3000]}

        # Health status
        health_match = re.search(r"SMART overall-health.*?:\s*(\S+)", output)
        if health_match:
            smart_info["health_status"] = health_match.group(1)

        # Model info
        for field_name in ["Device Model", "Model Number", "Serial Number", "Firmware Version", "User Capacity"]:
            match = re.search(rf"{field_name}:\s*(.+)", output)
            if match:
                key = field_name.lower().replace(" ", "_")
                smart_info[key] = match.group(1).strip()

        # Temperature
        temp_match = re.search(r"Temperature_Celsius.*?(\d+)\s*(?:\(|$)", output)
        if temp_match:
            smart_info["temperature_celsius"] = int(temp_match.group(1))

        # Power on hours
        hours_match = re.search(r"Power_On_Hours.*?(\d+)", output)
        if hours_match:
            smart_info["power_on_hours"] = int(hours_match.group(1))

        # Reallocated sectors
        realloc_match = re.search(r"Reallocated_Sector_Ct.*?(\d+)\s*$", output, re.MULTILINE)
        if realloc_match:
            smart_info["reallocated_sectors"] = int(realloc_match.group(1))

        # Parse SMART attributes table
        attributes: list[dict] = []
        in_table = False
        for line in output.splitlines():
            if "ATTRIBUTE_NAME" in line:
                in_table = True
                continue
            if in_table:
                if not line.strip() or line.strip().startswith("="):
                    break
                parts = line.split()
                if len(parts) >= 10 and parts[0].isdigit():
                    attributes.append({
                        "id": int(parts[0]),
                        "name": parts[1],
                        "value": int(parts[3]) if parts[3].isdigit() else parts[3],
                        "worst": int(parts[4]) if parts[4].isdigit() else parts[4],
                        "threshold": int(parts[5]) if parts[5].isdigit() else parts[5],
                        "raw_value": parts[9] if len(parts) > 9 else parts[-1],
                    })

        smart_info["attributes"] = attributes
        result_dict["smart"] = smart_info

    except subprocess.TimeoutExpired:
        result_dict["error"] = "SMART query timed out"
    except Exception as e:
        result_dict["error"] = str(e)

    return result_dict


# ---------------------------------------------------------------------------
# POST /reboot -- Reboot server (with confirmation)
# ---------------------------------------------------------------------------

@router.post("/reboot", status_code=status.HTTP_200_OK)
async def reboot_server(
    body: RebootRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Reboot the server. Requires explicit confirmation."""
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reboot not confirmed. Set 'confirm' to true to proceed.",
        )

    _log_activity(
        db, request, admin.id,
        "system.reboot",
        f"Server reboot initiated (delay: {body.delay_minutes}m)",
    )

    if body.delay_minutes > 0:
        cmd = ["sudo", "shutdown", "-r", f"+{body.delay_minutes}"]
    else:
        cmd = ["sudo", "shutdown", "-r", "now"]

    try:
        result = await _run_async(cmd, timeout=10)
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Reboot command failed: {result.stderr.strip()}",
            )
    except subprocess.TimeoutExpired:
        # This is expected if rebooting immediately
        pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate reboot: {e}",
        )

    return {
        "status": "rebooting",
        "delay_minutes": body.delay_minutes,
        "detail": f"Server reboot initiated." + (
            f" System will reboot in {body.delay_minutes} minute(s)." if body.delay_minutes > 0 else " Rebooting now."
        ),
    }


# ---------------------------------------------------------------------------
# GET /hostname -- Current hostname
# ---------------------------------------------------------------------------

@router.get("/hostname", status_code=status.HTTP_200_OK)
async def get_hostname(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return the current system hostname."""
    result_dict: dict[str, Any] = {}

    try:
        result = await _run_async(["hostname"], timeout=5)
        if result.returncode == 0:
            result_dict["hostname"] = result.stdout.strip()
    except Exception:
        pass

    try:
        result = await _run_async(["hostname", "-f"], timeout=5)
        if result.returncode == 0:
            result_dict["fqdn"] = result.stdout.strip()
    except Exception:
        pass

    try:
        result = await _run_async(["hostname", "-I"], timeout=5)
        if result.returncode == 0:
            result_dict["ips"] = result.stdout.strip().split()
    except Exception:
        pass

    return result_dict


# ---------------------------------------------------------------------------
# PUT /hostname -- Change hostname
# ---------------------------------------------------------------------------

@router.put("/hostname", status_code=status.HTTP_200_OK)
async def set_hostname(
    body: HostnameUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Change the system hostname."""
    new_hostname = body.hostname.strip()

    # Get old hostname
    try:
        old_result = await _run_async(["hostname"], timeout=5)
        old_hostname = old_result.stdout.strip() if old_result.returncode == 0 else "unknown"
    except Exception:
        old_hostname = "unknown"

    # Set hostname using hostnamectl
    try:
        result = await _run_async(["sudo", "hostnamectl", "set-hostname", new_hostname], timeout=10)
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to set hostname: {result.stderr.strip()}",
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Timeout setting hostname.",
        )

    # Update /etc/hosts
    try:
        hosts_result = await _run_async(["sudo", "cat", "/etc/hosts"], timeout=5)
        if hosts_result.returncode == 0:
            hosts_content = hosts_result.stdout
            # Replace old hostname with new
            updated_hosts = hosts_content.replace(old_hostname, new_hostname)
            proc = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["sudo", "tee", "/etc/hosts"],
                    input=updated_hosts,
                    capture_output=True,
                    text=True,
                    timeout=5,
                ),
            )
    except Exception:
        log.warning("Could not update /etc/hosts")

    _log_activity(
        db, request, admin.id,
        "system.hostname_change",
        f"Hostname changed from '{old_hostname}' to '{new_hostname}'",
    )

    return {
        "old_hostname": old_hostname,
        "new_hostname": new_hostname,
        "detail": f"Hostname changed to '{new_hostname}'.",
    }
