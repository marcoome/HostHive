"""MCP tool registry and definitions.

Each tool is registered with a name, description, JSON Schema for inputs,
and an async handler function.  The registry is consumed by the MCP server
to respond to ``tools/list`` and ``tools/call`` requests.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

log = logging.getLogger("hosthive.mcp")


# ---------------------------------------------------------------------------
# Registry data structures
# ---------------------------------------------------------------------------

@dataclass
class MCPTool:
    """Metadata + handler for a single MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, Any]]


_TOOLS: Dict[str, MCPTool] = {}


def mcp_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
):
    """Decorator that registers an async function as an MCP tool."""

    def _decorator(fn: Callable[..., Coroutine[Any, Any, Any]]):
        _TOOLS[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=fn,
        )
        return fn

    return _decorator


def list_tools() -> List[dict[str, Any]]:
    """Return the tool catalogue in MCP ``tools/list`` format."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.input_schema,
        }
        for t in _TOOLS.values()
    ]


async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke a registered tool by *name* with *arguments*."""
    tool = _TOOLS.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name!r}")
    return await tool.handler(**arguments)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_file_path(path: str) -> str:
    """Validate a file path to prevent path traversal.

    Only paths under /home or /var/log or /etc are allowed.
    """
    resolved = os.path.realpath(path)
    allowed_prefixes = ("/home/", "/var/log/", "/etc/", "/tmp/")
    if not any(resolved.startswith(p) or resolved == p.rstrip("/") for p in allowed_prefixes):
        raise PermissionError(
            f"Path {path!r} resolves to {resolved!r} which is outside allowed directories"
        )
    return resolved


def _get_agent_client():
    """Lazy import of the shared AgentClient singleton."""
    from api.core.agent_client import AgentClient
    return AgentClient()


# ---------------------------------------------------------------------------
# Domain tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="list_domains",
    description="List all domains configured on the server with details.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def list_domains() -> Any:
    agent = _get_agent_client()
    try:
        result = await agent._request("GET", "/nginx/vhosts")
        return result
    finally:
        await agent.close()


@mcp_tool(
    name="create_domain",
    description="Create a new domain (virtual host) with optional PHP version.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name to create"},
            "php_version": {"type": "string", "description": "PHP version", "default": "8.2"},
        },
        "required": ["domain"],
    },
)
async def create_domain(domain: str, php_version: str = "8.2") -> Any:
    agent = _get_agent_client()
    try:
        doc_root = f"/home/admin/{domain}/public_html"
        return await agent.create_vhost(domain, doc_root, php_version)
    finally:
        await agent.close()


@mcp_tool(
    name="delete_domain",
    description="Delete a domain and its virtual host configuration.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name to delete"},
        },
        "required": ["domain"],
    },
)
async def delete_domain(domain: str) -> Any:
    agent = _get_agent_client()
    try:
        await agent.delete_vhost(domain)
        return True
    finally:
        await agent.close()


@mcp_tool(
    name="get_domain_logs",
    description="Get the last N lines of access/error logs for a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
            "lines": {"type": "integer", "description": "Number of lines to return", "default": 100},
        },
        "required": ["domain"],
    },
)
async def get_domain_logs(domain: str, lines: int = 100) -> Any:
    agent = _get_agent_client()
    try:
        log_path = f"/var/log/nginx/{domain}.access.log"
        result = await agent.read_file(log_path)
        content = result.get("content", "")
        log_lines = content.strip().split("\n") if content else []
        return "\n".join(log_lines[-lines:])
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Database tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="list_databases",
    description="List all databases on the server.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def list_databases_tool() -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", "/database")
    finally:
        await agent.close()


@mcp_tool(
    name="create_database",
    description="Create a new MySQL or PostgreSQL database.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Database name"},
            "type": {"type": "string", "enum": ["mysql", "postgres"], "default": "mysql"},
        },
        "required": ["name"],
    },
)
async def create_database_tool(name: str, type: str = "mysql") -> Any:
    agent = _get_agent_client()
    try:
        import secrets as _secrets
        password = _secrets.token_urlsafe(16)
        return await agent.create_database(name, f"{name}_user", password, type)
    finally:
        await agent.close()


@mcp_tool(
    name="delete_database",
    description="Delete a database.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Database name"},
        },
        "required": ["name"],
    },
)
async def delete_database_tool(name: str) -> Any:
    agent = _get_agent_client()
    try:
        await agent.delete_database(name)
        return True
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# DNS tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="get_dns_zone",
    description="Get DNS zone details and records for a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
        },
        "required": ["domain"],
    },
)
async def get_dns_zone(domain: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", f"/dns/zone/{domain}")
    finally:
        await agent.close()


@mcp_tool(
    name="add_dns_record",
    description="Add a DNS record to a domain's zone.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
            "type": {"type": "string", "description": "Record type (A, AAAA, CNAME, MX, TXT, etc.)"},
            "name": {"type": "string", "description": "Record name"},
            "value": {"type": "string", "description": "Record value"},
            "ttl": {"type": "integer", "description": "TTL in seconds", "default": 3600},
        },
        "required": ["domain", "type", "name", "value"],
    },
)
async def add_dns_record(domain: str, type: str, name: str, value: str, ttl: int = 3600) -> Any:
    agent = _get_agent_client()
    try:
        return await agent.add_dns_record(domain, type, name, value, ttl)
    finally:
        await agent.close()


@mcp_tool(
    name="delete_dns_record",
    description="Delete a DNS record from a domain's zone.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
            "record_id": {"type": "string", "description": "Record ID to delete"},
        },
        "required": ["domain", "record_id"],
    },
)
async def delete_dns_record(domain: str, record_id: str) -> Any:
    agent = _get_agent_client()
    try:
        await agent.delete_dns_record(domain, record_id)
        return True
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# SSL tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="issue_ssl",
    description="Issue a Let's Encrypt SSL certificate for a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
            "email": {"type": "string", "description": "Contact email for Let's Encrypt"},
        },
        "required": ["domain", "email"],
    },
)
async def issue_ssl(domain: str, email: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent.issue_ssl(domain, email)
    finally:
        await agent.close()


@mcp_tool(
    name="get_ssl_expiry",
    description="Get the SSL certificate expiry date for a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
        },
        "required": ["domain"],
    },
)
async def get_ssl_expiry(domain: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", f"/ssl/expiry/{domain}")
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="read_file",
    description="Read the contents of a file on the server. Only files under /home, /var/log, /etc, or /tmp.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
        },
        "required": ["path"],
    },
)
async def read_file(path: str) -> Any:
    safe = _safe_file_path(path)
    agent = _get_agent_client()
    try:
        result = await agent.read_file(safe)
        return result.get("content", "")
    finally:
        await agent.close()


@mcp_tool(
    name="write_file",
    description="Write content to a file on the server. Only paths under /home or /tmp.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "File content to write"},
        },
        "required": ["path", "content"],
    },
)
async def write_file(path: str, content: str) -> Any:
    resolved = os.path.realpath(path)
    if not any(resolved.startswith(p) for p in ("/home/", "/tmp/")):
        raise PermissionError(f"Write not allowed outside /home or /tmp: {path!r}")
    agent = _get_agent_client()
    try:
        await agent.write_file(resolved, content)
        return True
    finally:
        await agent.close()


@mcp_tool(
    name="list_directory",
    description="List directory contents on the server. Only paths under /home, /var/log, /etc, or /tmp.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the directory"},
        },
        "required": ["path"],
    },
)
async def list_directory(path: str) -> Any:
    safe = _safe_file_path(path)
    agent = _get_agent_client()
    try:
        return await agent.list_files(safe)
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Server tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="get_server_stats",
    description="Get server resource usage: CPU, RAM, disk, network, and load averages.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def get_server_stats() -> Any:
    agent = _get_agent_client()
    try:
        return await agent.get_server_stats()
    finally:
        await agent.close()


@mcp_tool(
    name="get_service_status",
    description="Get status information for a specific system service.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name (e.g., nginx, mysql, php8.2-fpm)"},
        },
        "required": ["service"],
    },
)
async def get_service_status(service: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", f"/service/{service}/status")
    finally:
        await agent.close()


@mcp_tool(
    name="restart_service",
    description="Restart a system service (nginx, mysql, php-fpm, etc.).",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name to restart"},
        },
        "required": ["service"],
    },
)
async def restart_service(service: str) -> Any:
    agent = _get_agent_client()
    try:
        await agent.service_action(service, "restart")
        return True
    finally:
        await agent.close()


@mcp_tool(
    name="get_logs",
    description="Get the last N lines of logs for a system service.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "lines": {"type": "integer", "description": "Number of lines", "default": 200},
        },
        "required": ["service"],
    },
)
async def get_logs(service: str, lines: int = 200) -> Any:
    agent = _get_agent_client()
    try:
        log_path = f"/var/log/{service}/{service}.log"
        result = await agent.read_file(log_path)
        content = result.get("content", "")
        log_lines = content.strip().split("\n") if content else []
        return "\n".join(log_lines[-lines:])
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Email tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="create_mailbox",
    description="Create a new email mailbox.",
    input_schema={
        "type": "object",
        "properties": {
            "address": {"type": "string", "description": "Email address (user@domain.com)"},
            "quota_mb": {"type": "integer", "description": "Mailbox quota in MB", "default": 1024},
        },
        "required": ["address"],
    },
)
async def create_mailbox(address: str, quota_mb: int = 1024) -> Any:
    import secrets as _secrets
    agent = _get_agent_client()
    try:
        password = _secrets.token_urlsafe(16)
        result = await agent.create_mailbox(address, password, quota_mb)
        result["initial_password"] = password
        return result
    finally:
        await agent.close()


@mcp_tool(
    name="list_mailboxes",
    description="List all mailboxes for a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name"},
        },
        "required": ["domain"],
    },
)
async def list_mailboxes(domain: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", f"/mail/mailboxes/{domain}")
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Backup tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="create_backup",
    description="Create a server backup (full or incremental).",
    input_schema={
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["full", "incremental"], "default": "full"},
        },
        "required": [],
    },
)
async def create_backup_tool(type: str = "full") -> Any:
    agent = _get_agent_client()
    try:
        return await agent.create_backup("admin", type)
    finally:
        await agent.close()


@mcp_tool(
    name="list_backups",
    description="List all available backups.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def list_backups_tool() -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", "/backup/list/admin")
    finally:
        await agent.close()


@mcp_tool(
    name="restore_backup",
    description="Restore a backup by its ID / filename.",
    input_schema={
        "type": "object",
        "properties": {
            "backup_id": {"type": "string", "description": "Backup file identifier"},
        },
        "required": ["backup_id"],
    },
)
async def restore_backup_tool(backup_id: str) -> Any:
    agent = _get_agent_client()
    try:
        await agent.restore_backup(backup_id)
        return True
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Security tools
# ---------------------------------------------------------------------------

@mcp_tool(
    name="ban_ip",
    description="Ban an IP address via the firewall.",
    input_schema={
        "type": "object",
        "properties": {
            "ip": {"type": "string", "description": "IP address to ban"},
            "reason": {"type": "string", "description": "Reason for the ban"},
        },
        "required": ["ip", "reason"],
    },
)
async def ban_ip(ip: str, reason: str) -> Any:
    import ipaddress as _ipaddress
    _ipaddress.ip_address(ip)  # validate
    agent = _get_agent_client()
    try:
        await agent.firewall_add_rule({"port": "any", "protocol": "tcp", "action": "deny", "source": ip})
        log.info("Banned IP %s: %s", ip, reason)
        return True
    finally:
        await agent.close()


@mcp_tool(
    name="get_firewall_rules",
    description="List all firewall rules.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def get_firewall_rules() -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("GET", "/system/firewall")
    finally:
        await agent.close()


@mcp_tool(
    name="run_security_scan",
    description="Run a basic security scan of the server.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def run_security_scan() -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("POST", "/system/security-scan")
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# AI tools (proxied; only available when AI module is enabled)
# ---------------------------------------------------------------------------

@mcp_tool(
    name="analyze_logs",
    description="Use AI to analyze logs for a service and identify issues.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name to analyze"},
        },
        "required": ["service"],
    },
)
async def analyze_logs(service: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("POST", "/ai/analyze-logs", json_body={"service": service})
    finally:
        await agent.close()


@mcp_tool(
    name="optimize_nginx",
    description="Get AI-powered Nginx optimization suggestions for a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Domain name to optimize"},
        },
        "required": ["domain"],
    },
)
async def optimize_nginx(domain: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("POST", "/ai/optimize-nginx", json_body={"domain": domain})
    finally:
        await agent.close()


@mcp_tool(
    name="install_app",
    description="Install a web application (WordPress, etc.) on a domain.",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Target domain"},
            "app": {"type": "string", "description": "Application name (wordpress, joomla, etc.)"},
        },
        "required": ["domain", "app"],
    },
)
async def install_app(domain: str, app: str) -> Any:
    agent = _get_agent_client()
    try:
        return await agent._request("POST", "/ai/install-app", json_body={"domain": domain, "app": app})
    finally:
        await agent.close()
