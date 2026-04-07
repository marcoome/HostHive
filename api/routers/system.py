"""System information router -- /api/v1/system (admin only).

Provides detailed system information: OS, kernel, CPU, RAM, disk, network,
top processes, SMART disk health, hostname management, and reboot control.

All endpoints use psutil and subprocess directly. This router NEVER proxies
to the on-host agent on port 7080 -- the panel collects everything in-process
to avoid the agent dependency. Blocking syscalls are dispatched through
asyncio.get_running_loop().run_in_executor() so the event loop is never
blocked.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypeVar

import psutil
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

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_activity(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


async def _to_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking function in the default executor (thread pool)."""
    loop = asyncio.get_running_loop()
    if kwargs:
        from functools import partial
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))
    return await loop.run_in_executor(None, func, *args)


def _run(cmd: list[str], timeout: int = 15, input_data: Optional[str] = None) -> subprocess.CompletedProcess:
    """Synchronous subprocess wrapper. Always call via _run_async."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_data,
    )


async def _run_async(
    cmd: list[str],
    timeout: int = 15,
    input_data: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess command in the default executor."""
    return await _to_thread(_run, cmd, timeout, input_data)


def _read_text(path: str) -> str:
    """Read a text file synchronously (call via _to_thread)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _parse_os_release() -> dict[str, str]:
    """Parse /etc/os-release into a dict (blocking)."""
    result: dict[str, str] = {}
    try:
        content = _read_text("/etc/os-release")
    except Exception:
        return result
    for line in content.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip().strip('"')
    return result


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

def _collect_system_info() -> dict[str, Any]:
    """Collect comprehensive system information using psutil + /proc.

    This is a single blocking function so the entire collection runs in
    one executor task instead of bouncing through many subprocess calls.
    """
    info: dict[str, Any] = {}

    # ----- OS release -----
    os_release = _parse_os_release()
    info["os"] = {
        "name": os_release.get("PRETTY_NAME", "Unknown"),
        "id": os_release.get("ID", ""),
        "version": os_release.get("VERSION_ID", ""),
        "codename": os_release.get("VERSION_CODENAME", ""),
    }

    # ----- Kernel info (platform.uname is a pure-python call into uname(3)) -----
    try:
        uname = platform.uname()
        info["kernel"] = f"{uname.system} {uname.node} {uname.release} {uname.version} {uname.machine}"
        info["kernel_version"] = uname.release
    except Exception:
        pass

    # ----- CPU info via psutil -----
    try:
        cpu_freq = psutil.cpu_freq()
        cpu_count_logical = psutil.cpu_count(logical=True) or 0
        cpu_count_physical = psutil.cpu_count(logical=False) or 0
        threads_per_core = (
            cpu_count_logical // cpu_count_physical
            if cpu_count_physical > 0
            else 1
        )

        # Try to get a friendly model name from /proc/cpuinfo
        model = "Unknown"
        try:
            cpuinfo = _read_text("/proc/cpuinfo")
            for line in cpuinfo.splitlines():
                if line.lower().startswith("model name"):
                    _, _, val = line.partition(":")
                    model = val.strip()
                    break
        except Exception:
            pass

        info["cpu"] = {
            "model": model,
            "architecture": platform.machine(),
            "cores": cpu_count_logical,
            "physical_cores": cpu_count_physical,
            "threads_per_core": threads_per_core,
            "max_mhz": str(cpu_freq.max) if cpu_freq else "",
            "min_mhz": str(cpu_freq.min) if cpu_freq else "",
            "current_mhz": str(round(cpu_freq.current, 1)) if cpu_freq else "",
            "percent": psutil.cpu_percent(interval=0.1),
        }
    except Exception as e:
        info["cpu"] = {"model": "Unknown", "cores": os.cpu_count() or 0}
        log.debug("CPU info collection failed: %s", e)

    # ----- Memory info via psutil -----
    try:
        vm = psutil.virtual_memory()
        info["memory"] = {
            "total_mb": vm.total // (1024 * 1024),
            "used_mb": vm.used // (1024 * 1024),
            "free_mb": vm.free // (1024 * 1024),
            "available_mb": vm.available // (1024 * 1024),
            "buff_cache_mb": (getattr(vm, "buffers", 0) + getattr(vm, "cached", 0)) // (1024 * 1024),
            "shared_mb": getattr(vm, "shared", 0) // (1024 * 1024),
            "percent_used": round(vm.percent, 1),
        }
    except Exception as e:
        log.debug("Memory info collection failed: %s", e)

    try:
        sm = psutil.swap_memory()
        info["swap"] = {
            "total_mb": sm.total // (1024 * 1024),
            "used_mb": sm.used // (1024 * 1024),
            "free_mb": sm.free // (1024 * 1024),
            "percent_used": round(sm.percent, 1),
        }
    except Exception as e:
        log.debug("Swap info collection failed: %s", e)

    # ----- Disks via psutil.disk_partitions -----
    try:
        disks: list[dict] = []
        for part in psutil.disk_partitions(all=False):
            disk_entry: dict[str, Any] = {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
            }
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_entry.update({
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "percent_used": round(usage.percent, 1),
                })
            except (PermissionError, OSError):
                pass
            disks.append(disk_entry)
        info["disks"] = disks
    except Exception as e:
        log.debug("Disk info collection failed: %s", e)

    # ----- Filesystems summary (same as disks but flattened) -----
    try:
        filesystems: list[dict] = []
        for part in psutil.disk_partitions(all=False):
            if part.device.startswith(("tmpfs", "udev", "devtmpfs")):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                filesystems.append({
                    "filesystem": part.device,
                    "size": _human_bytes(usage.total),
                    "used": _human_bytes(usage.used),
                    "available": _human_bytes(usage.free),
                    "use_percent": f"{round(usage.percent)}%",
                    "mount": part.mountpoint,
                })
            except (PermissionError, OSError):
                continue
        info["filesystems"] = filesystems
    except Exception as e:
        log.debug("Filesystems collection failed: %s", e)

    # ----- Uptime via psutil -----
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = datetime.now().timestamp() - boot_time
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        info["uptime"] = {
            "seconds": int(uptime_seconds),
            "boot_time": datetime.fromtimestamp(boot_time, tz=timezone.utc).isoformat(),
            "human": f"{days}d {hours}h {minutes}m",
        }
    except Exception as e:
        log.debug("Uptime collection failed: %s", e)

    # ----- Load average -----
    try:
        load1, load5, load15 = psutil.getloadavg()
        info["load_average"] = {
            "1min": round(load1, 2),
            "5min": round(load5, 2),
            "15min": round(load15, 2),
        }
    except Exception as e:
        log.debug("Load average collection failed: %s", e)

    # ----- Hostname -----
    try:
        info["hostname"] = socket.getfqdn() or socket.gethostname()
    except Exception:
        try:
            info["hostname"] = socket.gethostname()
        except Exception:
            pass

    # ----- Timezone (read /etc/timezone, fall back to time.tzname) -----
    try:
        tz_content = _read_text("/etc/timezone").strip()
        if tz_content:
            info["timezone"] = tz_content
    except Exception:
        try:
            import time as _time
            info["timezone"] = _time.tzname[0] if _time.tzname else ""
        except Exception:
            pass

    info["collected_at"] = datetime.now(timezone.utc).isoformat()
    return info


def _human_bytes(num: int) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(num) < 1024:
            return f"{num:.1f}{unit}" if unit != "B" else f"{num}{unit}"
        num /= 1024
    return f"{num:.1f}E"


@router.get("/info", status_code=status.HTTP_200_OK)
async def system_info(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return comprehensive system information: OS, kernel, CPU, RAM, disks."""
    return await _to_thread(_collect_system_info)


# ---------------------------------------------------------------------------
# GET /processes -- Top processes by CPU/RAM
# ---------------------------------------------------------------------------

def _collect_processes(sort_by: str, limit: int) -> dict[str, Any]:
    """Collect and sort process info via psutil."""
    procs: list[dict] = []

    # First pass primes cpu_percent so the next reading is meaningful.
    for p in psutil.process_iter(["pid"]):
        try:
            p.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Tiny sleep so cpu_percent has a delta to compute against.
    import time as _time
    _time.sleep(0.1)

    for p in psutil.process_iter([
        "pid", "username", "name", "cmdline", "status",
        "create_time", "memory_info", "memory_percent",
    ]):
        try:
            with p.oneshot():
                cpu = p.cpu_percent(interval=None)
                mem_pct = p.memory_percent()
                meminfo = p.memory_info()
                cmdline = " ".join(p.info.get("cmdline") or []) or p.info.get("name") or ""
                start_ts = p.info.get("create_time") or 0
                start_human = (
                    datetime.fromtimestamp(start_ts).strftime("%H:%M")
                    if start_ts
                    else ""
                )
                procs.append({
                    "user": p.info.get("username") or "",
                    "pid": p.info.get("pid"),
                    "cpu_percent": round(cpu, 1),
                    "mem_percent": round(mem_pct, 1),
                    "vsz_kb": meminfo.vms // 1024 if meminfo else 0,
                    "rss_kb": meminfo.rss // 1024 if meminfo else 0,
                    "tty": "?",
                    "state": p.info.get("status") or "",
                    "start": start_human,
                    "time": "",
                    "command": cmdline,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    total = len(procs)

    key = "cpu_percent" if sort_by == "cpu" else "mem_percent"
    procs.sort(key=lambda d: d.get(key, 0.0), reverse=True)

    return {
        "processes": procs[:limit],
        "total": total,
        "sort_by": sort_by,
    }


@router.get("/processes", status_code=status.HTTP_200_OK)
async def top_processes(
    sort_by: str = Query("cpu", pattern="^(cpu|mem)$"),
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    admin: User = Depends(_admin),
):
    """Return top processes sorted by CPU or memory usage."""
    try:
        return await _to_thread(_collect_processes, sort_by, limit)
    except Exception as e:
        log.exception("Failed to collect processes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list processes: {e}",
        )


# ---------------------------------------------------------------------------
# GET /network -- Network interfaces and IPs
# ---------------------------------------------------------------------------

def _collect_network() -> dict[str, Any]:
    """Collect network interface info using psutil + /proc."""
    info: dict[str, Any] = {"interfaces": [], "routes": [], "dns": []}

    # ----- Interfaces via psutil -----
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io_counters = psutil.net_io_counters(pernic=True)

        interfaces: list[dict] = []
        for ifname, addr_list in addrs.items():
            iface_addresses: list[dict] = []
            mac = ""
            for addr in addr_list:
                family_name = ""
                if addr.family == socket.AF_INET:
                    family_name = "inet"
                elif addr.family == socket.AF_INET6:
                    family_name = "inet6"
                elif hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
                    mac = addr.address
                    continue
                else:
                    # Linux packet family for MAC
                    try:
                        from socket import AF_PACKET
                        if addr.family == AF_PACKET:
                            mac = addr.address
                            continue
                    except ImportError:
                        pass
                    continue

                # Convert netmask to CIDR prefix length
                prefix_len = 0
                if addr.netmask:
                    try:
                        if family_name == "inet":
                            prefix_len = bin(int.from_bytes(
                                socket.inet_aton(addr.netmask), "big"
                            )).count("1")
                        elif family_name == "inet6":
                            prefix_len = bin(int.from_bytes(
                                socket.inet_pton(socket.AF_INET6, addr.netmask), "big"
                            )).count("1")
                    except Exception:
                        pass

                iface_addresses.append({
                    "family": family_name,
                    "address": addr.address.split("%")[0] if family_name == "inet6" else addr.address,
                    "prefix_len": prefix_len,
                    "scope": "global",
                })

            stat = stats.get(ifname)
            io = io_counters.get(ifname)

            interfaces.append({
                "name": ifname,
                "state": "UP" if (stat and stat.isup) else "DOWN",
                "mtu": stat.mtu if stat else 0,
                "speed_mbps": stat.speed if stat else 0,
                "duplex": str(stat.duplex) if stat else "",
                "mac": mac,
                "addresses": iface_addresses,
                "bytes_sent": io.bytes_sent if io else 0,
                "bytes_recv": io.bytes_recv if io else 0,
                "packets_sent": io.packets_sent if io else 0,
                "packets_recv": io.packets_recv if io else 0,
            })
        info["interfaces"] = interfaces
    except Exception as e:
        log.debug("Interface collection failed: %s", e)

    # ----- Routes via /proc/net/route -----
    try:
        routes_text = _read_text("/proc/net/route")
        routes: list[dict] = []
        lines = routes_text.strip().splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) < 11:
                continue
            iface, dest_hex, gw_hex, _flags, _refcnt, _use, metric, mask_hex = parts[:8]
            try:
                dest_int = int(dest_hex, 16)
                mask_int = int(mask_hex, 16)
                gw_int = int(gw_hex, 16)
                dest_ip = socket.inet_ntoa(dest_int.to_bytes(4, "little"))
                mask_ip = socket.inet_ntoa(mask_int.to_bytes(4, "little"))
                gw_ip = socket.inet_ntoa(gw_int.to_bytes(4, "little"))
                prefix_len = bin(mask_int).count("1")
                if dest_int == 0:
                    dest_str = "default"
                else:
                    dest_str = f"{dest_ip}/{prefix_len}"
                routes.append({
                    "destination": dest_str,
                    "gateway": gw_ip if gw_int else "",
                    "device": iface,
                    "protocol": "",
                    "scope": "",
                    "metric": int(metric) if metric.isdigit() else 0,
                    "netmask": mask_ip,
                })
            except Exception:
                continue
        info["routes"] = routes
    except Exception as e:
        log.debug("Route collection failed: %s", e)

    # ----- DNS resolvers from /etc/resolv.conf -----
    try:
        resolv = _read_text("/etc/resolv.conf")
        dns_servers: list[str] = []
        for line in resolv.splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                parts = line.split()
                if len(parts) >= 2:
                    dns_servers.append(parts[1])
        info["dns"] = dns_servers
    except Exception as e:
        log.debug("DNS collection failed: %s", e)

    return info


@router.get("/network", status_code=status.HTTP_200_OK)
async def network_info(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return network interfaces, IPs, and routing information."""
    return await _to_thread(_collect_network)


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

    # Check if smartctl is available (use shutil.which, no subprocess needed)
    import shutil
    smartctl_path = await _to_thread(shutil.which, "smartctl")
    if not smartctl_path:
        result_dict["error"] = "smartmontools not installed. Install with: apt install smartmontools"
        return result_dict

    result_dict["available"] = True

    # Get SMART info via subprocess in executor
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
        "detail": "Server reboot initiated." + (
            f" System will reboot in {body.delay_minutes} minute(s)." if body.delay_minutes > 0 else " Rebooting now."
        ),
    }


# ---------------------------------------------------------------------------
# GET /hostname -- Current hostname
# ---------------------------------------------------------------------------

def _collect_hostname() -> dict[str, Any]:
    """Collect hostname / FQDN / local IPs via socket + psutil."""
    result_dict: dict[str, Any] = {}

    try:
        result_dict["hostname"] = socket.gethostname()
    except Exception:
        pass

    try:
        result_dict["fqdn"] = socket.getfqdn()
    except Exception:
        pass

    # Local IPs from psutil interfaces (skip loopback)
    try:
        ips: list[str] = []
        for ifname, addr_list in psutil.net_if_addrs().items():
            if ifname == "lo":
                continue
            for addr in addr_list:
                if addr.family == socket.AF_INET and addr.address:
                    ips.append(addr.address)
        result_dict["ips"] = ips
    except Exception:
        pass

    return result_dict


@router.get("/hostname", status_code=status.HTTP_200_OK)
async def get_hostname(
    request: Request,
    admin: User = Depends(_admin),
):
    """Return the current system hostname."""
    return await _to_thread(_collect_hostname)


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

    # Get old hostname (no subprocess needed)
    try:
        old_hostname = await _to_thread(socket.gethostname)
    except Exception:
        old_hostname = "unknown"

    # Set hostname using hostnamectl (subprocess in executor)
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

    # Update /etc/hosts: read directly, then write via `sudo tee`
    try:
        try:
            hosts_content = await _to_thread(_read_text, "/etc/hosts")
        except Exception:
            # Fall back to `sudo cat` if /etc/hosts isn't world-readable
            cat_result = await _run_async(["sudo", "cat", "/etc/hosts"], timeout=5)
            hosts_content = cat_result.stdout if cat_result.returncode == 0 else ""

        if hosts_content and old_hostname and old_hostname != "unknown":
            updated_hosts = hosts_content.replace(old_hostname, new_hostname)
            await _run_async(
                ["sudo", "tee", "/etc/hosts"],
                timeout=5,
                input_data=updated_hosts,
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
