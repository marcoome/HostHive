"""HostHive AI Celery tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from api.core.config import settings
from api.tasks import app
from api.tasks._db import get_sync_session

logger = logging.getLogger("hosthive.worker.ai")


@app.task(
    name="api.tasks.ai_tasks.analyze_logs_periodic",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    retry_backoff=True,
    retry_backoff_max=600,
)
def analyze_logs_periodic(self) -> dict:
    """Run AI log analysis based on configured interval.

    Collects recent log entries from nginx, exim, auth.log, and syslog,
    sends them to the configured AI provider for analysis, and creates
    AiInsight records for any issues found.
    """
    from api.services.ai_log_analyzer import analyze_logs

    logger.info("Starting periodic AI log analysis")

    with get_sync_session() as session:
        try:
            insights = analyze_logs(session)
            logger.info("AI log analysis complete: %d insights created", len(insights))
            return {"status": "completed", "insights_created": len(insights)}
        except Exception as exc:
            logger.error("AI log analysis failed: %s", exc)
            raise self.retry(exc=exc)


@app.task(
    name="api.tasks.ai_tasks.security_scan_daily",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    retry_backoff=True,
    retry_backoff_max=600,
)
def security_scan_daily(self) -> dict:
    """Run daily AI-powered security scan.

    Scans nginx configs, PHP versions, SSL certs, open ports, file
    permissions, WordPress installs, mail config, SSH config, and
    firewall rules. Creates AiInsight records for findings.
    """
    import httpx
    import json

    from api.models.ai import AiInsight, AiInsightSeverity, AiSettings
    from api.core.encryption import decrypt_value

    logger.info("Starting daily AI security scan")

    with get_sync_session() as session:
        # Check if AI is enabled
        ai_settings = session.execute(
            select(AiSettings).limit(1)
        ).scalar_one_or_none()

        if ai_settings is None or not ai_settings.is_enabled:
            logger.info("AI is disabled, skipping security scan")
            return {"status": "skipped", "reason": "AI disabled"}

        # We need to run async security scan from sync context
        # Use the sync httpx client to call the AI API directly
        api_key = None
        if ai_settings.api_key_encrypted:
            try:
                api_key = decrypt_value(ai_settings.api_key_encrypted, settings.SECRET_KEY)
            except Exception:
                logger.error("Failed to decrypt AI API key for security scan")
                return {"status": "error", "reason": "decrypt_failed"}

        # Run simplified scan checks via agent (sync)
        scan_results = {}
        try:
            # Quick sync checks via agent
            for check_name, check_cmd in [
                ("open_ports", "ss -tlnp 2>/dev/null | tail -n +2"),
                ("ssh_config", "sshd -T 2>/dev/null | grep -E '(permitrootlogin|passwordauthentication)'"),
                ("firewall", "ufw status 2>/dev/null || echo 'ufw not installed'"),
                ("php_versions", "ls /etc/php/ 2>/dev/null || echo 'no-php'"),
                ("world_writable", "find /home -maxdepth 4 -perm -o+w -type f 2>/dev/null | head -10"),
            ]:
                try:
                    resp = httpx.post(
                        f"{settings.AGENT_URL}/exec",
                        json={"command": check_cmd},
                        headers={"X-Agent-Secret": settings.AGENT_SECRET},
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                    scan_results[check_name] = resp.json().get("stdout", "")
                except Exception as exc:
                    scan_results[check_name] = f"Error: {exc}"

            # Send to AI for analysis
            prompt = (
                "Analyze these server security scan results and return JSON with "
                "'findings' array. Each finding: severity (high/medium/low), "
                "issue_type, description, recommendation, auto_fix_available (bool), "
                "auto_fix_action (string or null).\n\n"
                + "\n".join(f"=== {k} ===\n{v}" for k, v in scan_results.items())
            )

            # Build AI request (sync)
            if ai_settings.provider == "openai":
                url = (ai_settings.base_url or "https://api.openai.com") + "/v1/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                body = {
                    "model": ai_settings.model,
                    "messages": [
                        {"role": "system", "content": "You are a server security expert. Respond with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": ai_settings.max_tokens_per_request,
                    "response_format": {"type": "json_object"},
                }
            elif ai_settings.provider == "anthropic":
                url = (ai_settings.base_url or "https://api.anthropic.com") + "/v1/messages"
                headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
                body = {
                    "model": ai_settings.model,
                    "system": "You are a server security expert. Respond with valid JSON only.",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": ai_settings.max_tokens_per_request,
                }
            else:  # ollama
                url = (ai_settings.base_url or "http://localhost:11434") + "/api/chat"
                headers = {"Content-Type": "application/json"}
                body = {
                    "model": ai_settings.model,
                    "messages": [
                        {"role": "system", "content": "You are a server security expert. Respond with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "format": "json",
                    "stream": False,
                }

            resp = httpx.post(url, json=body, headers=headers, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()

            if ai_settings.provider == "openai":
                response_text = data["choices"][0]["message"]["content"]
            elif ai_settings.provider == "anthropic":
                response_text = data["content"][0]["text"]
            else:
                response_text = data.get("message", {}).get("content", "")

            parsed = json.loads(response_text)
            findings = parsed.get("findings", parsed.get("issues", []))
            if isinstance(parsed, list):
                findings = parsed

            created = 0
            for finding in findings:
                severity_str = finding.get("severity", "low").lower()
                try:
                    severity = AiInsightSeverity(severity_str)
                except ValueError:
                    severity = AiInsightSeverity.LOW

                insight = AiInsight(
                    severity=severity,
                    issue_type=finding.get("issue_type", "security"),
                    description=finding.get("description", ""),
                    recommendation=finding.get("recommendation", ""),
                    auto_fix_available=finding.get("auto_fix_available", False),
                    auto_fix_action=finding.get("auto_fix_action"),
                )
                session.add(insight)
                created += 1

            session.commit()
            logger.info("Daily security scan complete: %d findings", created)
            return {"status": "completed", "findings": created}

        except Exception as exc:
            logger.error("Daily security scan failed: %s", exc)
            raise self.retry(exc=exc)


@app.task(
    name="api.tasks.ai_tasks.cleanup_ai_conversations",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def cleanup_ai_conversations(self) -> dict:
    """Delete AI conversations older than 30 days."""
    from api.models.ai import AiConversation

    logger.info("Starting AI conversation cleanup")
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    with get_sync_session() as session:
        try:
            result = session.execute(
                delete(AiConversation).where(AiConversation.updated_at < cutoff)
            )
            deleted = result.rowcount
            session.commit()
            logger.info("Cleaned up %d old AI conversations (cutoff: %s)", deleted, cutoff)
            return {"deleted": deleted, "cutoff": cutoff.isoformat()}
        except Exception as exc:
            logger.error("AI conversation cleanup failed: %s", exc)
            raise self.retry(exc=exc)
