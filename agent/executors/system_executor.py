"""
System executor — server stats, service management, firewall, fail2ban,
and sandboxed command execution.

Reads stats from /proc/ directly for minimal overhead.
All subprocess calls use list arguments.  shell=True is NEVER used.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Services that may be restarted via the API.
ALLOWED_SERVICES = frozenset({
    "nginx",
    "apache2",
    "mysql",
    "mariadb",
    "postgresql",
    "php8.0-fpm",
    "php8.1-fpm",
    "php8.2-fpm",
    "php8.3-fpm",
    "php8.4-fpm",
    "exim4",
    "dovecot",
    "proftpd",
    "named",
    "bind9",
    "fail2ban",
    "ufw",
    "redis-server",
    "memcached",
    "cron",
    "ssh",
    "sshd",
})

# Commands allowed via run_command()
ALLOWED_COMMANDS = frozenset({
    "ls",
    "df",
    "du",
    "free",
    "uptime",
    "whoami",
    "hostname",
    "uname",
    "date",
    "cat",
    "wc",
    "tail",
    "head",
    "id",
    "stat",
    "find",
    "php",
    "nginx",
    "mysql",
    "psql",
    "certbot",
})


# ------------------------------------------------------------------
# Server stats (read from /proc/ where possible)
# ------------------------------------------------------------------


def get_server_stats() -> dict[str, Any]:
    """Gather CPU, memory, disk, network, uptime, and load average."""
    stats: dict[str, Any] = {}

    # Load average
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        stats["load_average"] = {
            "1min": float(parts[0]),
            "5min": float(parts[1]),
            "15min": float(parts[2]),
        }
    except (OSError, IndexError, ValueError):
        stats["load_average"] = None

    # Uptime
    try:
        with open("/proc/uptime") as f:
            raw = f.read().split()
        stats["uptime_seconds"] = float(raw[0])
    except (OSError, IndexError, ValueError):
        stats["uptime_seconds"] = None

    # Memory
    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])  # in kB
        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", 0)
        stats["memory"] = {
            "total_kb": total,
            "available_kb": available,
            "used_kb": total - available,
            "percent": round((total - available) / total * 100, 1) if total else 0,
        }
    except (OSError, ValueError):
        stats["memory"] = None

    # CPU usage (quick sample)
    try:
        stats["cpu_percent"] = _sample_cpu_usage()
    except Exception:
        stats["cpu_percent"] = None

    # Disk usage (via df)
    try:
        r = subprocess.run(
            ["df", "-B1", "--output=target,size,used,avail,pcent", "/"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            stats["disk"] = {
                "mount": parts[0],
                "total_bytes": int(parts[1]),
                "used_bytes": int(parts[2]),
                "available_bytes": int(parts[3]),
                "percent": parts[4],
            }
    except Exception:
        stats["disk"] = None

    # Network — bytes transferred
    try:
        with open("/proc/net/dev") as f:
            net_lines = f.readlines()
        interfaces: dict[str, Any] = {}
        for line in net_lines[2:]:
            parts = line.split()
            iface = parts[0].rstrip(":")
            if iface == "lo":
                continue
            interfaces[iface] = {
                "rx_bytes": int(parts[1]),
                "tx_bytes": int(parts[9]),
            }
        stats["network"] = interfaces
    except (OSError, IndexError, ValueError):
        stats["network"] = None

    return stats


def _sample_cpu_usage() -> float:
    """Compute CPU usage over a 0.25s interval from /proc/stat."""
    def _read() -> tuple[int, int]:
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        return idle, total

    idle1, total1 = _read()
    time.sleep(0.25)
    idle2, total2 = _read()

    diff_idle = idle2 - idle1
    diff_total = total2 - total1
    if diff_total == 0:
        return 0.0
    return round((1.0 - diff_idle / diff_total) * 100, 1)


# ------------------------------------------------------------------
# Services
# ------------------------------------------------------------------


def get_running_services() -> list[dict[str, str]]:
    """Return a list of active systemd units."""
    r = subprocess.run(
        ["systemctl", "list-units", "--type=service", "--state=active", "--no-pager", "--plain"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    services = []
    for line in r.stdout.strip().splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4:
            services.append({
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            })
    return services


def restart_service(name: str) -> dict[str, Any]:
    """Restart a systemd service (whitelisted only)."""
    name = name.strip()
    if name not in ALLOWED_SERVICES:
        raise PermissionError(
            f"service {name!r} is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
        )

    r = subprocess.run(
        ["systemctl", "restart", name],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "service": name,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


# ------------------------------------------------------------------
# Firewall (ufw)
# ------------------------------------------------------------------


def get_firewall_rules() -> dict[str, Any]:
    """Parse ufw status output."""
    r = subprocess.run(
        ["ufw", "status", "numbered"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    rules = []
    for line in r.stdout.splitlines():
        m = re.match(r"\[\s*(\d+)\]\s+(.+)", line)
        if m:
            rules.append({"id": int(m.group(1)), "rule": m.group(2).strip()})
    return {
        "active": "active" in r.stdout.lower(),
        "rules": rules,
    }


def add_firewall_rule(
    port: int | str, protocol: str = "tcp", action: str = "allow"
) -> dict[str, Any]:
    """Add a ufw rule."""
    action = action.lower()
    if action not in ("allow", "deny", "reject"):
        raise ValueError(f"invalid action: {action!r}")
    protocol = protocol.lower()
    if protocol not in ("tcp", "udp"):
        raise ValueError(f"invalid protocol: {protocol!r}")

    r = subprocess.run(
        ["ufw", action, f"{port}/{protocol}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def delete_firewall_rule(rule_id: int) -> dict[str, Any]:
    """Delete a ufw rule by its numbered ID."""
    r = subprocess.run(
        ["ufw", "--force", "delete", str(rule_id)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


# ------------------------------------------------------------------
# Fail2ban
# ------------------------------------------------------------------


def get_fail2ban_jails() -> dict[str, Any]:
    """Parse fail2ban-client status output."""
    r = subprocess.run(
        ["fail2ban-client", "status"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    jails: list[str] = []
    for line in r.stdout.splitlines():
        if "Jail list:" in line:
            raw = line.split(":", 1)[1].strip()
            jails = [j.strip() for j in raw.split(",") if j.strip()]

    details = []
    for jail in jails:
        jr = subprocess.run(
            ["fail2ban-client", "status", jail],
            capture_output=True,
            text=True,
            timeout=15,
        )
        details.append({"jail": jail, "status": jr.stdout})

    return {"jails": jails, "details": details}


def unban_ip(ip: str, jail: str) -> dict[str, Any]:
    """Unban an IP from a fail2ban jail."""
    # Basic IP validation
    import ipaddress
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"invalid IP address: {ip!r}")

    if not re.match(r"^[a-zA-Z0-9_-]+$", jail):
        raise ValueError(f"invalid jail name: {jail!r}")

    r = subprocess.run(
        ["fail2ban-client", "set", jail, "unbanip", ip],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


# ------------------------------------------------------------------
# Sandboxed command execution
# ------------------------------------------------------------------


def run_command(cmd: str, args: list[str] | None = None) -> dict[str, Any]:
    """Run a whitelisted command with list arguments, timeout 30s.

    NEVER uses shell=True.  Only commands in ALLOWED_COMMANDS are accepted.
    """
    cmd = cmd.strip()
    if cmd not in ALLOWED_COMMANDS:
        raise PermissionError(
            f"command {cmd!r} is not whitelisted. Allowed: {sorted(ALLOWED_COMMANDS)}"
        )

    full_cmd = [cmd] + (args or [])

    # Extra safety: no argument may contain shell meta-characters that look
    # like injection attempts.
    for arg in full_cmd[1:]:
        if any(c in arg for c in (";", "|", "&", "`", "$", "(", ")", "{", "}")):
            raise ValueError(f"suspicious characters in argument: {arg!r}")

    r = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "command": full_cmd,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


# ------------------------------------------------------------------
# Start / Stop services
# ------------------------------------------------------------------


def start_service(name: str) -> dict[str, Any]:
    """Start a systemd service (whitelisted only)."""
    name = name.strip()
    if name not in ALLOWED_SERVICES:
        raise PermissionError(
            f"service {name!r} is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
        )

    r = subprocess.run(
        ["systemctl", "start", name],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "service": name,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


def stop_service(name: str) -> dict[str, Any]:
    """Stop a systemd service (whitelisted only)."""
    name = name.strip()
    if name not in ALLOWED_SERVICES:
        raise PermissionError(
            f"service {name!r} is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
        )

    r = subprocess.run(
        ["systemctl", "stop", name],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "service": name,
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


# ------------------------------------------------------------------
# Fail2ban enable / disable jails
# ------------------------------------------------------------------


def enable_fail2ban_jail(jail: str) -> dict[str, Any]:
    """Start a fail2ban jail."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", jail):
        raise ValueError(f"invalid jail name: {jail!r}")

    r = subprocess.run(
        ["fail2ban-client", "start", jail],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def disable_fail2ban_jail(jail: str) -> dict[str, Any]:
    """Stop a fail2ban jail."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", jail):
        raise ValueError(f"invalid jail name: {jail!r}")

    r = subprocess.run(
        ["fail2ban-client", "stop", jail],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


# ------------------------------------------------------------------
# Service logs
# ------------------------------------------------------------------


def get_service_logs(service: str, lines: int = 200) -> dict[str, Any]:
    """Return the last N lines of a service's journal."""
    service = service.strip()
    if service not in ALLOWED_SERVICES:
        raise PermissionError(
            f"service {service!r} is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
        )

    r = subprocess.run(
        ["journalctl", "-u", service, "--no-pager", "-n", str(lines)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"stdout": r.stdout, "stderr": r.stderr}


def tail_service_logs(service: str, lines: int = 20) -> dict[str, Any]:
    """Return the last N lines of a service's journal (small default)."""
    return get_service_logs(service, lines)


# ------------------------------------------------------------------
# Terminal execution (more permissive)
# ------------------------------------------------------------------

_TERMINAL_BLOCKLIST = [
    "rm -rf /",
    "reboot",
    "shutdown",
    "poweroff",
    "init ",
    "mkfs",
    "dd if=",
]


def exec_terminal_command(command: str) -> dict[str, Any]:
    """Execute a command via bash -c with a 30s timeout.

    Blocks dangerous commands via a blocklist.
    """
    cmd_lower = command.strip().lower()
    for blocked in _TERMINAL_BLOCKLIST:
        if cmd_lower.startswith(blocked) or blocked in cmd_lower:
            return {
                "stdout": "",
                "stderr": f"blocked: command matches dangerous pattern {blocked!r}",
                "returncode": -1,
            }

    r = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "stdout": r.stdout,
        "stderr": r.stderr,
        "returncode": r.returncode,
    }


# ------------------------------------------------------------------
# File operations
# ------------------------------------------------------------------


def make_directory(path: str) -> dict[str, Any]:
    """Create a directory tree. Path must be under /home/."""
    if not path.startswith("/home/"):
        raise PermissionError("path must start with /home/")
    os.makedirs(path, exist_ok=True)
    return {"path": path, "created": True}


def rename_path(old_path: str, new_path: str) -> dict[str, Any]:
    """Rename/move a file or directory. Both paths must be under /home/."""
    if not old_path.startswith("/home/"):
        raise PermissionError("old_path must start with /home/")
    if not new_path.startswith("/home/"):
        raise PermissionError("new_path must start with /home/")
    os.rename(old_path, new_path)
    return {"old_path": old_path, "new_path": new_path, "renamed": True}


def chmod_path(path: str, permissions: str) -> dict[str, Any]:
    """Change file permissions. Path must be under /home/."""
    if not path.startswith("/home/"):
        raise PermissionError("path must start with /home/")
    if not re.match(r"^[0-7]{3,4}$", permissions):
        raise ValueError(f"invalid permissions: {permissions!r}")

    r = subprocess.run(
        ["chmod", permissions, path],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def compress_paths(paths: list[str], destination: str) -> dict[str, Any]:
    """Create a tar.gz archive from paths. All paths must be under /home/."""
    for p in paths:
        if not p.startswith("/home/"):
            raise PermissionError(f"path must start with /home/: {p!r}")
    if not destination.startswith("/home/"):
        raise PermissionError("destination must start with /home/")

    r = subprocess.run(
        ["tar", "-czf", destination] + paths,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def extract_archive(archive_path: str, destination: str) -> dict[str, Any]:
    """Extract a tar.gz archive. Both paths must be under /home/."""
    if not archive_path.startswith("/home/"):
        raise PermissionError("archive_path must start with /home/")
    if not destination.startswith("/home/"):
        raise PermissionError("destination must start with /home/")

    r = subprocess.run(
        ["tar", "-xzf", archive_path, "-C", destination],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
