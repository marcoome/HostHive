"""AI-powered nginx configuration optimization service."""

from __future__ import annotations

import difflib
import logging
from typing import Any

from api.core.ai_client import AIClient

logger = logging.getLogger("hosthive.ai.nginx")

_OPTIMIZE_PROMPT = """You are an expert nginx systems administrator. Analyze the following nginx virtual host configuration and optimize it.

Apply these optimizations where appropriate:
1. **Gzip compression** — enable for text, CSS, JS, JSON, XML, SVG
2. **Browser caching** — set Cache-Control and Expires headers for static assets
3. **Security headers** — X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Content-Security-Policy
4. **Rate limiting** — add limit_req_zone and limit_req for login/admin endpoints
5. **FastCGI cache** — if PHP/FastCGI is used, add fastcgi_cache directives
6. **HTTP/2** — ensure listen directive has http2 enabled (if SSL)
7. **Connection settings** — keepalive_timeout, client_max_body_size
8. **Logging** — access_log with buffer, error_log at warn level

Current traffic info: {traffic_info}

Return a JSON object with:
- "optimized_config": the full optimized nginx config (complete server block)
- "explanation": bullet-point list of changes made and why

Current config:
```nginx
{current_config}
```
"""


async def optimize_nginx(
    domain: str,
    agent_client: Any,
    ai_client: AIClient,
) -> dict[str, str]:
    """Read vhost config, analyze traffic, generate optimized config.

    Returns dict with keys: current_config, proposed_config, diff, explanation.
    """
    # Read current vhost config
    vhost_path = f"/etc/nginx/sites-available/{domain}.conf"
    try:
        result = await agent_client.read_file(vhost_path)
        current_config = result.get("content", "")
    except Exception:
        # Try alternative path
        vhost_path = f"/etc/nginx/conf.d/{domain}.conf"
        try:
            result = await agent_client.read_file(vhost_path)
            current_config = result.get("content", "")
        except Exception as exc:
            raise ValueError(f"Could not read nginx config for {domain}: {exc}")

    if not current_config.strip():
        raise ValueError(f"Empty nginx config for {domain}")

    # Get traffic stats
    traffic_info = "No traffic data available"
    try:
        stats = await agent_client._request("GET", f"/vhost/{domain}/stats")
        traffic_info = (
            f"Requests today: {stats.get('requests_today', 'unknown')}, "
            f"Bandwidth: {stats.get('bandwidth_bytes', 'unknown')} bytes, "
            f"30-day requests: {stats.get('requests_30d', 'unknown')}"
        )
    except Exception:
        pass

    # Send to AI for optimization
    prompt = _OPTIMIZE_PROMPT.format(
        current_config=current_config,
        traffic_info=traffic_info,
    )
    analysis = await ai_client.analyze(prompt)

    proposed_config = analysis.get("optimized_config", current_config)
    explanation = analysis.get("explanation", "No explanation provided.")

    if isinstance(explanation, list):
        explanation = "\n".join(f"- {item}" for item in explanation)

    # Generate diff
    current_lines = current_config.splitlines(keepends=True)
    proposed_lines = proposed_config.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            current_lines,
            proposed_lines,
            fromfile=f"{domain}.conf (current)",
            tofile=f"{domain}.conf (optimized)",
        )
    )

    return {
        "current_config": current_config,
        "proposed_config": proposed_config,
        "diff": diff or "No changes needed.",
        "explanation": explanation,
    }


async def apply_nginx_config(
    domain: str,
    proposed_config: str,
    agent_client: Any,
) -> dict[str, Any]:
    """Write the proposed config and reload nginx.

    Returns dict with status and any error message.
    """
    vhost_path = f"/etc/nginx/sites-available/{domain}.conf"

    # Test the proposed config by writing to a temp location first
    test_path = f"/tmp/nginx_test_{domain}.conf"
    try:
        await agent_client.write_file(test_path, proposed_config)
        # Ask agent to test nginx config
        test_result = await agent_client._request(
            "POST", "/exec",
            json_body={"command": f"nginx -t -c {test_path}"},
        )
        if test_result.get("exit_code", 1) != 0:
            return {
                "status": "error",
                "message": f"Config test failed: {test_result.get('stderr', 'unknown error')}",
            }
    except Exception as exc:
        logger.warning("Config test via temp file failed: %s, writing directly", exc)

    # Write the config
    try:
        await agent_client.write_file(vhost_path, proposed_config)
    except Exception as exc:
        raise ValueError(f"Failed to write nginx config: {exc}")

    # Reload nginx
    try:
        await agent_client.service_action("nginx", "reload")
    except Exception as exc:
        raise ValueError(f"Failed to reload nginx: {exc}")

    return {"status": "applied", "message": f"Nginx config for {domain} updated and reloaded."}
