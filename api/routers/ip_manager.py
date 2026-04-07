"""IP management router -- /api/v1/ip (admin only).

Manage IP addresses on the server, maintain IP blacklist/whitelist
via UFW firewall rules.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

router = APIRouter()
log = logging.getLogger("novapanel.ip_manager")

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


def _validate_ip(ip: str) -> str:
    """Validate an IP address or CIDR notation."""
    ip = ip.strip()
    # IPv4 or IPv4/CIDR
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(/\d{1,2})?$", ip):
        # Basic range check
        parts = ip.split("/")[0].split(".")
        if all(0 <= int(p) <= 255 for p in parts):
            return ip
    # IPv6 or IPv6/CIDR
    if re.match(r"^[0-9a-fA-F:]+(/\d{1,3})?$", ip):
        return ip
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Invalid IP address: {ip}",
    )


def _validate_interface(interface: str) -> str:
    """Validate a network interface name."""
    cleaned = re.sub(r"[^a-zA-Z0-9._\-]", "", interface)
    if not cleaned or cleaned != interface:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid interface name: {interface}",
        )
    return cleaned


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AddIPRequest(BaseModel):
    ip: str = Field(..., min_length=3, max_length=64, description="IP address with CIDR (e.g. 192.168.1.100/24)")
    interface: str = Field(default="eth0", min_length=1, max_length=32, description="Network interface")
    label: Optional[str] = Field(default=None, max_length=64, description="Optional label for the IP")


class BlockIPRequest(BaseModel):
    ip: str = Field(..., min_length=3, max_length=64, description="IP address to block")
    comment: Optional[str] = Field(default=None, max_length=255, description="Reason for blocking")


class WhitelistIPRequest(BaseModel):
    ip: str = Field(..., min_length=3, max_length=64, description="IP address to whitelist")
    comment: Optional[str] = Field(default=None, max_length=255, description="Reason for whitelisting")


# ---------------------------------------------------------------------------
# GET /addresses -- List all IPs on server
# ---------------------------------------------------------------------------

@router.get("/addresses", status_code=status.HTTP_200_OK)
async def list_ip_addresses(
    request: Request,
    admin: User = Depends(_admin),
):
    """List all IP addresses assigned to network interfaces."""
    addresses: list[dict] = []

    try:
        result = await _run_async(["ip", "-j", "addr", "show"], timeout=10)
        if result.returncode == 0:
            try:
                interfaces = json.loads(result.stdout)
                for iface in interfaces:
                    iface_name = iface.get("ifname", "")
                    iface_state = iface.get("operstate", "UNKNOWN")
                    mac = iface.get("address", "")

                    for addr in iface.get("addr_info", []):
                        addresses.append({
                            "interface": iface_name,
                            "address": addr.get("local", ""),
                            "prefix_len": addr.get("prefixlen", 0),
                            "family": addr.get("family", ""),
                            "scope": addr.get("scope", ""),
                            "label": addr.get("label", ""),
                            "state": iface_state,
                            "mac": mac,
                            "dynamic": addr.get("dynamic", False),
                        })
            except json.JSONDecodeError:
                pass
    except Exception:
        pass

    # Fallback: plain ip addr if JSON didn't work
    if not addresses:
        try:
            result = await _run_async(["ip", "addr", "show"], timeout=10)
            if result.returncode == 0:
                current_iface = ""
                for line in result.stdout.strip().splitlines():
                    # Interface line: "2: eth0: <BROADCAST,...>"
                    iface_match = re.match(r"^\d+:\s+(\S+?):", line)
                    if iface_match:
                        current_iface = iface_match.group(1)
                        continue

                    # Address line: "    inet 192.168.1.100/24 ..."
                    addr_match = re.match(
                        r"\s+inet6?\s+(\S+)\s.*scope\s+(\S+)",
                        line,
                    )
                    if addr_match:
                        addr_cidr = addr_match.group(1)
                        scope = addr_match.group(2)
                        ip_part = addr_cidr.split("/")[0]
                        prefix = addr_cidr.split("/")[1] if "/" in addr_cidr else ""
                        family = "inet6" if ":" in ip_part else "inet"
                        addresses.append({
                            "interface": current_iface,
                            "address": ip_part,
                            "prefix_len": int(prefix) if prefix.isdigit() else 0,
                            "family": family,
                            "scope": scope,
                        })
        except Exception:
            pass

    return {
        "addresses": addresses,
        "count": len(addresses),
    }


# ---------------------------------------------------------------------------
# POST /addresses -- Add IP address to interface
# ---------------------------------------------------------------------------

@router.post("/addresses", status_code=status.HTTP_201_CREATED)
async def add_ip_address(
    body: AddIPRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Add an IP address to a network interface."""
    ip = _validate_ip(body.ip)
    interface = _validate_interface(body.interface)

    # Ensure CIDR notation
    if "/" not in ip:
        ip = f"{ip}/24"

    # Check if the interface exists
    try:
        check = await _run_async(["ip", "link", "show", interface], timeout=5)
        if check.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Network interface '{interface}' not found.",
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Timeout checking network interface.",
        )

    # Add the IP address
    cmd = ["sudo", "ip", "addr", "add", ip, "dev", interface]
    if body.label:
        label = re.sub(r"[^a-zA-Z0-9._\-:]", "", body.label)
        cmd += ["label", f"{interface}:{label}"]

    try:
        result = await _run_async(cmd, timeout=10)
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "File exists" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"IP address {ip} already exists on {interface}.",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to add IP: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add IP: {e}",
        )

    _log_activity(
        db, request, admin.id,
        "ip.add_address",
        f"Added IP {ip} to {interface}" + (f" (label: {body.label})" if body.label else ""),
    )

    return {
        "status": "added",
        "ip": ip,
        "interface": interface,
        "label": body.label,
        "detail": f"IP {ip} added to {interface}.",
        "note": "This change is not persistent across reboots. Add to /etc/network/interfaces or netplan for persistence.",
    }


# ---------------------------------------------------------------------------
# DELETE /addresses/{ip} -- Remove IP address
# ---------------------------------------------------------------------------

@router.delete("/addresses/{ip:path}", status_code=status.HTTP_200_OK)
async def remove_ip_address(
    ip: str,
    interface: str = Query("eth0", max_length=32),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Remove an IP address from a network interface."""
    ip = _validate_ip(ip)
    interface = _validate_interface(interface)

    # Ensure CIDR notation
    if "/" not in ip:
        ip = f"{ip}/24"

    try:
        result = await _run_async(
            ["sudo", "ip", "addr", "del", ip, "dev", interface],
            timeout=10,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "Cannot assign" in error_msg or "does not exist" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"IP address {ip} not found on {interface}.",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to remove IP: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove IP: {e}",
        )

    _log_activity(
        db, request, admin.id,
        "ip.remove_address",
        f"Removed IP {ip} from {interface}",
    )

    return {
        "status": "removed",
        "ip": ip,
        "interface": interface,
        "detail": f"IP {ip} removed from {interface}.",
    }


# ---------------------------------------------------------------------------
# GET /blacklist -- Blocked IPs
# ---------------------------------------------------------------------------

@router.get("/blacklist", status_code=status.HTTP_200_OK)
async def list_blacklist(
    request: Request,
    admin: User = Depends(_admin),
):
    """List all blocked (denied) IP addresses from UFW."""
    blocked: list[dict] = []

    try:
        result = await _run_async(["sudo", "ufw", "status", "numbered"], timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                # Match deny rules: [ 1] Anywhere     DENY IN     203.0.113.50
                # or [ 1] DENY IN     203.0.113.50
                match = re.match(
                    r"\[\s*(\d+)\]\s+(.+?)\s+(DENY)\s+(IN|OUT|FWD)?\s*(.*)",
                    line,
                )
                if match:
                    rule_id = match.group(1)
                    target = match.group(2).strip()
                    source = match.group(5).strip() or target
                    blocked.append({
                        "id": rule_id,
                        "ip": source,
                        "target": target,
                        "direction": (match.group(4) or "in").lower(),
                        "raw": line.strip(),
                    })
    except Exception:
        pass

    # Also check iptables for deny rules
    try:
        result = await _run_async(
            ["sudo", "iptables", "-L", "INPUT", "-n", "--line-numbers"],
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines()[2:]:  # Skip headers
                if "DROP" in line or "REJECT" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        # parts: num target prot opt source destination
                        source_ip = parts[4] if parts[4] != "0.0.0.0/0" else None
                        if source_ip:
                            # Check if already in UFW list
                            if not any(b.get("ip") == source_ip for b in blocked):
                                blocked.append({
                                    "id": f"ipt-{parts[0]}",
                                    "ip": source_ip,
                                    "target": parts[5] if len(parts) > 5 else "anywhere",
                                    "source": "iptables",
                                    "raw": line.strip(),
                                })
    except Exception:
        pass

    return {
        "blocked": blocked,
        "count": len(blocked),
    }


# ---------------------------------------------------------------------------
# POST /blacklist -- Block IP
# ---------------------------------------------------------------------------

@router.post("/blacklist", status_code=status.HTTP_201_CREATED)
async def block_ip(
    body: BlockIPRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Block an IP address using UFW deny rule."""
    ip = _validate_ip(body.ip)

    cmd = ["sudo", "ufw", "deny", "from", ip]
    if body.comment:
        clean_comment = re.sub(r"[^a-zA-Z0-9 ._\-]", "", body.comment)
        cmd += ["comment", clean_comment]

    try:
        result = await _run_async(cmd, timeout=15)
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to block IP: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to block IP: {e}",
        )

    _log_activity(
        db, request, admin.id,
        "ip.block",
        f"Blocked IP {ip}" + (f" (reason: {body.comment})" if body.comment else ""),
    )

    return {
        "status": "blocked",
        "ip": ip,
        "comment": body.comment,
        "detail": f"IP {ip} has been blocked.",
    }


# ---------------------------------------------------------------------------
# DELETE /blacklist/{ip} -- Unblock IP
# ---------------------------------------------------------------------------

@router.delete("/blacklist/{ip:path}", status_code=status.HTTP_200_OK)
async def unblock_ip(
    ip: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Unblock an IP address by removing the UFW deny rule."""
    ip = _validate_ip(ip)

    try:
        result = await _run_async(
            ["sudo", "ufw", "--force", "delete", "deny", "from", ip],
            timeout=15,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "Could not delete" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No deny rule found for IP {ip}.",
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to unblock IP: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unblock IP: {e}",
        )

    _log_activity(
        db, request, admin.id,
        "ip.unblock",
        f"Unblocked IP {ip}",
    )

    return {
        "status": "unblocked",
        "ip": ip,
        "detail": f"IP {ip} has been unblocked.",
    }


# ---------------------------------------------------------------------------
# GET /whitelist -- Whitelisted IPs
# ---------------------------------------------------------------------------

@router.get("/whitelist", status_code=status.HTTP_200_OK)
async def list_whitelist(
    request: Request,
    admin: User = Depends(_admin),
):
    """List all whitelisted (allowed) IP addresses from UFW."""
    whitelisted: list[dict] = []

    try:
        result = await _run_async(["sudo", "ufw", "status", "numbered"], timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                # Match allow rules with specific source IPs
                # [ 1] Anywhere     ALLOW IN     203.0.113.50
                match = re.match(
                    r"\[\s*(\d+)\]\s+(.+?)\s+(ALLOW)\s+(IN|OUT|FWD)?\s*(.*)",
                    line,
                )
                if match:
                    rule_id = match.group(1)
                    target = match.group(2).strip()
                    source = match.group(5).strip()
                    # Only include rules with specific IPs (not "Anywhere")
                    if source and source.lower() != "anywhere":
                        whitelisted.append({
                            "id": rule_id,
                            "ip": source,
                            "target": target,
                            "direction": (match.group(4) or "in").lower(),
                            "raw": line.strip(),
                        })
    except Exception:
        pass

    return {
        "whitelisted": whitelisted,
        "count": len(whitelisted),
    }


# ---------------------------------------------------------------------------
# POST /whitelist -- Whitelist IP
# ---------------------------------------------------------------------------

@router.post("/whitelist", status_code=status.HTTP_201_CREATED)
async def whitelist_ip(
    body: WhitelistIPRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Whitelist an IP address using UFW allow rule."""
    ip = _validate_ip(body.ip)

    cmd = ["sudo", "ufw", "allow", "from", ip]
    if body.comment:
        clean_comment = re.sub(r"[^a-zA-Z0-9 ._\-]", "", body.comment)
        cmd += ["comment", clean_comment]

    try:
        result = await _run_async(cmd, timeout=15)
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to whitelist IP: {error_msg}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to whitelist IP: {e}",
        )

    _log_activity(
        db, request, admin.id,
        "ip.whitelist",
        f"Whitelisted IP {ip}" + (f" (reason: {body.comment})" if body.comment else ""),
    )

    return {
        "status": "whitelisted",
        "ip": ip,
        "comment": body.comment,
        "detail": f"IP {ip} has been whitelisted.",
    }
