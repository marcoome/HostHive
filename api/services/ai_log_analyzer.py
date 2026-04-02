"""AI-powered log analysis service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.config import settings

logger = logging.getLogger("hosthive.ai.log_analyzer")

# Log files to analyze
_LOG_SOURCES = {
    "nginx_error": "/var/log/nginx/error.log",
    "exim": "/var/log/exim4/mainlog",
    "auth": "/var/log/auth.log",
    "syslog": "/var/log/syslog",
}

_ANALYSIS_PROMPT = """Analyze the following server logs and identify issues.
Return a JSON array of findings. Each finding must have:
- "severity": "high", "medium", or "low"
- "issue_type": short category (e.g. "brute_force", "disk_space", "service_crash", "permission_error", "malware", "config_error")
- "description": clear explanation of the issue
- "recommendation": actionable fix
- "auto_fix_available": true/false
- "auto_fix_action": if auto_fix_available is true, a shell command or agent action to fix it; null otherwise

Only report genuine issues. Do NOT include normal/healthy log entries.
Do NOT include any passwords, API keys, or certificates in your response.

=== NGINX ERROR LOG (last 500 lines) ===
{nginx_error}

=== EXIM MAIL LOG (last 500 lines) ===
{exim}

=== AUTH LOG (last 500 lines) ===
{auth}

=== SYSLOG (last 500 lines) ===
{syslog}
"""


def _read_log_tail(session: Session, file_path: str, lines: int = 500) -> str:
    """Read the last N lines of a log file via the agent (sync)."""
    import httpx

    try:
        resp = httpx.get(
            f"{settings.AGENT_URL}/files/read",
            params={"path": file_path},
            headers={"X-Agent-Secret": settings.AGENT_SECRET},
            timeout=30.0,
        )
        resp.raise_for_status()
        content = resp.json().get("content", "")
        log_lines = content.strip().split("\n") if content else []
        return "\n".join(log_lines[-lines:])
    except Exception as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return f"[Could not read {file_path}: {exc}]"


def analyze_logs(session: Session) -> list[dict[str, Any]]:
    """Collect logs and send to AI for analysis.

    This function is designed to be called from a Celery task (sync context).
    Returns a list of insight dicts that were created.
    """
    from api.models.ai import AiInsight, AiInsightSeverity, AiSettings, AiTokenUsage
    from api.core.encryption import decrypt_value

    # Check if AI is enabled
    ai_settings = session.execute(
        select(AiSettings).limit(1)
    ).scalar_one_or_none()

    if ai_settings is None or not ai_settings.is_enabled:
        logger.info("AI is disabled, skipping log analysis")
        return []

    # Build AI client (sync wrapper)
    api_key = None
    if ai_settings.api_key_encrypted:
        try:
            api_key = decrypt_value(ai_settings.api_key_encrypted, settings.SECRET_KEY)
        except Exception:
            logger.error("Failed to decrypt AI API key")
            return []

    # Collect logs
    log_data = {}
    for name, path in _LOG_SOURCES.items():
        log_data[name] = _read_log_tail(session, path)

    # Build prompt
    prompt = _ANALYSIS_PROMPT.format(**log_data)

    # Call AI (sync via httpx)
    import httpx
    import json

    insights_created = []

    try:
        if ai_settings.provider == "openai":
            url = (ai_settings.base_url or "https://api.openai.com") + "/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": ai_settings.model,
                "messages": [
                    {"role": "system", "content": "You are a server administration expert. Always respond with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": ai_settings.max_tokens_per_request,
                "response_format": {"type": "json_object"},
            }
        elif ai_settings.provider == "anthropic":
            url = (ai_settings.base_url or "https://api.anthropic.com") + "/v1/messages"
            headers = {
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            body = {
                "model": ai_settings.model,
                "system": "You are a server administration expert. Always respond with valid JSON.",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": ai_settings.max_tokens_per_request,
            }
        elif ai_settings.provider == "ollama":
            url = (ai_settings.base_url or "http://localhost:11434") + "/api/chat"
            headers = {"Content-Type": "application/json"}
            body = {
                "model": ai_settings.model,
                "messages": [
                    {"role": "system", "content": "You are a server administration expert. Always respond with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "format": "json",
                "stream": False,
            }
        else:
            logger.error("Unknown AI provider: %s", ai_settings.provider)
            return []

        resp = httpx.post(url, json=body, headers=headers, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()

        # Extract response text
        if ai_settings.provider == "openai":
            response_text = data["choices"][0]["message"]["content"]
            tokens_in = data.get("usage", {}).get("prompt_tokens", 0)
            tokens_out = data.get("usage", {}).get("completion_tokens", 0)
        elif ai_settings.provider == "anthropic":
            response_text = data["content"][0]["text"]
            tokens_in = data.get("usage", {}).get("input_tokens", 0)
            tokens_out = data.get("usage", {}).get("output_tokens", 0)
        else:  # ollama
            response_text = data.get("message", {}).get("content", "")
            tokens_in = data.get("prompt_eval_count", 0)
            tokens_out = data.get("eval_count", 0)

        # Log token usage
        from api.core.ai_client import AIClient
        cost = 0.0
        client_temp = AIClient(ai_settings.provider, model=ai_settings.model)
        cost = client_temp.estimate_cost(tokens_in, tokens_out)

        usage = AiTokenUsage(
            provider=ai_settings.provider,
            model=ai_settings.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
        session.add(usage)

        # Parse findings
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            import re
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response_text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(1))
            else:
                logger.error("Failed to parse AI response as JSON")
                return []

        # Normalize: could be {"findings": [...]} or just [...]
        if isinstance(parsed, dict):
            findings = parsed.get("findings", parsed.get("issues", []))
        elif isinstance(parsed, list):
            findings = parsed
        else:
            findings = []

        for finding in findings:
            severity_str = finding.get("severity", "low").lower()
            try:
                severity = AiInsightSeverity(severity_str)
            except ValueError:
                severity = AiInsightSeverity.LOW

            insight = AiInsight(
                severity=severity,
                issue_type=finding.get("issue_type", "unknown"),
                description=finding.get("description", ""),
                recommendation=finding.get("recommendation", ""),
                auto_fix_available=finding.get("auto_fix_available", False),
                auto_fix_action=finding.get("auto_fix_action"),
            )
            session.add(insight)
            insights_created.append({
                "severity": severity.value,
                "issue_type": insight.issue_type,
                "description": insight.description,
            })

            # Auto-fix high severity issues if enabled
            if (
                severity == AiInsightSeverity.HIGH
                and ai_settings.auto_fix_enabled
                and insight.auto_fix_available
                and insight.auto_fix_action
            ):
                try:
                    _execute_auto_fix(insight.auto_fix_action)
                    insight.is_resolved = True
                    insight.resolved_at = datetime.now(timezone.utc)
                    logger.info(
                        "Auto-fixed high severity issue: %s", insight.issue_type,
                    )
                except Exception as exc:
                    logger.error(
                        "Auto-fix failed for %s: %s", insight.issue_type, exc,
                    )

            # Send Telegram alert for high severity
            if severity == AiInsightSeverity.HIGH:
                _send_high_severity_alert(session, insight)

        session.commit()
        logger.info("Log analysis complete: %d insights created", len(insights_created))

    except Exception as exc:
        logger.error("Log analysis failed: %s", exc)
        return []

    return insights_created


def _execute_auto_fix(action: str) -> None:
    """Execute an auto-fix action via the agent."""
    import httpx

    resp = httpx.post(
        f"{settings.AGENT_URL}/exec",
        json={"command": action},
        headers={"X-Agent-Secret": settings.AGENT_SECRET},
        timeout=30.0,
    )
    resp.raise_for_status()


def _send_high_severity_alert(session: Session, insight) -> None:
    """Send a Telegram alert for high severity issues."""
    from api.models.integrations import Integration

    try:
        integrations = session.execute(
            select(Integration).where(Integration.is_enabled.is_(True))
        ).scalars().all()

        integration_list = []
        for intg in integrations:
            integration_list.append({
                "name": intg.name,
                "is_enabled": intg.is_enabled,
                "config_json": intg.config_json,
            })

        if integration_list:
            # Use sync httpx to trigger notification via internal API
            # or directly call the dispatcher logic
            import httpx
            import json
            from api.core.encryption import decrypt_value

            for intg in integration_list:
                if intg["name"] != "telegram" or not intg["is_enabled"]:
                    continue
                try:
                    config = json.loads(
                        decrypt_value(intg["config_json"], settings.SECRET_KEY)
                    )
                    message = (
                        f"\u26a0\ufe0f [HIGH] AI Log Analysis\n"
                        f"Issue: {insight.issue_type}\n"
                        f"Description: {insight.description}\n"
                        f"Recommendation: {insight.recommendation}"
                    )
                    httpx.post(
                        f"https://api.telegram.org/bot{config['bot_token']}/sendMessage",
                        json={
                            "chat_id": config["chat_id"],
                            "text": message,
                            "parse_mode": "HTML",
                        },
                        timeout=10.0,
                    )
                except Exception as exc:
                    logger.warning("Failed to send Telegram alert: %s", exc)

    except Exception as exc:
        logger.warning("Failed to send high severity alert: %s", exc)
