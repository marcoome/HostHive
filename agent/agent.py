"""
HostHive Root Agent — FastAPI daemon bound to 127.0.0.1:7080.

Accepts only localhost connections.  Every request is authenticated via
HMAC-SHA256 (shared secret loaded from /opt/novapanel/config/secrets.env).

Structured JSON logging goes to /opt/novapanel/logs/agent.log.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent.auth import HMACVerifier
from api.core.middleware import IPWhitelistMiddleware

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SECRETS_FILE = Path("/opt/novapanel/config/secrets.env")
LOG_FILE = Path("/opt/novapanel/logs/agent.log")
BIND_HOST = "127.0.0.1"
BIND_PORT = 7080

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("novapanel.agent")
    logger.setLevel(logging.INFO)

    # JSON formatter
    class _JSONFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            obj = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[1]:
                obj["exception"] = traceback.format_exception(*record.exc_info)
            return json.dumps(obj)

    handler = logging.FileHandler(str(LOG_FILE))
    handler.setFormatter(_JSONFormatter())
    logger.addHandler(handler)

    # Also log to stderr during development
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(_JSONFormatter())
    logger.addHandler(stderr_handler)

    return logger


log = _setup_logging()

# ---------------------------------------------------------------------------
# Load shared secret
# ---------------------------------------------------------------------------


def _load_secret() -> str:
    """Read AGENT_SECRET from secrets.env (KEY=VALUE format)."""
    if not SECRETS_FILE.exists():
        log.warning("secrets file not found at %s — using fallback", SECRETS_FILE)
        fallback = os.environ.get("NOVAPANEL_AGENT_SECRET", "")
        if not fallback:
            raise RuntimeError(
                f"No shared secret: {SECRETS_FILE} missing and "
                "NOVAPANEL_AGENT_SECRET env var not set"
            )
        return fallback

    for line in SECRETS_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "AGENT_SECRET":
            return value.strip().strip("'\"")

    raise RuntimeError(f"AGENT_SECRET not found in {SECRETS_FILE}")


_secret = _load_secret()
_verifier = HMACVerifier(_secret)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="HostHive Root Agent", docs_url=None, redoc_url=None)

# Localhost-only enforcement — reject any non-loopback client
app.add_middleware(IPWhitelistMiddleware)


@app.middleware("http")
async def hmac_auth_middleware(request: Request, call_next):
    """Verify HMAC-SHA256 on every request."""
    # Health-check bypass (localhost only, no auth needed)
    if request.url.path == "/healthz":
        return await call_next(request)

    body = await request.body()

    timestamp = request.headers.get("X-NP-Timestamp")
    nonce = request.headers.get("X-NP-Nonce")
    signature = request.headers.get("X-NP-Signature")

    ok, reason = _verifier.verify(timestamp, nonce, body, signature)
    if not ok:
        log.warning("auth failed: %s [%s %s]", reason, request.method, request.url.path)
        return JSONResponse({"error": f"authentication failed: {reason}"}, status_code=401)

    log.info("request: %s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class VhostCreate(BaseModel):
    domain: str
    document_root: str
    php_version: str = "8.2"
    ssl: bool = False


class VhostSSL(BaseModel):
    domain: str
    cert_path: str
    key_path: str


class DomainOnly(BaseModel):
    domain: str


class DNSZoneCreate(BaseModel):
    domain: str
    ip: str


class DNSRecordAdd(BaseModel):
    domain: str
    record_type: str
    name: str
    value: str
    ttl: int = 3600
    priority: int | None = None


class DNSRecordDelete(BaseModel):
    domain: str
    record_id: int


class MailboxCreate(BaseModel):
    address: str
    password: str
    quota_mb: int = 1024


class MailboxPassword(BaseModel):
    address: str
    new_password: str


class MailAlias(BaseModel):
    from_addr: str
    to_addr: str


class AliasDelete(BaseModel):
    alias: str


class AddressOnly(BaseModel):
    address: str


class FTPUserCreate(BaseModel):
    username: str
    password: str
    home_dir: str


class FTPUserDelete(BaseModel):
    username: str


class FTPPassword(BaseModel):
    username: str
    password: str


class MySQLCreate(BaseModel):
    db_name: str
    db_user: str
    db_password: str


class MySQLDelete(BaseModel):
    db_name: str
    db_user: str


class PostgresCreate(BaseModel):
    db_name: str
    db_user: str
    db_password: str


class PostgresDelete(BaseModel):
    db_name: str
    db_user: str


class SSLIssue(BaseModel):
    domain: str
    email: str


class SSLCustom(BaseModel):
    domain: str
    cert_pem: str
    key_pem: str


class BackupCreate(BaseModel):
    username: str
    backup_type: str = "full"


class BackupRestore(BaseModel):
    username: str
    backup_file: str


class BackupDelete(BaseModel):
    backup_file: str


class BackupList(BaseModel):
    username: str


class ServiceRestart(BaseModel):
    name: str


class FirewallRuleAdd(BaseModel):
    port: int | str
    protocol: str = "tcp"
    action: str = "allow"


class FirewallRuleDelete(BaseModel):
    rule_id: int


class UnbanIP(BaseModel):
    ip: str
    jail: str


class RunCommand(BaseModel):
    cmd: str
    args: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Route helper
# ---------------------------------------------------------------------------


def _exec(func, *args, **kwargs) -> JSONResponse:
    """Call an executor function and return a JSON response."""
    try:
        result = func(*args, **kwargs)
        return JSONResponse({"ok": True, "data": result})
    except PermissionError as exc:
        log.warning("permission denied: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
    except (ValueError, FileNotFoundError) as exc:
        log.warning("client error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        log.error("executor error: %s", exc, exc_info=True)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Nginx routes
# ---------------------------------------------------------------------------

from agent.executors import nginx_executor  # noqa: E402


@app.post("/nginx/vhost")
async def nginx_create_vhost(body: VhostCreate):
    return _exec(nginx_executor.create_vhost, body.domain, body.document_root, body.php_version, body.ssl)


@app.post("/nginx/vhost/ssl")
async def nginx_enable_ssl(body: VhostSSL):
    return _exec(nginx_executor.enable_ssl, body.domain, body.cert_path, body.key_path)


@app.delete("/nginx/vhost")
async def nginx_delete_vhost(body: DomainOnly):
    return _exec(nginx_executor.delete_vhost, body.domain)


@app.post("/nginx/reload")
async def nginx_reload():
    return _exec(nginx_executor.reload_nginx)


@app.get("/nginx/vhosts")
async def nginx_list_vhosts():
    return _exec(nginx_executor.list_vhosts)


@app.get("/nginx/status")
async def nginx_status():
    return _exec(nginx_executor.get_nginx_status)


# ---------------------------------------------------------------------------
# DNS routes
# ---------------------------------------------------------------------------

from agent.executors import dns_executor  # noqa: E402


@app.post("/dns/zone")
async def dns_create_zone(body: DNSZoneCreate):
    return _exec(dns_executor.create_zone, body.domain, body.ip)


@app.delete("/dns/zone")
async def dns_delete_zone(body: DomainOnly):
    return _exec(dns_executor.delete_zone, body.domain)


@app.post("/dns/record")
async def dns_add_record(body: DNSRecordAdd):
    return _exec(dns_executor.add_record, body.domain, body.record_type, body.name, body.value, body.ttl, body.priority)


@app.delete("/dns/record")
async def dns_delete_record(body: DNSRecordDelete):
    return _exec(dns_executor.delete_record, body.domain, body.record_id)


@app.post("/dns/reload")
async def dns_reload():
    return _exec(dns_executor.reload_bind)


# ---------------------------------------------------------------------------
# Mail routes
# ---------------------------------------------------------------------------

from agent.executors import mail_executor  # noqa: E402


@app.post("/mail/mailbox")
async def mail_create_mailbox(body: MailboxCreate):
    return _exec(mail_executor.create_mailbox, body.address, body.password, body.quota_mb)


@app.delete("/mail/mailbox")
async def mail_delete_mailbox(body: AddressOnly):
    return _exec(mail_executor.delete_mailbox, body.address)


@app.post("/mail/password")
async def mail_set_password(body: MailboxPassword):
    return _exec(mail_executor.set_password, body.address, body.new_password)


@app.post("/mail/alias")
async def mail_create_alias(body: MailAlias):
    return _exec(mail_executor.create_alias, body.from_addr, body.to_addr)


@app.delete("/mail/alias")
async def mail_delete_alias(body: AliasDelete):
    return _exec(mail_executor.delete_alias, body.alias)


@app.get("/mail/queue")
async def mail_get_queue():
    return _exec(mail_executor.get_mail_queue)


@app.post("/mail/queue/flush")
async def mail_flush_queue():
    return _exec(mail_executor.flush_mail_queue)


# ---------------------------------------------------------------------------
# FTP routes
# ---------------------------------------------------------------------------

from agent.executors import ftp_executor  # noqa: E402


@app.post("/ftp/user")
async def ftp_create_user(body: FTPUserCreate):
    return _exec(ftp_executor.create_ftp_user, body.username, body.password, body.home_dir)


@app.delete("/ftp/user")
async def ftp_delete_user(body: FTPUserDelete):
    return _exec(ftp_executor.delete_ftp_user, body.username)


@app.post("/ftp/password")
async def ftp_set_password(body: FTPPassword):
    return _exec(ftp_executor.set_ftp_password, body.username, body.password)


# ---------------------------------------------------------------------------
# Database routes
# ---------------------------------------------------------------------------

from agent.executors import database_executor  # noqa: E402


@app.post("/db/mysql")
async def db_create_mysql(body: MySQLCreate):
    return _exec(database_executor.create_mysql_db, body.db_name, body.db_user, body.db_password)


@app.delete("/db/mysql")
async def db_delete_mysql(body: MySQLDelete):
    return _exec(database_executor.delete_mysql_db, body.db_name, body.db_user)


@app.post("/db/postgres")
async def db_create_postgres(body: PostgresCreate):
    return _exec(database_executor.create_postgres_db, body.db_name, body.db_user, body.db_password)


@app.delete("/db/postgres")
async def db_delete_postgres(body: PostgresDelete):
    return _exec(database_executor.delete_postgres_db, body.db_name, body.db_user)


# ---------------------------------------------------------------------------
# SSL routes
# ---------------------------------------------------------------------------

from agent.executors import ssl_executor  # noqa: E402


@app.post("/ssl/letsencrypt")
async def ssl_issue(body: SSLIssue):
    return _exec(ssl_executor.issue_letsencrypt, body.domain, body.email)


@app.post("/ssl/renew")
async def ssl_renew(body: DomainOnly):
    return _exec(ssl_executor.renew_certificate, body.domain)


@app.post("/ssl/revoke")
async def ssl_revoke(body: DomainOnly):
    return _exec(ssl_executor.revoke_certificate, body.domain)


@app.post("/ssl/custom")
async def ssl_custom(body: SSLCustom):
    return _exec(ssl_executor.install_custom_cert, body.domain, body.cert_pem, body.key_pem)


@app.get("/ssl/expiry/{domain}")
async def ssl_expiry(domain: str):
    return _exec(ssl_executor.get_expiry, domain)


# ---------------------------------------------------------------------------
# Backup routes
# ---------------------------------------------------------------------------

from agent.executors import backup_executor  # noqa: E402


@app.post("/backup/create")
async def backup_create(body: BackupCreate):
    return _exec(backup_executor.create_backup, body.username, body.backup_type)


@app.post("/backup/restore")
async def backup_restore(body: BackupRestore):
    return _exec(backup_executor.restore_backup, body.username, body.backup_file)


@app.delete("/backup")
async def backup_delete(body: BackupDelete):
    return _exec(backup_executor.delete_backup, body.backup_file)


@app.get("/backup/list/{username}")
async def backup_list(username: str):
    return _exec(backup_executor.list_backups, username)


# ---------------------------------------------------------------------------
# System routes
# ---------------------------------------------------------------------------

from agent.executors import system_executor  # noqa: E402


@app.get("/system/stats")
async def system_stats():
    return _exec(system_executor.get_server_stats)


@app.get("/system/services")
async def system_services():
    return _exec(system_executor.get_running_services)


@app.post("/system/service/restart")
async def system_restart_service(body: ServiceRestart):
    return _exec(system_executor.restart_service, body.name)


@app.get("/system/firewall")
async def system_firewall():
    return _exec(system_executor.get_firewall_rules)


@app.post("/system/firewall/rule")
async def system_firewall_add(body: FirewallRuleAdd):
    return _exec(system_executor.add_firewall_rule, body.port, body.protocol, body.action)


@app.delete("/system/firewall/rule")
async def system_firewall_delete(body: FirewallRuleDelete):
    return _exec(system_executor.delete_firewall_rule, body.rule_id)


@app.get("/system/fail2ban")
async def system_fail2ban():
    return _exec(system_executor.get_fail2ban_jails)


@app.post("/system/fail2ban/unban")
async def system_unban(body: UnbanIP):
    return _exec(system_executor.unban_ip, body.ip, body.jail)


@app.post("/system/command")
async def system_run_command(body: RunCommand):
    return _exec(system_executor.run_command, body.cmd, body.args)


# ---------------------------------------------------------------------------
# Docker Isolation routes
# ---------------------------------------------------------------------------

from agent.executors import docker_isolation  # noqa: E402


class DockerIsolationCreate(BaseModel):
    username: str
    plan: dict = Field(default_factory=dict)


class DockerIsolationDestroy(BaseModel):
    username: str


class DockerIsolationSwitchWebserver(BaseModel):
    username: str
    webserver: str


class DockerIsolationSwitchDb(BaseModel):
    username: str
    version: str


class DockerIsolationPhp(BaseModel):
    username: str
    version: str


class DockerIsolationToggleCache(BaseModel):
    username: str
    enable: bool
    memory_mb: int = 64


class DockerIsolationUpdateResources(BaseModel):
    username: str
    cpu: float
    memory_mb: int
    io_bps: int = 0


async def _async_exec(coro) -> JSONResponse:
    """Await an async executor coroutine and return a JSON response."""
    try:
        result = await coro
        return JSONResponse({"ok": True, "data": result})
    except PermissionError as exc:
        log.warning("permission denied: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
    except (ValueError, FileNotFoundError) as exc:
        log.warning("client error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        log.error("executor error: %s", exc, exc_info=True)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/docker-isolation/create")
async def docker_iso_create(body: DockerIsolationCreate):
    return await _async_exec(docker_isolation.create_user_environment(body.username, body.plan))


@app.post("/docker-isolation/destroy")
async def docker_iso_destroy(body: DockerIsolationDestroy):
    return await _async_exec(docker_isolation.destroy_user_environment(body.username))


@app.post("/docker-isolation/switch-webserver")
async def docker_iso_switch_webserver(body: DockerIsolationSwitchWebserver):
    return await _async_exec(docker_isolation.switch_webserver(body.username, body.webserver))


@app.post("/docker-isolation/switch-db")
async def docker_iso_switch_db(body: DockerIsolationSwitchDb):
    return await _async_exec(docker_isolation.switch_db_version(body.username, body.version))


@app.post("/docker-isolation/add-php")
async def docker_iso_add_php(body: DockerIsolationPhp):
    return await _async_exec(docker_isolation.add_php_version(body.username, body.version))


@app.post("/docker-isolation/remove-php")
async def docker_iso_remove_php(body: DockerIsolationPhp):
    return await _async_exec(docker_isolation.remove_php_version(body.username, body.version))


@app.post("/docker-isolation/toggle-redis")
async def docker_iso_toggle_redis(body: DockerIsolationToggleCache):
    return await _async_exec(docker_isolation.toggle_redis(body.username, body.enable, body.memory_mb))


@app.post("/docker-isolation/toggle-memcached")
async def docker_iso_toggle_memcached(body: DockerIsolationToggleCache):
    return await _async_exec(docker_isolation.toggle_memcached(body.username, body.enable, body.memory_mb))


@app.post("/docker-isolation/update-resources")
async def docker_iso_update_resources(body: DockerIsolationUpdateResources):
    return await _async_exec(docker_isolation.update_resource_limits(body.username, body.cpu, body.memory_mb, body.io_bps))


@app.get("/docker-isolation/usage/{username}")
async def docker_iso_usage(username: str):
    return await _async_exec(docker_isolation.get_user_resource_usage(username))


@app.get("/docker-isolation/containers/{username}")
async def docker_iso_containers(username: str):
    return await _async_exec(docker_isolation.get_user_containers(username))


# ---------------------------------------------------------------------------
# Analytics routes (GoAccess)
# ---------------------------------------------------------------------------

from agent.executors import analytics_executor  # noqa: E402


class AnalyticsReport(BaseModel):
    domain: str
    period: str = "daily"


class AnalyticsStats(BaseModel):
    domain: str
    period: str = "7d"


class AnalyticsDomain(BaseModel):
    domain: str


class AnalyticsTopRequest(BaseModel):
    domain: str
    limit: int = 20


@app.post("/analytics/report")
async def analytics_report(body: AnalyticsReport):
    return await _async_exec(analytics_executor.generate_visitor_report(body.domain, body.period))


@app.post("/analytics/stats")
async def analytics_stats(body: AnalyticsStats):
    return await _async_exec(analytics_executor.get_visitor_stats(body.domain, body.period))


@app.post("/analytics/visitors")
async def analytics_visitors(body: AnalyticsDomain):
    return await _async_exec(analytics_executor.get_realtime_visitors(body.domain))


@app.post("/analytics/top-pages")
async def analytics_top_pages(body: AnalyticsTopRequest):
    return await _async_exec(analytics_executor.get_top_pages(body.domain, body.limit))


@app.post("/analytics/top-countries")
async def analytics_top_countries(body: AnalyticsTopRequest):
    return await _async_exec(analytics_executor.get_top_countries(body.domain, body.limit))


# ---------------------------------------------------------------------------
# WAF routes
# ---------------------------------------------------------------------------

from agent.executors import waf_executor  # noqa: E402


class WAFDomain(BaseModel):
    domain: str


class WAFCustomRule(BaseModel):
    domain: str
    rule: str


class WAFMode(BaseModel):
    domain: str
    mode: str


@app.post("/waf/enable")
async def waf_enable(body: WAFDomain):
    return _exec(waf_executor.enable_waf, body.domain)


@app.post("/waf/disable")
async def waf_disable(body: WAFDomain):
    return _exec(waf_executor.disable_waf, body.domain)


@app.get("/waf/status/{domain}")
async def waf_status(domain: str):
    return _exec(waf_executor.get_waf_status, domain)


@app.get("/waf/log/{domain}")
async def waf_log(domain: str, lines: int = 100):
    return _exec(waf_executor.get_waf_log, domain, lines)


@app.get("/waf/rules/{domain}")
async def waf_list_rules(domain: str):
    return _exec(waf_executor.list_rules, domain)


@app.post("/waf/rules/{domain}")
async def waf_add_rule(domain: str, body: WAFCustomRule):
    return _exec(waf_executor.add_custom_rule, body.domain, body.rule)


@app.delete("/waf/rules/{domain}/{rule_id}")
async def waf_delete_rule(domain: str, rule_id: int):
    return _exec(waf_executor.delete_custom_rule, domain, rule_id)


@app.put("/waf/mode/{domain}")
async def waf_set_mode(domain: str, body: WAFMode):
    return _exec(waf_executor.set_waf_mode, body.domain, body.mode)


# ---------------------------------------------------------------------------
# Resource limit routes
# ---------------------------------------------------------------------------

from agent.executors import resource_executor  # noqa: E402


class UserLimits(BaseModel):
    username: str
    cpu_percent: int = 100
    memory_mb: int = 1024
    io_weight: int = 100


class PHPLimits(BaseModel):
    domain: str
    max_children: int = 5
    memory_limit: str = "256M"
    php_version: str = "8.2"


@app.post("/resources/user/limits")
async def resource_set_user_limits(body: UserLimits):
    return _exec(
        resource_executor.set_user_limits,
        body.username,
        body.cpu_percent,
        body.memory_mb,
        body.io_weight,
    )


@app.get("/resources/user/{username}/usage")
async def resource_get_user_usage(username: str):
    return _exec(resource_executor.get_user_usage, username)


@app.get("/resources/user/{username}/limits")
async def resource_get_user_limits(username: str):
    meta = resource_executor._load_limit_meta(username)
    if not meta:
        return JSONResponse({"ok": False, "error": f"No limits found for {username}"}, status_code=404)
    return JSONResponse({"ok": True, "data": meta})


@app.delete("/resources/user/{username}")
async def resource_remove_user_limits(username: str):
    return _exec(resource_executor.remove_user_limits, username)


@app.get("/resources/overview")
async def resource_overview():
    return _exec(resource_executor.list_user_limits)


@app.get("/resources/domain/{domain}/usage")
async def resource_domain_usage(domain: str):
    return _exec(resource_executor.get_domain_resource_usage, domain)


@app.post("/resources/domain/php-limits")
async def resource_php_limits(body: PHPLimits):
    return _exec(
        resource_executor.set_php_fpm_limits,
        body.domain,
        body.max_children,
        body.memory_limit,
        body.php_version,
    )


# ---------------------------------------------------------------------------
# App (runtime) routes
# ---------------------------------------------------------------------------

from agent.executors import runtime_executor  # noqa: E402


class NodeJSDeploy(BaseModel):
    domain: str
    path: str
    port: int
    node_version: str = "20"


class PythonDeploy(BaseModel):
    domain: str
    path: str
    port: int
    python_version: str = "3.11"


class AgentAppEnvUpdate(BaseModel):
    domain: str
    env_dict: dict[str, str]


@app.post("/apps/deploy/nodejs")
async def app_deploy_nodejs(body: NodeJSDeploy):
    return _exec(runtime_executor.deploy_nodejs_app, body.domain, body.path, body.port, body.node_version)


@app.post("/apps/deploy/python")
async def app_deploy_python(body: PythonDeploy):
    return _exec(runtime_executor.deploy_python_app, body.domain, body.path, body.port, body.python_version)


@app.post("/apps/stop")
async def app_stop(body: DomainOnly):
    return _exec(runtime_executor.stop_app, body.domain)


@app.post("/apps/restart")
async def app_restart(body: DomainOnly):
    return _exec(runtime_executor.restart_app, body.domain)


@app.get("/apps/status/{domain}")
async def app_status(domain: str):
    return _exec(runtime_executor.get_app_status, domain)


@app.get("/apps/logs/{domain}")
async def app_logs(domain: str, lines: int = 200):
    return _exec(runtime_executor.get_app_logs, domain, lines)


@app.get("/apps/list")
async def app_list():
    return _exec(runtime_executor.list_apps)


@app.put("/apps/env/{domain}")
async def app_env_update(domain: str, body: AgentAppEnvUpdate):
    return _exec(runtime_executor.set_env_vars, body.domain, body.env_dict)


# ---------------------------------------------------------------------------
# Email Auth (DKIM/SPF/DMARC) routes
# ---------------------------------------------------------------------------


@app.get("/mail/auth/status/{domain}")
async def mail_auth_status(domain: str):
    return _exec(mail_executor.get_email_auth_status, domain)


@app.post("/mail/auth/dkim/setup")
async def mail_dkim_setup(body: DomainOnly):
    return _exec(mail_executor.setup_dkim, body.domain)


@app.get("/mail/auth/dkim/{domain}")
async def mail_dkim_record(domain: str):
    return _exec(mail_executor.get_dkim_record, domain)


@app.get("/mail/auth/dns-records/{domain}")
async def mail_auth_dns_records(domain: str):
    """Return all required DNS records for email auth (SPF, DKIM, DMARC)."""
    try:
        records = []

        # SPF record
        spf = mail_executor.generate_spf_record(domain)
        records.append({
            "type": "TXT",
            "name": domain,
            "value": spf["record"],
            "description": "SPF record for email authentication",
        })

        # DKIM record (if keys exist)
        try:
            dkim = mail_executor.get_dkim_record(domain)
            records.append({
                "type": "TXT",
                "name": dkim["dns_name"],
                "value": dkim["dns_value"],
                "description": "DKIM public key record",
            })
        except FileNotFoundError:
            records.append({
                "type": "TXT",
                "name": f"default._domainkey.{domain}",
                "value": "(Run DKIM setup first)",
                "description": "DKIM record -- keys not yet generated",
            })

        # DMARC record
        dmarc = mail_executor.generate_dmarc_record(domain)
        records.append({
            "type": "TXT",
            "name": f"_dmarc.{domain}",
            "value": dmarc["record"],
            "description": "DMARC policy record",
        })

        return JSONResponse({"ok": True, "data": {"domain": domain, "records": records}})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/mail/auth/verify")
async def mail_auth_verify(body: DomainOnly):
    """Check all email auth records and return status."""
    try:
        auth_status = mail_executor.get_email_auth_status(body.domain)
        all_ok = all(v == "ok" for v in [auth_status["spf"], auth_status["dkim"], auth_status["dmarc"]])
        auth_status["all_ok"] = all_ok
        auth_status["details"] = {}
        if auth_status["spf"] != "ok":
            auth_status["details"]["spf"] = "Add SPF TXT record to DNS"
        if auth_status["dkim"] != "ok":
            auth_status["details"]["dkim"] = "Run DKIM setup and add TXT record to DNS"
        if auth_status["dmarc"] != "ok":
            auth_status["details"]["dmarc"] = "Add DMARC TXT record to DNS"
        return JSONResponse({"ok": True, "data": auth_status})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/mail/auth/rspamd")
async def mail_rspamd_setup(body: DomainOnly):
    return _exec(mail_executor.setup_rspamd, body.domain)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the agent daemon."""
    log.info("HostHive Root Agent starting on %s:%d", BIND_HOST, BIND_PORT)
    uvicorn.run(
        app,
        host=BIND_HOST,
        port=BIND_PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
