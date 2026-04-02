#!/usr/bin/env python3
"""
HostHive CLI -- manage your server from the command line.

Usage: hosthive [command] [subcommand] [options]

Commands:
  hosthive domain list
  hosthive domain add example.com --php 8.2
  hosthive domain delete example.com
  hosthive domain ssl example.com

  hosthive db list
  hosthive db create mydb --type mysql
  hosthive db delete mydb

  hosthive user list
  hosthive user create admin --email admin@example.com --package default
  hosthive user suspend username

  hosthive email list example.com
  hosthive email create user@example.com --quota 1024

  hosthive dns list example.com
  hosthive dns add example.com A www 1.2.3.4

  hosthive backup create --user admin
  hosthive backup list
  hosthive backup restore backup_id

  hosthive server status
  hosthive server stats
  hosthive server restart nginx
  hosthive server firewall list
  hosthive server firewall add 8080 tcp allow

  hosthive ssl list
  hosthive ssl issue example.com
  hosthive ssl renew example.com

  hosthive app install wordpress example.com
  hosthive app list

  hosthive docker list
  hosthive docker deploy nginx:latest --name web --port 80:80
  hosthive docker stop container_id

  hosthive config show
  hosthive config set KEY value
  hosthive version
  hosthive update
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SECRETS_FILE = Path("/opt/novapanel/config/secrets.env")
CONFIG_FILE = Path("/opt/novapanel/config/cli.env")
API_BASE = "http://127.0.0.1:8000/api/v1"

# ---------------------------------------------------------------------------
# Colour helpers (ANSI codes, no external deps)
# ---------------------------------------------------------------------------

_NO_COLOR = os.environ.get("NO_COLOR") is not None or not sys.stdout.isatty()

_GREEN = "" if _NO_COLOR else "\033[0;32m"
_RED = "" if _NO_COLOR else "\033[0;31m"
_YELLOW = "" if _NO_COLOR else "\033[1;33m"
_CYAN = "" if _NO_COLOR else "\033[0;36m"
_BOLD = "" if _NO_COLOR else "\033[1m"
_RESET = "" if _NO_COLOR else "\033[0m"


def _ok(msg: str) -> None:
    print(f"{_GREEN}[OK]{_RESET} {msg}")


def _err(msg: str) -> None:
    print(f"{_RED}[ERROR]{_RESET} {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"{_YELLOW}[WARN]{_RESET} {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"{_CYAN}[INFO]{_RESET} {msg}")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _load_token() -> str:
    """Load API key / token from secrets file or environment."""
    # 1. Environment override
    token = os.environ.get("HOSTHIVE_API_TOKEN", "")
    if token:
        return token

    # 2. CLI config file
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "API_TOKEN":
                return value.strip().strip("'\"")

    # 3. Secrets env (admin scenario)
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "API_TOKEN":
                return value.strip().strip("'\"")

    return ""


# ---------------------------------------------------------------------------
# HTTP client (stdlib only + optional httpx)
# ---------------------------------------------------------------------------


def _request(
    method: str,
    path: str,
    data: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Make an HTTP request to the HostHive API.

    Tries httpx first (better ergonomics), falls back to urllib.
    """
    token = _load_token()
    url = f"{API_BASE}{path}"

    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body_bytes = json.dumps(data).encode("utf-8") if data else None

    # Try httpx
    try:
        import httpx  # noqa: F811

        with httpx.Client(timeout=30.0) as client:
            resp = client.request(
                method,
                url,
                headers=headers,
                content=body_bytes,
            )
            resp.raise_for_status()
            return resp.json()
    except ImportError:
        pass
    except Exception as exc:
        # If httpx is available but request failed, report it
        try:
            # httpx HTTPStatusError has a response attribute
            resp_body = exc.response.json()  # type: ignore[union-attr]
            return resp_body
        except Exception:
            _err(f"Request failed: {exc}")
            sys.exit(1)

    # Fallback: stdlib urllib
    req = Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            return body
        except Exception:
            _err(f"HTTP {exc.code}: {exc.reason}")
            sys.exit(1)
    except URLError as exc:
        _err(f"Cannot connect to API at {API_BASE}: {exc.reason}")
        _err("Is the HostHive API running?  (systemctl status novapanel-api)")
        sys.exit(1)


def _get(path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
    return _request("GET", path, params=params)


def _post(path: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return _request("POST", path, data=data or {})


def _put(path: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return _request("PUT", path, data=data or {})


def _delete(path: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return _request("DELETE", path, data=data or {})


# ---------------------------------------------------------------------------
# ASCII table rendering (no external deps)
# ---------------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a simple ASCII table."""
    if not rows:
        _info("No results.")
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
            else:
                widths.append(len(str(cell)))

    # Build format string
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    sep = "  ".join("-" * w for w in widths)

    print(f"{_BOLD}{fmt.format(*headers)}{_RESET}")
    print(sep)
    for row in rows:
        # Pad row to match headers length
        padded = list(row) + [""] * (len(headers) - len(row))
        print(fmt.format(*padded[:len(headers)]))


# ---------------------------------------------------------------------------
# Domain commands
# ---------------------------------------------------------------------------


def cmd_domain(args: argparse.Namespace) -> None:
    action = args.domain_action

    if action == "list":
        resp = _get("/domains")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["ID", "Domain", "PHP", "SSL", "Active"]
            rows = [
                [
                    str(d.get("id", ""))[:8],
                    d.get("domain_name", ""),
                    d.get("php_version", ""),
                    str(d.get("ssl_enabled", False)),
                    str(d.get("is_active", True)),
                ]
                for d in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "add":
        data: dict[str, Any] = {"domain_name": args.name}
        if args.php:
            data["php_version"] = args.php
        resp = _post("/domains", data)
        if resp.get("id") or resp.get("domain_name"):
            _ok(f"Domain {args.name} created.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    elif action == "delete":
        resp = _delete(f"/domains/{args.name}")
        if resp.get("detail", "") == "Domain not found.":
            _err(f"Domain {args.name} not found.")
        else:
            _ok(f"Domain {args.name} deleted.")

    elif action == "ssl":
        resp = _post(f"/ssl/issue", {"domain": args.name})
        if resp.get("ok") or resp.get("id"):
            _ok(f"SSL issued for {args.name}.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    else:
        _err(f"Unknown domain action: {action}")


# ---------------------------------------------------------------------------
# Database commands
# ---------------------------------------------------------------------------


def cmd_db(args: argparse.Namespace) -> None:
    action = args.db_action

    if action == "list":
        resp = _get("/databases")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["Name", "Type", "User", "Size"]
            rows = [
                [
                    d.get("db_name", ""),
                    d.get("db_type", "mysql"),
                    d.get("db_user", ""),
                    d.get("size", "N/A"),
                ]
                for d in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "create":
        db_type = getattr(args, "type", "mysql") or "mysql"
        resp = _post("/databases", {
            "db_name": args.name,
            "db_type": db_type,
        })
        if resp.get("id") or resp.get("db_name"):
            _ok(f"Database {args.name} ({db_type}) created.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    elif action == "delete":
        resp = _delete(f"/databases/{args.name}")
        _ok(f"Database {args.name} deleted.")

    else:
        _err(f"Unknown db action: {action}")


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------


def cmd_user(args: argparse.Namespace) -> None:
    action = args.user_action

    if action == "list":
        resp = _get("/users")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["ID", "Username", "Email", "Role", "Active", "Suspended"]
            rows = [
                [
                    str(u.get("id", ""))[:8],
                    u.get("username", ""),
                    u.get("email", ""),
                    u.get("role", ""),
                    str(u.get("is_active", True)),
                    str(u.get("is_suspended", False)),
                ]
                for u in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "create":
        data: dict[str, Any] = {"username": args.name}
        if args.email:
            data["email"] = args.email
        if args.package:
            data["package"] = args.package
        resp = _post("/users", data)
        if resp.get("id") or resp.get("username"):
            _ok(f"User {args.name} created.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    elif action == "suspend":
        resp = _put(f"/users/{args.name}/suspend")
        _ok(f"User {args.name} suspended.")

    else:
        _err(f"Unknown user action: {action}")


# ---------------------------------------------------------------------------
# Email commands
# ---------------------------------------------------------------------------


def cmd_email(args: argparse.Namespace) -> None:
    action = args.email_action

    if action == "list":
        resp = _get("/email", params={"domain": args.domain} if args.domain else None)
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["Address", "Quota (MB)", "Used (MB)"]
            rows = [
                [
                    e.get("address", ""),
                    str(e.get("quota_mb", "")),
                    str(e.get("used_mb", "N/A")),
                ]
                for e in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "create":
        data: dict[str, Any] = {"address": args.address}
        if args.quota:
            data["quota_mb"] = args.quota
        resp = _post("/email", data)
        if resp.get("id") or resp.get("address"):
            _ok(f"Mailbox {args.address} created.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    else:
        _err(f"Unknown email action: {action}")


# ---------------------------------------------------------------------------
# DNS commands
# ---------------------------------------------------------------------------


def cmd_dns(args: argparse.Namespace) -> None:
    action = args.dns_action

    if action == "list":
        resp = _get(f"/dns/{args.domain}")
        items = resp.get("records", resp.get("data", []))
        if isinstance(items, list):
            headers = ["ID", "Type", "Name", "Value", "TTL"]
            rows = [
                [
                    str(r.get("id", ""))[:8],
                    r.get("record_type", r.get("type", "")),
                    r.get("name", ""),
                    r.get("value", ""),
                    str(r.get("ttl", 3600)),
                ]
                for r in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "add":
        resp = _post(f"/dns/{args.domain}/records", {
            "record_type": args.record_type,
            "name": args.name,
            "value": args.value,
        })
        if resp.get("id") or resp.get("ok"):
            _ok(f"DNS record added to {args.domain}.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    else:
        _err(f"Unknown dns action: {action}")


# ---------------------------------------------------------------------------
# Backup commands
# ---------------------------------------------------------------------------


def cmd_backup(args: argparse.Namespace) -> None:
    action = args.backup_action

    if action == "list":
        resp = _get("/backups")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["ID", "User", "Type", "Size", "Created"]
            rows = [
                [
                    str(b.get("id", ""))[:8],
                    b.get("username", ""),
                    b.get("backup_type", "full"),
                    b.get("size", "N/A"),
                    b.get("created_at", ""),
                ]
                for b in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "create":
        data: dict[str, Any] = {}
        if args.user:
            data["username"] = args.user
        resp = _post("/backups", data)
        _ok(f"Backup created: {resp.get('id', resp.get('backup_file', 'OK'))}")

    elif action == "restore":
        resp = _post(f"/backups/{args.backup_id}/restore")
        _ok(f"Backup {args.backup_id} restore initiated.")

    else:
        _err(f"Unknown backup action: {action}")


# ---------------------------------------------------------------------------
# Server commands
# ---------------------------------------------------------------------------


def cmd_server(args: argparse.Namespace) -> None:
    action = args.server_action

    if action == "status":
        resp = _get("/server/status")
        print(json.dumps(resp, indent=2))

    elif action == "stats":
        resp = _get("/server/stats")
        data = resp.get("data", resp)
        if isinstance(data, dict):
            load = data.get("load_average", {})
            mem = data.get("memory", {})
            disk = data.get("disk", {})

            print(f"\n{_BOLD}Server Statistics{_RESET}")
            print("-" * 40)
            if load:
                print(f"  Load Average: {load.get('1min', 'N/A')} / {load.get('5min', 'N/A')} / {load.get('15min', 'N/A')}")
            if data.get("cpu_percent") is not None:
                print(f"  CPU Usage:    {data['cpu_percent']}%")
            if mem:
                print(f"  Memory:       {mem.get('percent', 'N/A')}% used ({mem.get('used_kb', 0) // 1024} MB / {mem.get('total_kb', 0) // 1024} MB)")
            if disk:
                print(f"  Disk:         {disk.get('percent', 'N/A')} used")
            if data.get("uptime_seconds") is not None:
                hours = int(data["uptime_seconds"]) // 3600
                days = hours // 24
                hours = hours % 24
                print(f"  Uptime:       {days}d {hours}h")
            print()
        else:
            print(json.dumps(resp, indent=2))

    elif action == "restart":
        if not args.service:
            _err("Specify a service name: hosthive server restart nginx")
            sys.exit(1)
        resp = _post("/server/services/restart", {"name": args.service})
        _ok(f"Service {args.service} restarted.")

    elif action == "firewall":
        fw_action = args.fw_action if hasattr(args, "fw_action") and args.fw_action else "list"

        if fw_action == "list":
            resp = _get("/server/firewall")
            rules = resp.get("rules", resp.get("data", {}).get("rules", []))
            if isinstance(rules, list):
                headers = ["ID", "Rule"]
                rows = [[str(r.get("id", "")), r.get("rule", "")] for r in rules]
                _table(headers, rows)
            else:
                print(json.dumps(resp, indent=2))

        elif fw_action == "add":
            resp = _post("/server/firewall", {
                "port": args.port,
                "protocol": args.protocol,
                "action": args.fw_rule_action,
            })
            _ok(f"Firewall rule added: {args.fw_rule_action} {args.port}/{args.protocol}")

        else:
            _err(f"Unknown firewall action: {fw_action}")

    else:
        _err(f"Unknown server action: {action}")


# ---------------------------------------------------------------------------
# SSL commands
# ---------------------------------------------------------------------------


def cmd_ssl(args: argparse.Namespace) -> None:
    action = args.ssl_action

    if action == "list":
        resp = _get("/ssl")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["Domain", "Issuer", "Expires", "Status"]
            rows = [
                [
                    c.get("domain", ""),
                    c.get("issuer", "Let's Encrypt"),
                    c.get("expires_at", ""),
                    c.get("status", "active"),
                ]
                for c in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "issue":
        resp = _post("/ssl/issue", {"domain": args.domain})
        if resp.get("ok") or resp.get("id"):
            _ok(f"SSL certificate issued for {args.domain}.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    elif action == "renew":
        resp = _post(f"/ssl/{args.domain}/renew")
        _ok(f"SSL certificate renewed for {args.domain}.")

    else:
        _err(f"Unknown ssl action: {action}")


# ---------------------------------------------------------------------------
# App commands
# ---------------------------------------------------------------------------


def cmd_app(args: argparse.Namespace) -> None:
    action = args.app_action

    if action == "list":
        resp = _get("/apps")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["Domain", "Runtime", "Status", "Port", "PID"]
            rows = [
                [
                    a.get("domain", ""),
                    a.get("runtime", ""),
                    a.get("status", ""),
                    str(a.get("port", "")),
                    str(a.get("pid", "")),
                ]
                for a in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "install":
        resp = _post("/apps/deploy", {
            "app_name": args.app_name,
            "domain": args.domain,
        })
        if resp.get("ok") or resp.get("id"):
            _ok(f"App {args.app_name} installed on {args.domain}.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    else:
        _err(f"Unknown app action: {action}")


# ---------------------------------------------------------------------------
# Docker commands
# ---------------------------------------------------------------------------


def cmd_docker(args: argparse.Namespace) -> None:
    action = args.docker_action

    if action == "list":
        resp = _get("/docker/containers")
        items = resp.get("items", resp.get("data", []))
        if isinstance(items, list):
            headers = ["ID", "Name", "Image", "Status", "Ports"]
            rows = [
                [
                    str(c.get("id", ""))[:12],
                    c.get("name", ""),
                    c.get("image", ""),
                    c.get("status", ""),
                    c.get("ports", ""),
                ]
                for c in items
            ]
            _table(headers, rows)
        else:
            print(json.dumps(resp, indent=2))

    elif action == "deploy":
        data: dict[str, Any] = {"image": args.image}
        if args.name:
            data["name"] = args.name
        if args.port:
            data["ports"] = args.port
        resp = _post("/docker/containers", data)
        if resp.get("ok") or resp.get("id"):
            _ok(f"Container deployed from {args.image}.")
        else:
            _err(f"Failed: {resp.get('detail', resp)}")

    elif action == "stop":
        resp = _post(f"/docker/containers/{args.container_id}/stop")
        _ok(f"Container {args.container_id} stopped.")

    else:
        _err(f"Unknown docker action: {action}")


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------


def cmd_config(args: argparse.Namespace) -> None:
    action = args.config_action

    if action == "show":
        if CONFIG_FILE.exists():
            print(f"\n{_BOLD}CLI Configuration{_RESET} ({CONFIG_FILE})")
            print("-" * 40)
            for line in CONFIG_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                # Mask sensitive values
                if "TOKEN" in key.upper() or "SECRET" in key.upper() or "PASSWORD" in key.upper():
                    value = value[:4] + "****" if len(value) > 4 else "****"
                print(f"  {key.strip()} = {value.strip()}")
            print()
        else:
            _info(f"No CLI config found at {CONFIG_FILE}")
            _info("Set values with: hosthive config set KEY value")

    elif action == "set":
        key = args.key
        value = args.value

        # Read existing config
        existing: dict[str, str] = {}
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

        existing[key] = value

        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# HostHive CLI configuration\n"]
        for k, v in sorted(existing.items()):
            lines.append(f"{k}={v}\n")
        CONFIG_FILE.write_text("".join(lines))
        os.chmod(str(CONFIG_FILE), 0o600)
        _ok(f"Set {key} in {CONFIG_FILE}")

    else:
        _err(f"Unknown config action: {action}")


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def cmd_version(_args: argparse.Namespace) -> None:
    print(f"HostHive CLI v{__version__}")


def cmd_update(_args: argparse.Namespace) -> None:
    _info("Checking for updates...")
    resp = _get("/health")
    api_version = resp.get("version", "unknown")
    print(f"  CLI version: {__version__}")
    print(f"  API version: {api_version}")
    _info("To update HostHive, run: apt update && apt upgrade novapanel")
    _info("Or pull the latest from the repository.")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hosthive",
        description="HostHive CLI -- manage your hosting server from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api-url", default=None, help="Override API base URL")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- domain ---
    domain_p = subparsers.add_parser("domain", help="Manage domains")
    domain_sub = domain_p.add_subparsers(dest="domain_action")

    domain_sub.add_parser("list", help="List all domains")

    domain_add = domain_sub.add_parser("add", help="Add a domain")
    domain_add.add_argument("name", help="Domain name (e.g. example.com)")
    domain_add.add_argument("--php", default="8.2", help="PHP version (default: 8.2)")

    domain_del = domain_sub.add_parser("delete", help="Delete a domain")
    domain_del.add_argument("name", help="Domain name")

    domain_ssl = domain_sub.add_parser("ssl", help="Issue SSL for a domain")
    domain_ssl.add_argument("name", help="Domain name")

    # --- db ---
    db_p = subparsers.add_parser("db", help="Manage databases")
    db_sub = db_p.add_subparsers(dest="db_action")

    db_sub.add_parser("list", help="List all databases")

    db_create = db_sub.add_parser("create", help="Create a database")
    db_create.add_argument("name", help="Database name")
    db_create.add_argument("--type", default="mysql", choices=["mysql", "postgres"], help="DB type")

    db_del = db_sub.add_parser("delete", help="Delete a database")
    db_del.add_argument("name", help="Database name")

    # --- user ---
    user_p = subparsers.add_parser("user", help="Manage users")
    user_sub = user_p.add_subparsers(dest="user_action")

    user_sub.add_parser("list", help="List all users")

    user_create = user_sub.add_parser("create", help="Create a user")
    user_create.add_argument("name", help="Username")
    user_create.add_argument("--email", required=True, help="Email address")
    user_create.add_argument("--package", default="default", help="Hosting package")

    user_suspend = user_sub.add_parser("suspend", help="Suspend a user")
    user_suspend.add_argument("name", help="Username")

    # --- email ---
    email_p = subparsers.add_parser("email", help="Manage email accounts")
    email_sub = email_p.add_subparsers(dest="email_action")

    email_list = email_sub.add_parser("list", help="List email accounts")
    email_list.add_argument("domain", nargs="?", default=None, help="Filter by domain")

    email_create = email_sub.add_parser("create", help="Create a mailbox")
    email_create.add_argument("address", help="Email address (user@domain.com)")
    email_create.add_argument("--quota", type=int, default=1024, help="Quota in MB")

    # --- dns ---
    dns_p = subparsers.add_parser("dns", help="Manage DNS records")
    dns_sub = dns_p.add_subparsers(dest="dns_action")

    dns_list = dns_sub.add_parser("list", help="List DNS records")
    dns_list.add_argument("domain", help="Domain name")

    dns_add = dns_sub.add_parser("add", help="Add a DNS record")
    dns_add.add_argument("domain", help="Domain name")
    dns_add.add_argument("record_type", help="Record type (A, AAAA, CNAME, MX, TXT)")
    dns_add.add_argument("name", help="Record name (e.g. www)")
    dns_add.add_argument("value", help="Record value (e.g. 1.2.3.4)")

    # --- backup ---
    backup_p = subparsers.add_parser("backup", help="Manage backups")
    backup_sub = backup_p.add_subparsers(dest="backup_action")

    backup_sub.add_parser("list", help="List backups")

    backup_create = backup_sub.add_parser("create", help="Create a backup")
    backup_create.add_argument("--user", default=None, help="Username to backup")

    backup_restore = backup_sub.add_parser("restore", help="Restore a backup")
    backup_restore.add_argument("backup_id", help="Backup ID")

    # --- server ---
    server_p = subparsers.add_parser("server", help="Server management")
    server_sub = server_p.add_subparsers(dest="server_action")

    server_sub.add_parser("status", help="Show server status")
    server_sub.add_parser("stats", help="Show server statistics")

    server_restart = server_sub.add_parser("restart", help="Restart a service")
    server_restart.add_argument("service", help="Service name (nginx, mysql, etc.)")

    server_fw = server_sub.add_parser("firewall", help="Firewall management")
    fw_sub = server_fw.add_subparsers(dest="fw_action")

    fw_sub.add_parser("list", help="List firewall rules")

    fw_add = fw_sub.add_parser("add", help="Add a firewall rule")
    fw_add.add_argument("port", help="Port number")
    fw_add.add_argument("protocol", nargs="?", default="tcp", help="Protocol (tcp/udp)")
    fw_add.add_argument("fw_rule_action", nargs="?", default="allow", help="Action (allow/deny)")

    # --- ssl ---
    ssl_p = subparsers.add_parser("ssl", help="Manage SSL certificates")
    ssl_sub = ssl_p.add_subparsers(dest="ssl_action")

    ssl_sub.add_parser("list", help="List SSL certificates")

    ssl_issue = ssl_sub.add_parser("issue", help="Issue a certificate")
    ssl_issue.add_argument("domain", help="Domain name")

    ssl_renew = ssl_sub.add_parser("renew", help="Renew a certificate")
    ssl_renew.add_argument("domain", help="Domain name")

    # --- app ---
    app_p = subparsers.add_parser("app", help="Manage web applications")
    app_sub = app_p.add_subparsers(dest="app_action")

    app_sub.add_parser("list", help="List running apps")

    app_install = app_sub.add_parser("install", help="Install an app")
    app_install.add_argument("app_name", help="App name (wordpress, etc.)")
    app_install.add_argument("domain", help="Domain to install on")

    # --- docker ---
    docker_p = subparsers.add_parser("docker", help="Manage Docker containers")
    docker_sub = docker_p.add_subparsers(dest="docker_action")

    docker_sub.add_parser("list", help="List containers")

    docker_deploy = docker_sub.add_parser("deploy", help="Deploy a container")
    docker_deploy.add_argument("image", help="Docker image (e.g. nginx:latest)")
    docker_deploy.add_argument("--name", default=None, help="Container name")
    docker_deploy.add_argument("--port", default=None, help="Port mapping (e.g. 80:80)")

    docker_stop = docker_sub.add_parser("stop", help="Stop a container")
    docker_stop.add_argument("container_id", help="Container ID or name")

    # --- config ---
    config_p = subparsers.add_parser("config", help="CLI configuration")
    config_sub = config_p.add_subparsers(dest="config_action")

    config_sub.add_parser("show", help="Show current configuration")

    config_set = config_sub.add_parser("set", help="Set a configuration value")
    config_set.add_argument("key", help="Configuration key")
    config_set.add_argument("value", help="Configuration value")

    # --- version ---
    subparsers.add_parser("version", help="Show CLI version")

    # --- update ---
    subparsers.add_parser("update", help="Check for updates")

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Any] = {
    "domain": cmd_domain,
    "db": cmd_db,
    "user": cmd_user,
    "email": cmd_email,
    "dns": cmd_dns,
    "backup": cmd_backup,
    "server": cmd_server,
    "ssl": cmd_ssl,
    "app": cmd_app,
    "docker": cmd_docker,
    "config": cmd_config,
    "version": cmd_version,
    "update": cmd_update,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Override API URL if specified
    global API_BASE
    if args.api_url:
        API_BASE = args.api_url.rstrip("/")

    handler = _DISPATCH.get(args.command)
    if handler is None:
        _err(f"Unknown command: {args.command}")
        parser.print_help()
        sys.exit(1)

    # Check that subcommand was provided for commands that need one
    sub_key = f"{args.command}_action"
    if hasattr(args, sub_key) and getattr(args, sub_key) is None:
        # Print sub-parser help
        _err(f"Missing subcommand for '{args.command}'. See: hosthive {args.command} --help")
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
