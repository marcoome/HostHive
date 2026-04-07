"""WAF (Web Application Firewall) router -- /api/v1/waf.

This router edits nginx WAF rule files directly and reloads nginx via
``subprocess`` -- it does NOT proxy to the agent on port 7080.

All blocking file-system and subprocess work is dispatched to the default
executor through ``asyncio.get_running_loop().run_in_executor`` so the event
loop is never blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.core.security import get_current_user
from api.models.users import User
from api.schemas.waf import (
    GeoModeUpdate,
    GeoRule,
    GeoRulesListResponse,
    GeoStatus,
    WAFLogResponse,
    WAFModeUpdate,
    WAFRuleCreate,
    WAFRulesListResponse,
    WAFStatsResponse,
    WAFStatusResponse,
)
from api.services.geo_service import GeoBlockingService

logger = logging.getLogger(__name__)

router = APIRouter()


# ==========================================================================
# Paths -- mirror agent.executors.waf_executor so the same on-disk layout
# is read/written by both the panel API and (legacy) agent.
# ==========================================================================

NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
WAF_CONF_DIR = Path("/etc/nginx/waf")
WAF_RULES_DIR = WAF_CONF_DIR / "rules"
WAF_CUSTOM_DIR = WAF_CONF_DIR / "custom"
WAF_LOG_DIR = Path("/var/log/nginx/waf")
WAF_DEFAULT_RULES = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "templates"
    / "waf_rules.conf"
)

_WAF_INCLUDE_MARKER = "# HostHive WAF include"
_DOMAIN_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*$")


# ==========================================================================
# Generic helpers
# ==========================================================================


def _require_admin(user: User) -> None:
    if user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )


def _safe_domain(domain: str) -> str:
    """Validate and normalise a domain name -- prevents path traversal."""
    domain = (domain or "").strip().lower()
    if not _DOMAIN_RE.match(domain) or len(domain) > 253:
        raise HTTPException(status_code=400, detail=f"invalid domain name: {domain!r}")
    return domain


def _atomic_write(target: Path, content: str, mode: int = 0o644) -> None:
    """Atomically write *content* to *target* via temp-file + rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, mode)
        os.rename(tmp, str(target))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


async def _run_in_executor(func, *args, **kwargs):
    """Run a blocking *func* on the default executor."""
    loop = asyncio.get_running_loop()
    if kwargs:
        from functools import partial

        return await loop.run_in_executor(None, partial(func, *args, **kwargs))
    return await loop.run_in_executor(None, func, *args)


# ==========================================================================
# Path helpers
# ==========================================================================


def _ensure_waf_dirs() -> None:
    for d in (WAF_CONF_DIR, WAF_RULES_DIR, WAF_CUSTOM_DIR, WAF_LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _domain_waf_conf(domain: str) -> Path:
    return WAF_RULES_DIR / f"{domain}.conf"


def _domain_custom_conf(domain: str) -> Path:
    return WAF_CUSTOM_DIR / f"{domain}.conf"


def _domain_waf_log(domain: str) -> Path:
    return WAF_LOG_DIR / f"{domain}.log"


def _domain_waf_meta(domain: str) -> Path:
    return WAF_CONF_DIR / f"{domain}.meta.json"


def _read_meta(domain: str) -> dict[str, Any]:
    meta_path = _domain_waf_meta(domain)
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt WAF meta for %s, resetting", domain)
    return {"mode": "detect", "enabled": False}


def _write_meta(domain: str, meta: dict[str, Any]) -> None:
    _atomic_write(_domain_waf_meta(domain), json.dumps(meta, indent=2))


# ==========================================================================
# Nginx test + reload (blocking, must run in executor)
# ==========================================================================


def _nginx_test_and_reload() -> None:
    """Run ``nginx -t`` and ``nginx -s reload``.

    Raises HTTPException(400) on failure -- caller should not catch.
    """
    test = subprocess.run(
        ["nginx", "-t"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if test.returncode != 0:
        msg = (test.stderr or test.stdout or "").strip()
        logger.error("nginx config test failed: %s", msg)
        raise HTTPException(status_code=400, detail=f"nginx config test failed: {msg}")

    reload = subprocess.run(
        ["nginx", "-s", "reload"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if reload.returncode != 0:
        msg = (reload.stderr or reload.stdout or "").strip()
        logger.error("nginx reload failed: %s", msg)
        raise HTTPException(status_code=500, detail=f"nginx reload failed: {msg}")


# ==========================================================================
# WAF config generation
# ==========================================================================


def _generate_waf_conf(domain: str, mode: str = "detect") -> str:
    """Render the per-domain WAF include for nginx."""
    log_path = _domain_waf_log(domain)
    custom_path = _domain_custom_conf(domain)

    lines = [
        f"# HostHive WAF configuration for {domain}",
        f"# Mode: {mode}",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}Z",
        "",
        "# Load default WAF rules",
        f"include {WAF_DEFAULT_RULES};",
        "",
    ]

    if custom_path.exists():
        lines.extend(
            [
                "# Custom rules",
                f"include {custom_path};",
                "",
            ]
        )

    lines.extend(
        [
            "# WAF log for blocked/detected requests",
            f"set $waf_log_path {log_path};",
            f"set $waf_mode {mode};",
            "",
            "# Block requests matching WAF rules",
            "if ($waf_block = 1) {",
        ]
    )

    if mode == "block":
        lines.append("    return 403;")
    else:
        lines.append(f"    access_log {log_path} waf_log;")

    lines.extend(["}", ""])
    return "\n".join(lines)


def _add_waf_to_vhost(domain: str) -> bool:
    """Insert the WAF include directive into the vhost. Returns True if modified."""
    conf_path = NGINX_SITES_AVAILABLE / domain
    if not conf_path.exists():
        raise HTTPException(
            status_code=404, detail=f"vhost config not found for {domain}"
        )

    content = conf_path.read_text()
    if _WAF_INCLUDE_MARKER in content:
        return False

    waf_conf = _domain_waf_conf(domain)
    insert_line = f"\n    {_WAF_INCLUDE_MARKER}\n    include {waf_conf};\n"

    match = re.search(r"(server\s*\{)", content)
    if not match:
        raise HTTPException(
            status_code=500,
            detail=f"Could not find server block in vhost config for {domain}",
        )

    pos = match.end()
    new_content = content[:pos] + insert_line + content[pos:]
    _atomic_write(conf_path, new_content)
    return True


def _remove_waf_from_vhost(domain: str) -> bool:
    """Remove the WAF include directive from the vhost. Returns True if modified."""
    conf_path = NGINX_SITES_AVAILABLE / domain
    if not conf_path.exists():
        raise HTTPException(
            status_code=404, detail=f"vhost config not found for {domain}"
        )

    content = conf_path.read_text()
    if _WAF_INCLUDE_MARKER not in content:
        return False

    new_lines: list[str] = []
    skip_next = False
    for line in content.splitlines(keepends=True):
        if _WAF_INCLUDE_MARKER in line:
            skip_next = True
            continue
        if skip_next and "include" in line and "/etc/nginx/waf/" in line:
            skip_next = False
            continue
        skip_next = False
        new_lines.append(line)

    _atomic_write(conf_path, "".join(new_lines))
    return True


# ==========================================================================
# Blocking implementations -- run via run_in_executor
# ==========================================================================


def _impl_status(domain: str) -> dict[str, Any]:
    domain = _safe_domain(domain)
    meta = _read_meta(domain)

    blocked_count = 0
    log_path = _domain_waf_log(domain)
    if log_path.exists():
        try:
            with log_path.open() as fh:
                blocked_count = sum(1 for _ in fh)
        except OSError:
            blocked_count = 0

    return {
        "domain": domain,
        "enabled": meta.get("enabled", False),
        "mode": meta.get("mode", "detect"),
        "blocked_requests": blocked_count,
        "enabled_at": meta.get("enabled_at"),
        "disabled_at": meta.get("disabled_at"),
    }


def _impl_status_all() -> list[dict[str, Any]]:
    if not WAF_CONF_DIR.exists():
        return []

    domains: list[str] = []
    for meta_file in WAF_CONF_DIR.glob("*.meta.json"):
        # strip the ".meta.json" suffix
        name = meta_file.name[: -len(".meta.json")]
        try:
            domains.append(_safe_domain(name))
        except HTTPException:
            continue

    domains.sort()
    return [_impl_status(d) for d in domains]


def _impl_enable(domain: str) -> dict[str, Any]:
    domain = _safe_domain(domain)
    _ensure_waf_dirs()

    meta = _read_meta(domain)
    mode = meta.get("mode", "detect")

    waf_content = _generate_waf_conf(domain, mode)
    _atomic_write(_domain_waf_conf(domain), waf_content)

    custom_path = _domain_custom_conf(domain)
    if not custom_path.exists():
        _atomic_write(custom_path, f"# Custom WAF rules for {domain}\n")

    _add_waf_to_vhost(domain)

    meta["enabled"] = True
    meta["enabled_at"] = datetime.now(timezone.utc).isoformat() + "Z"
    _write_meta(domain, meta)

    _nginx_test_and_reload()

    return _impl_status(domain)


def _impl_disable(domain: str) -> dict[str, Any]:
    domain = _safe_domain(domain)

    _remove_waf_from_vhost(domain)

    meta = _read_meta(domain)
    meta["enabled"] = False
    meta["disabled_at"] = datetime.now(timezone.utc).isoformat() + "Z"
    _write_meta(domain, meta)

    _nginx_test_and_reload()

    return _impl_status(domain)


def _impl_list_rules(domain: str) -> dict[str, Any]:
    domain = _safe_domain(domain)
    rules: list[dict[str, Any]] = []

    if WAF_DEFAULT_RULES.exists():
        rule_id = 0
        for raw in WAF_DEFAULT_RULES.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                rules.append(
                    {
                        "id": f"default-{rule_id}",
                        "type": "default",
                        "rule": line,
                    }
                )
                rule_id += 1

    custom_path = _domain_custom_conf(domain)
    if custom_path.exists():
        current_id: int | None = None
        for raw in custom_path.read_text().splitlines():
            line = raw.strip()
            if line.startswith("# Rule ID:"):
                try:
                    current_id = int(line.split(":")[-1].strip())
                except ValueError:
                    current_id = None
                continue
            if line and not line.startswith("#") and current_id is not None:
                rules.append(
                    {
                        "id": f"custom-{current_id}",
                        "type": "custom",
                        "rule": line,
                    }
                )
                current_id = None

    return {"domain": domain, "rules": rules, "total": len(rules)}


def _impl_add_rule(domain: str, rule: str) -> dict[str, Any]:
    domain = _safe_domain(domain)
    _ensure_waf_dirs()

    if any(c in rule for c in ("`", "$(")):
        raise HTTPException(status_code=400, detail="Rule contains forbidden characters")

    custom_path = _domain_custom_conf(domain)
    existing = (
        custom_path.read_text()
        if custom_path.exists()
        else f"# Custom WAF rules for {domain}\n"
    )

    rule_id = sum(
        1
        for line in existing.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )

    rule_line = f"# Rule ID: {rule_id}\n{rule}\n"
    _atomic_write(custom_path, existing.rstrip("\n") + "\n" + rule_line + "\n")

    meta = _read_meta(domain)
    if meta.get("enabled"):
        waf_content = _generate_waf_conf(domain, meta.get("mode", "detect"))
        _atomic_write(_domain_waf_conf(domain), waf_content)
        _nginx_test_and_reload()

    return {"domain": domain, "rule_id": rule_id, "rule": rule, "added": True}


def _impl_delete_rule(domain: str, rule_id: int) -> dict[str, Any]:
    domain = _safe_domain(domain)

    custom_path = _domain_custom_conf(domain)
    if not custom_path.exists():
        raise HTTPException(
            status_code=404, detail=f"No custom rules found for {domain}"
        )

    lines = custom_path.read_text().splitlines(keepends=True)
    new_lines: list[str] = []
    skip_next = False
    found = False

    for line in lines:
        if f"# Rule ID: {rule_id}" in line:
            skip_next = True
            found = True
            continue
        if skip_next:
            skip_next = False
            continue
        new_lines.append(line)

    if not found:
        raise HTTPException(
            status_code=404, detail=f"Rule ID {rule_id} not found for {domain}"
        )

    _atomic_write(custom_path, "".join(new_lines))

    meta = _read_meta(domain)
    if meta.get("enabled"):
        waf_content = _generate_waf_conf(domain, meta.get("mode", "detect"))
        _atomic_write(_domain_waf_conf(domain), waf_content)
        _nginx_test_and_reload()

    return {"domain": domain, "rule_id": rule_id, "deleted": True}


def _impl_log(domain: str, lines: int) -> dict[str, Any]:
    domain = _safe_domain(domain)
    if lines < 1:
        lines = 1
    if lines > 10000:
        lines = 10000

    log_path = _domain_waf_log(domain)
    if not log_path.exists():
        return {"domain": domain, "entries": [], "total": 0}

    # Read the last N lines without shelling out -- keeps things simple and
    # safe even on systems without `tail`.
    try:
        with log_path.open("r", errors="replace") as fh:
            tail = fh.readlines()[-lines:]
    except OSError as exc:
        logger.error("Failed to read WAF log %s: %s", log_path, exc)
        return {"domain": domain, "entries": [], "total": 0}

    entries = [line.rstrip("\n") for line in tail if line.strip()]
    return {"domain": domain, "entries": entries, "total": len(entries)}


def _impl_set_mode(domain: str, mode: str) -> dict[str, Any]:
    domain = _safe_domain(domain)
    if mode not in ("detect", "block"):
        raise HTTPException(
            status_code=400, detail=f"Invalid WAF mode: {mode!r}"
        )

    meta = _read_meta(domain)
    meta["mode"] = mode
    _write_meta(domain, meta)

    if meta.get("enabled"):
        _ensure_waf_dirs()
        waf_content = _generate_waf_conf(domain, mode)
        _atomic_write(_domain_waf_conf(domain), waf_content)
        _nginx_test_and_reload()

    return _impl_status(domain)


_RULE_RE = re.compile(r"waf_rule_matched=([\w\-]+)")
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _impl_stats() -> dict[str, Any]:
    total_blocked = 0
    domains_with_waf = 0
    attack_counter: Counter[str] = Counter()
    ip_counter: Counter[str] = Counter()

    if WAF_CONF_DIR.exists():
        for meta_file in WAF_CONF_DIR.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if meta.get("enabled"):
                domains_with_waf += 1

    if WAF_LOG_DIR.exists():
        for log_file in WAF_LOG_DIR.glob("*.log"):
            try:
                with log_file.open("r", errors="replace") as fh:
                    for line in fh:
                        total_blocked += 1
                        m = _RULE_RE.search(line)
                        if m:
                            attack_counter[m.group(1)] += 1
                        ip_match = _IP_RE.search(line)
                        if ip_match:
                            ip_counter[ip_match.group(1)] += 1
            except OSError:
                continue

    top_attack_types = [
        {name: count} for name, count in attack_counter.most_common(10)
    ]
    top_ips = [{ip: count} for ip, count in ip_counter.most_common(10)]

    return {
        "total_blocked": total_blocked,
        "top_attack_types": top_attack_types,
        "top_ips": top_ips,
        "domains_with_waf": domains_with_waf,
    }


# ==========================================================================
# GET /status -- WAF status for all domains
# ==========================================================================


@router.get("/status", response_model=list[WAFStatusResponse])
async def waf_status_all(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_status_all)


# ==========================================================================
# POST /{domain}/enable -- enable WAF
# ==========================================================================


@router.post("/{domain}/enable", response_model=WAFStatusResponse)
async def waf_enable(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_enable, domain)


# ==========================================================================
# POST /{domain}/disable -- disable WAF
# ==========================================================================


@router.post("/{domain}/disable", response_model=WAFStatusResponse)
async def waf_disable(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_disable, domain)


# ==========================================================================
# GET /{domain}/rules -- list rules
# ==========================================================================


@router.get("/{domain}/rules", response_model=WAFRulesListResponse)
async def waf_list_rules(
    domain: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_list_rules, domain)


# ==========================================================================
# POST /{domain}/rules -- add custom rule
# ==========================================================================


@router.post("/{domain}/rules")
async def waf_add_rule(
    domain: str,
    body: WAFRuleCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_add_rule, domain, body.rule)


# ==========================================================================
# DELETE /{domain}/rules/{rule_id} -- delete rule
# ==========================================================================


@router.delete("/{domain}/rules/{rule_id}")
async def waf_delete_rule(
    domain: str,
    rule_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_delete_rule, domain, rule_id)


# ==========================================================================
# GET /{domain}/log -- blocked requests log
# ==========================================================================


@router.get("/{domain}/log", response_model=WAFLogResponse)
async def waf_log(
    domain: str,
    lines: int = 100,
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_log, domain, lines)


# ==========================================================================
# PUT /{domain}/mode -- set detect/block mode
# ==========================================================================


@router.put("/{domain}/mode")
async def waf_set_mode(
    domain: str,
    body: WAFModeUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_set_mode, domain, body.mode)


# ==========================================================================
# GET /stats -- total blocked requests, top attack types, top IPs
# ==========================================================================


@router.get("/stats", response_model=WAFStatsResponse)
async def waf_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return await _run_in_executor(_impl_stats)


# ==========================================================================
# Geo-blocking endpoints (already direct -- GeoBlockingService is local)
# ==========================================================================

_geo = GeoBlockingService()


@router.get("/geo/status", response_model=GeoStatus)
async def geo_status(
    current_user: User = Depends(get_current_user),
):
    """Check if GeoIP2 module is installed and the MaxMind database is current."""
    _require_admin(current_user)
    return await _geo.get_status()


@router.get("/geo/rules", response_model=GeoRulesListResponse)
async def geo_list_rules(
    current_user: User = Depends(get_current_user),
):
    """List all current geo-blocking rules."""
    _require_admin(current_user)
    return await _geo.list_rules()


@router.post("/geo/rules", response_model=GeoRulesListResponse)
async def geo_add_rule(
    body: GeoRule,
    current_user: User = Depends(get_current_user),
):
    """Add a country block or allow rule."""
    _require_admin(current_user)
    return await _geo.add_rule(body.country_code, body.action)


@router.delete("/geo/rules/{country_code}", response_model=GeoRulesListResponse)
async def geo_delete_rule(
    country_code: str,
    current_user: User = Depends(get_current_user),
):
    """Remove a geo-blocking rule by country code."""
    _require_admin(current_user)
    cc = country_code.upper().strip()
    if len(cc) != 2 or not cc.isalpha():
        raise HTTPException(status_code=400, detail="Invalid country code")
    return await _geo.remove_rule(cc)


@router.put("/geo/mode", response_model=GeoRulesListResponse)
async def geo_set_mode(
    body: GeoModeUpdate,
    current_user: User = Depends(get_current_user),
):
    """Set geo-blocking mode: whitelist or blacklist."""
    _require_admin(current_user)
    return await _geo.set_mode(body.mode)


@router.post("/geo/update-db")
async def geo_update_db(
    current_user: User = Depends(get_current_user),
):
    """Trigger geoipupdate to refresh the MaxMind GeoLite2-Country database."""
    _require_admin(current_user)
    result = await _geo.update_database()
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Update failed"))
    return result
