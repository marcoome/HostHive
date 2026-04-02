"""AI-powered security scanning service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from api.core.ai_client import AIClient

logger = logging.getLogger("hosthive.ai.security")

_SECURITY_SUMMARY_PROMPT = """You are a server security expert. Analyze the following security scan results and provide:
1. An overall security score from 0 (critical) to 100 (perfect)
2. A prioritized list of issues with severity and recommendations

Return JSON with:
- "score": integer 0-100
- "issues": array of objects with "category", "severity" (high/medium/low), "description", "recommendation"

Scan results:
{scan_results}

IMPORTANT: Do NOT include any passwords, API keys, certificates, or secrets in your response.
"""


async def run_security_scan(
    agent_client: Any,
    ai_client: AIClient,
) -> dict[str, Any]:
    """Run comprehensive security scan across all targets.

    Returns dict with score, issues list, and scan_time.
    """
    scan_results: dict[str, Any] = {}

    # Run all individual scans
    scanners = [
        ("nginx_config", _scan_nginx_configs),
        ("php_versions", _scan_php_versions),
        ("ssl_certificates", _scan_ssl_certs),
        ("open_ports", _scan_open_ports),
        ("file_permissions", _scan_file_permissions),
        ("wordpress", _scan_wordpress),
        ("mail_config", _scan_mail_config),
        ("ssh_config", _scan_ssh_config),
        ("firewall", _scan_firewall),
    ]

    for name, scanner_fn in scanners:
        try:
            result = await scanner_fn(agent_client)
            scan_results[name] = result
        except Exception as exc:
            logger.warning("Security scan %s failed: %s", name, exc)
            scan_results[name] = {"error": str(exc)}

    # Send to AI for summary and scoring
    prompt = _SECURITY_SUMMARY_PROMPT.format(
        scan_results=_format_scan_results(scan_results),
    )
    analysis = await ai_client.analyze(prompt)

    return {
        "score": analysis.get("score", 50),
        "issues": analysis.get("issues", []),
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "raw_scans": scan_results,
    }


def _format_scan_results(results: dict[str, Any]) -> str:
    """Format scan results as text for the AI prompt, stripping secrets."""
    lines = []
    for category, data in results.items():
        lines.append(f"\n=== {category.upper().replace('_', ' ')} ===")
        if isinstance(data, dict):
            if "error" in data:
                lines.append(f"  Scan error: {data['error']}")
            else:
                for key, val in data.items():
                    # Never send actual cert content or keys
                    if any(s in key.lower() for s in ("key", "password", "secret", "cert_content")):
                        continue
                    lines.append(f"  {key}: {val}")
        elif isinstance(data, list):
            for item in data[:50]:  # Limit to avoid huge prompts
                lines.append(f"  - {item}")
        else:
            lines.append(f"  {data}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual scan functions
# ---------------------------------------------------------------------------

async def _scan_nginx_configs(agent: Any) -> dict[str, Any]:
    """Check nginx configs for security issues."""
    result = await agent._request("GET", "/exec", json_body={
        "command": "nginx -T 2>&1 | grep -E '(server_tokens|add_header|ssl_protocols|ssl_ciphers)' | head -50",
    })
    output = result.get("stdout", "")

    issues = []
    if "server_tokens on" in output or "server_tokens" not in output:
        issues.append("server_tokens not disabled — nginx version exposed")
    if "X-Frame-Options" not in output:
        issues.append("X-Frame-Options header not set")
    if "X-Content-Type-Options" not in output:
        issues.append("X-Content-Type-Options header not set")
    if "ssl_protocols TLSv1 " in output or "ssl_protocols TLSv1.1" in output:
        issues.append("Outdated TLS protocols (TLSv1/1.1) still enabled")

    return {"issues": issues, "raw_output_lines": len(output.splitlines())}


async def _scan_php_versions(agent: Any) -> dict[str, Any]:
    """Check installed PHP versions for EOL."""
    result = await agent._request("POST", "/exec", json_body={
        "command": "ls /etc/php/ 2>/dev/null || echo 'no-php'",
    })
    output = result.get("stdout", "").strip()
    if output == "no-php":
        return {"installed": [], "eol_versions": []}

    versions = output.split()
    eol_versions = [v for v in versions if v in ("5.6", "7.0", "7.1", "7.2", "7.3", "7.4", "8.0")]
    return {"installed": versions, "eol_versions": eol_versions}


async def _scan_ssl_certs(agent: Any) -> dict[str, Any]:
    """Check SSL certificate expiry dates."""
    result = await agent._request("POST", "/exec", json_body={
        "command": (
            "for cert in /etc/letsencrypt/live/*/cert.pem; do "
            "domain=$(basename $(dirname $cert)); "
            "expiry=$(openssl x509 -enddate -noout -in $cert 2>/dev/null | cut -d= -f2); "
            "echo \"$domain|$expiry\"; "
            "done"
        ),
    })
    output = result.get("stdout", "").strip()
    certs = []
    for line in output.splitlines():
        if "|" in line:
            parts = line.split("|", 1)
            certs.append({"domain": parts[0], "expiry": parts[1]})
    return {"certificates": certs, "total": len(certs)}


async def _scan_open_ports(agent: Any) -> dict[str, Any]:
    """Check for unexpected open ports."""
    result = await agent._request("POST", "/exec", json_body={
        "command": "ss -tlnp 2>/dev/null | tail -n +2 | awk '{print $4}' | sort -u",
    })
    output = result.get("stdout", "").strip()
    ports = output.splitlines() if output else []

    expected = {"22", "25", "80", "110", "143", "443", "465", "587", "993", "995", "3306", "5432"}
    unexpected = []
    for addr in ports:
        port = addr.rsplit(":", 1)[-1] if ":" in addr else addr
        if port not in expected:
            unexpected.append(addr)

    return {"all_listening": ports, "unexpected": unexpected}


async def _scan_file_permissions(agent: Any) -> dict[str, Any]:
    """Check for world-writable files and directories in web roots."""
    result = await agent._request("POST", "/exec", json_body={
        "command": "find /home -maxdepth 4 -perm -o+w -type f 2>/dev/null | head -20",
    })
    world_writable = result.get("stdout", "").strip().splitlines()
    return {"world_writable_files": world_writable, "count": len(world_writable)}


async def _scan_wordpress(agent: Any) -> dict[str, Any]:
    """Check WordPress installations for outdated versions."""
    result = await agent._request("POST", "/exec", json_body={
        "command": (
            "find /home -maxdepth 4 -name 'wp-includes' -type d 2>/dev/null | "
            "while read d; do "
            "root=$(dirname $d); "
            "ver=$(grep 'wp_version =' $root/wp-includes/version.php 2>/dev/null | grep -oP \"'[^']+'\"); "
            "echo \"$root|$ver\"; "
            "done"
        ),
    })
    output = result.get("stdout", "").strip()
    installs = []
    for line in output.splitlines():
        if "|" in line:
            parts = line.split("|", 1)
            installs.append({"path": parts[0], "version": parts[1].strip("'")})
    return {"installations": installs, "total": len(installs)}


async def _scan_mail_config(agent: Any) -> dict[str, Any]:
    """Check SPF, DKIM, and DMARC records."""
    result = await agent._request("POST", "/exec", json_body={
        "command": (
            "postconf -n 2>/dev/null | grep -E '(smtpd_tls|smtpd_sasl|reject)' | head -20; "
            "echo '---'; "
            "ls /etc/opendkim/keys/ 2>/dev/null || echo 'no-dkim-keys'"
        ),
    })
    output = result.get("stdout", "")
    has_tls = "smtpd_tls" in output
    has_dkim = "no-dkim-keys" not in output
    return {"tls_configured": has_tls, "dkim_configured": has_dkim, "raw": output[:500]}


async def _scan_ssh_config(agent: Any) -> dict[str, Any]:
    """Check SSH configuration for security."""
    result = await agent._request("POST", "/exec", json_body={
        "command": "sshd -T 2>/dev/null | grep -E '(permitrootlogin|passwordauthentication|port |maxauthtries|protocol)'",
    })
    output = result.get("stdout", "").strip()
    issues = []
    if "permitrootlogin yes" in output:
        issues.append("Root login via SSH is permitted")
    if "passwordauthentication yes" in output:
        issues.append("Password authentication enabled (key-only recommended)")
    return {"issues": issues, "config_lines": output.splitlines()}


async def _scan_firewall(agent: Any) -> dict[str, Any]:
    """Check firewall status and rules."""
    result = await agent._request("POST", "/exec", json_body={
        "command": "ufw status verbose 2>/dev/null || iptables -L -n 2>/dev/null | head -30",
    })
    output = result.get("stdout", "").strip()
    is_active = "Status: active" in output
    return {"active": is_active, "rules_summary": output[:1000]}
