"""Server migration service -- import accounts from cPanel and HestiaCP backups.

Supports:
- cPanel full backup (tar.gz with homedir/, mysql/, psql/, dnszones/, etc/)
- HestiaCP backup  (tar.gz with web/, dns/, mail/, db/, cron/, user.conf)
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import shutil
import tarfile
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from api.schemas.migration import (
    MigrationAnalysis,
    MigrationCronInfo,
    MigrationDatabaseInfo,
    MigrationDnsZoneInfo,
    MigrationDomainInfo,
    MigrationEmailInfo,
    MigrationUserInfo,
    SourceType,
)

logger = logging.getLogger("hosthive.migration")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UPLOAD_DIR = Path("/opt/hosthive/tmp/migrations")


def _ensure_upload_dir() -> Path:
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return _UPLOAD_DIR


def _safe_extract(tar: tarfile.TarFile, dest: str) -> None:
    """Extract a tarball while preventing path-traversal attacks."""
    dest_path = Path(dest).resolve()
    for member in tar.getmembers():
        member_path = (dest_path / member.name).resolve()
        if not str(member_path).startswith(str(dest_path)):
            raise ValueError(f"Path traversal detected in archive member: {member.name}")
    tar.extractall(dest, filter="data")


def _read_file_from_dir(base: Path, *parts: str) -> Optional[str]:
    """Read a text file relative to *base*, returning None if missing."""
    p = base.joinpath(*parts)
    if p.is_file():
        try:
            return p.read_text(errors="replace")
        except Exception:
            return None
    return None


def _find_files(base: Path, pattern: str) -> list[Path]:
    """Recursively find files matching a glob pattern."""
    return sorted(base.glob(pattern))


# ---------------------------------------------------------------------------
# Abstract migrator
# ---------------------------------------------------------------------------

class BaseMigrator(ABC):
    """Common interface for backup parsers."""

    def __init__(self, extract_dir: Path) -> None:
        self.extract_dir = extract_dir

    @abstractmethod
    def detect(self) -> bool:
        """Return True if the extracted directory looks like this backup type."""

    @abstractmethod
    def analyze(self) -> MigrationAnalysis:
        """Parse the backup and return a structured analysis."""

    @abstractmethod
    def get_sql_dump_path(self, db_name: str) -> Optional[Path]:
        """Return the path to the SQL dump for a given database, if it exists."""

    @abstractmethod
    def get_homedir_path(self, username: str) -> Optional[Path]:
        """Return the path to the user's home directory content."""


# ---------------------------------------------------------------------------
# cPanel migrator
# ---------------------------------------------------------------------------

class CpanelMigrator(BaseMigrator):
    """Parse a cPanel full backup tar.gz.

    cPanel backup structure (after extracting the outer tar.gz):
        <username>/
            homedir/          -- /home/<user>/ contents
            mysql/            -- MySQL .sql dumps
            psql/             -- PostgreSQL dumps (if any)
            dnszones/         -- BIND zone files
            etc/              -- passwd, shadow, etc.
            cp/<user>         -- cPanel metadata (email accounts, etc.)
            cron/             -- crontab file
            mysql.sql         -- grant statements
            meta/             -- backup metadata
    """

    # Regex to parse a BIND zone record count (SOA + individual records)
    _RR_RE = re.compile(r"^\S+\s+\d*\s*IN\s+", re.MULTILINE)

    def _find_root(self) -> Path:
        """Find the actual backup root (may be nested one level)."""
        children = list(self.extract_dir.iterdir())
        # cPanel backups typically contain a single directory named after the user
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return self.extract_dir

    def detect(self) -> bool:
        root = self._find_root()
        # cPanel backups always contain a homedir/ directory
        return (root / "homedir").is_dir() or (root / "mysql").is_dir()

    def parse_cpanel_backup(self, backup_path: str) -> MigrationAnalysis:
        """High-level entry: extract and analyze a cPanel backup tar.gz."""
        with tarfile.open(backup_path, "r:gz") as tar:
            _safe_extract(tar, str(self.extract_dir))
        return self.analyze()

    def analyze(self) -> MigrationAnalysis:
        root = self._find_root()
        username = root.name
        warnings: list[str] = []

        # -- Domains ----------------------------------------------------------
        domains: list[MigrationDomainInfo] = []
        # Main domain from userdata
        userdata_dir = root / "cp" / username
        if not userdata_dir.is_dir():
            userdata_dir = root / "userdata"

        # Try to discover domains from the dnszones directory
        dnszone_dir = root / "dnszones"
        zone_domains: set[str] = set()
        if dnszone_dir.is_dir():
            for zf in dnszone_dir.iterdir():
                if zf.is_file() and zf.suffix == ".db":
                    zone_domains.add(zf.stem)
                elif zf.is_file() and "." in zf.name:
                    zone_domains.add(zf.name)

        # Also check userdata/ for domain configs
        ud_dir = root / "userdata"
        if ud_dir.is_dir():
            for f in ud_dir.iterdir():
                if f.is_file() and f.name not in ("main", "cache") and not f.name.endswith("_SSL"):
                    zone_domains.add(f.name)

        for d in sorted(zone_domains):
            has_ssl = (ud_dir / f"{d}_SSL").is_file() if ud_dir.is_dir() else False
            domains.append(MigrationDomainInfo(
                name=d,
                document_root=f"/home/{username}/public_html" if not domains else f"/home/{username}/{d}",
                has_ssl=has_ssl,
            ))

        # If no domains found from zones, try the homedir
        if not domains:
            homedir = root / "homedir"
            if homedir.is_dir() and (homedir / "public_html").is_dir():
                domains.append(MigrationDomainInfo(
                    name=f"{username}.example.com",
                    document_root=f"/home/{username}/public_html",
                ))
                warnings.append(
                    "Could not determine main domain name; "
                    f"placeholder '{username}.example.com' used."
                )

        # -- Databases --------------------------------------------------------
        databases: list[MigrationDatabaseInfo] = []
        mysql_dir = root / "mysql"
        if mysql_dir.is_dir():
            for dump in mysql_dir.iterdir():
                if dump.is_file() and dump.suffix in (".sql", ".gz"):
                    db_name = dump.stem.removesuffix(".sql")
                    databases.append(MigrationDatabaseInfo(
                        name=db_name,
                        db_type="mysql",
                        has_dump=True,
                        size_bytes=dump.stat().st_size,
                    ))

        psql_dir = root / "psql"
        if psql_dir.is_dir():
            for dump in psql_dir.iterdir():
                if dump.is_file():
                    db_name = dump.stem.removesuffix(".sql")
                    databases.append(MigrationDatabaseInfo(
                        name=db_name,
                        db_type="postgresql",
                        has_dump=True,
                        size_bytes=dump.stat().st_size,
                    ))

        # -- Email accounts ---------------------------------------------------
        emails: list[MigrationEmailInfo] = []
        # cPanel stores email account info in etc/ or homedir/etc/
        etc_dir = root / "homedir" / "etc"
        if not etc_dir.is_dir():
            etc_dir = root / "etc"
        if etc_dir.is_dir():
            for domain_dir in etc_dir.iterdir():
                if domain_dir.is_dir():
                    passwd_file = domain_dir / "passwd"
                    if passwd_file.is_file():
                        for line in passwd_file.read_text(errors="replace").splitlines():
                            parts = line.split(":")
                            if len(parts) >= 1 and parts[0]:
                                local = parts[0]
                                quota = 0
                                # Quota is typically in the 5th field (bytes)
                                if len(parts) >= 5:
                                    try:
                                        quota = int(parts[4]) // (1024 * 1024)
                                    except (ValueError, IndexError):
                                        pass
                                emails.append(MigrationEmailInfo(
                                    address=f"{local}@{domain_dir.name}",
                                    domain=domain_dir.name,
                                    quota_mb=quota,
                                ))

        # -- DNS zones --------------------------------------------------------
        dns_zones: list[MigrationDnsZoneInfo] = []
        if dnszone_dir.is_dir():
            for zf in dnszone_dir.iterdir():
                if zf.is_file():
                    content = zf.read_text(errors="replace")
                    rc = len(self._RR_RE.findall(content))
                    dns_zones.append(MigrationDnsZoneInfo(
                        domain=zf.stem if zf.suffix == ".db" else zf.name,
                        record_count=rc,
                    ))

        # -- Cron jobs --------------------------------------------------------
        cron_jobs: list[MigrationCronInfo] = []
        cron_dir = root / "cron"
        cron_file = cron_dir / username if cron_dir.is_dir() else None
        if cron_file and cron_file.is_file():
            self._parse_crontab(cron_file.read_text(errors="replace"), cron_jobs)
        else:
            # Sometimes it's just a single file
            for cf in (root / "cron").glob("*") if (root / "cron").is_dir() else []:
                if cf.is_file():
                    self._parse_crontab(cf.read_text(errors="replace"), cron_jobs)

        # -- Version detection ------------------------------------------------
        version: Optional[str] = None
        meta_dir = root / "meta"
        if meta_dir.is_dir():
            ver_file = meta_dir / "cp_version"
            if ver_file.is_file():
                version = ver_file.read_text().strip()

        user_info = MigrationUserInfo(
            username=username,
            domains=domains,
            databases=databases,
            emails=emails,
            dns_zones=dns_zones,
            cron_jobs=cron_jobs,
        )

        return MigrationAnalysis(
            backup_id="",  # set by caller
            source_type=SourceType.CPANEL,
            source_version=version,
            users=[user_info],
            total_domains=len(domains),
            total_databases=len(databases),
            total_emails=len(emails),
            total_dns_zones=len(dns_zones),
            total_cron_jobs=len(cron_jobs),
            warnings=warnings,
        )

    def get_sql_dump_path(self, db_name: str) -> Optional[Path]:
        root = self._find_root()
        for ext in (".sql", ".sql.gz"):
            p = root / "mysql" / f"{db_name}{ext}"
            if p.is_file():
                return p
        for ext in (".sql", ".sql.gz"):
            p = root / "psql" / f"{db_name}{ext}"
            if p.is_file():
                return p
        return None

    def get_homedir_path(self, username: str) -> Optional[Path]:
        root = self._find_root()
        hd = root / "homedir"
        return hd if hd.is_dir() else None

    @staticmethod
    def _parse_crontab(content: str, out: list[MigrationCronInfo]) -> None:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("MAILTO"):
                continue
            parts = line.split(None, 5)
            if len(parts) >= 6:
                schedule = " ".join(parts[:5])
                command = parts[5]
                out.append(MigrationCronInfo(schedule=schedule, command=command))


# ---------------------------------------------------------------------------
# HestiaCP migrator
# ---------------------------------------------------------------------------

class HestiaMigrator(BaseMigrator):
    """Parse a HestiaCP user backup tar.gz.

    HestiaCP backup structure:
        <username>.YYYY-MM-DD_HH-MM-SS.tar  (outer)
            web/              -- domain directories + configs
            dns/              -- DNS zone files per domain
            mail/             -- mail domains + accounts
            db/               -- database dumps + configs
            cron/             -- cron.conf
            user.conf         -- user configuration
    """

    def _find_root(self) -> Path:
        """Find the actual backup root (may be nested one level)."""
        children = list(self.extract_dir.iterdir())
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return self.extract_dir

    def detect(self) -> bool:
        root = self._find_root()
        return (root / "user.conf").is_file() or (root / "web").is_dir()

    def parse_hestia_backup(self, backup_path: str) -> MigrationAnalysis:
        """High-level entry: extract and analyze a HestiaCP backup tar.gz."""
        with tarfile.open(backup_path, "r:*") as tar:
            _safe_extract(tar, str(self.extract_dir))
        return self.analyze()

    def analyze(self) -> MigrationAnalysis:
        root = self._find_root()
        warnings: list[str] = []

        # -- User config ------------------------------------------------------
        username = root.name
        email: Optional[str] = None
        user_conf = root / "user.conf"
        conf: dict[str, str] = {}
        if user_conf.is_file():
            for line in user_conf.read_text(errors="replace").splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    conf[k.strip()] = v.strip().strip("'\"")
            username = conf.get("NAME", username)
            email = conf.get("CONTACT", None)

        # -- Domains (web/) ---------------------------------------------------
        domains: list[MigrationDomainInfo] = []
        web_dir = root / "web"
        if web_dir.is_dir():
            for domain_conf in sorted(web_dir.glob("*.conf")):
                dname = domain_conf.stem
                dconf = self._parse_hestia_conf(domain_conf)
                has_ssl = dconf.get("SSL", "no").lower() == "yes"
                doc_root = dconf.get("DOCROOT", f"/home/{username}/web/{dname}/public_html")
                domains.append(MigrationDomainInfo(
                    name=dname,
                    document_root=doc_root,
                    has_ssl=has_ssl,
                ))
            # Also look for domain directories without .conf files
            for d in sorted(web_dir.iterdir()):
                if d.is_dir() and not any(dom.name == d.name for dom in domains):
                    domains.append(MigrationDomainInfo(
                        name=d.name,
                        document_root=f"/home/{username}/web/{d.name}/public_html",
                    ))

        # -- Databases (db/) --------------------------------------------------
        databases: list[MigrationDatabaseInfo] = []
        db_dir = root / "db"
        if db_dir.is_dir():
            # Hestia stores <db_name>.conf and <db_name>.sql.gz (or .sql)
            for db_conf in sorted(db_dir.glob("*.conf")):
                db_name = db_conf.stem
                dconf = self._parse_hestia_conf(db_conf)
                db_type = dconf.get("TYPE", "mysql").lower()
                # Find the dump
                dump = None
                for ext in (".sql.gz", ".sql"):
                    candidate = db_dir / f"{db_name}{ext}"
                    if candidate.is_file():
                        dump = candidate
                        break
                databases.append(MigrationDatabaseInfo(
                    name=db_name,
                    db_type=db_type if db_type in ("mysql", "postgresql") else "mysql",
                    has_dump=dump is not None,
                    size_bytes=dump.stat().st_size if dump else 0,
                ))

            # Pick up dumps without .conf files
            for dump_file in sorted(db_dir.glob("*.sql*")):
                db_name = dump_file.stem.removesuffix(".sql")
                if not any(d.name == db_name for d in databases):
                    databases.append(MigrationDatabaseInfo(
                        name=db_name,
                        db_type="mysql",
                        has_dump=True,
                        size_bytes=dump_file.stat().st_size,
                    ))

        # -- Email (mail/) ----------------------------------------------------
        emails: list[MigrationEmailInfo] = []
        mail_dir = root / "mail"
        if mail_dir.is_dir():
            for domain_dir in sorted(mail_dir.iterdir()):
                if domain_dir.is_dir():
                    # Each domain has accounts listed in passwd or in .conf files
                    for acct_conf in sorted(domain_dir.glob("*.conf")):
                        local = acct_conf.stem
                        aconf = self._parse_hestia_conf(acct_conf)
                        quota = 0
                        try:
                            quota = int(aconf.get("QUOTA", "0"))
                        except ValueError:
                            pass
                        emails.append(MigrationEmailInfo(
                            address=f"{local}@{domain_dir.name}",
                            domain=domain_dir.name,
                            quota_mb=quota,
                        ))

        # -- DNS (dns/) -------------------------------------------------------
        dns_zones: list[MigrationDnsZoneInfo] = []
        dns_dir = root / "dns"
        if dns_dir.is_dir():
            for zone_conf in sorted(dns_dir.glob("*.conf")):
                dname = zone_conf.stem
                content = zone_conf.read_text(errors="replace")
                record_count = sum(1 for line in content.splitlines() if line.strip() and not line.startswith("#"))
                dns_zones.append(MigrationDnsZoneInfo(
                    domain=dname,
                    record_count=record_count,
                ))

        # -- Cron (cron/) -----------------------------------------------------
        cron_jobs: list[MigrationCronInfo] = []
        cron_dir = root / "cron"
        if cron_dir.is_dir():
            cron_conf = cron_dir / "cron.conf"
            if cron_conf.is_file():
                self._parse_hestia_cron(cron_conf.read_text(errors="replace"), cron_jobs)

        user_info = MigrationUserInfo(
            username=username,
            email=email,
            domains=domains,
            databases=databases,
            emails=emails,
            dns_zones=dns_zones,
            cron_jobs=cron_jobs,
        )

        return MigrationAnalysis(
            backup_id="",  # set by caller
            source_type=SourceType.HESTIA,
            source_version=conf.get("HESTIA", None),
            users=[user_info],
            total_domains=len(domains),
            total_databases=len(databases),
            total_emails=len(emails),
            total_dns_zones=len(dns_zones),
            total_cron_jobs=len(cron_jobs),
            warnings=warnings,
        )

    def get_sql_dump_path(self, db_name: str) -> Optional[Path]:
        root = self._find_root()
        db_dir = root / "db"
        if db_dir.is_dir():
            for ext in (".sql.gz", ".sql"):
                p = db_dir / f"{db_name}{ext}"
                if p.is_file():
                    return p
        return None

    def get_homedir_path(self, username: str) -> Optional[Path]:
        root = self._find_root()
        web_dir = root / "web"
        return web_dir if web_dir.is_dir() else None

    @staticmethod
    def _parse_hestia_conf(path: Path) -> dict[str, str]:
        """Parse a HestiaCP key='value' config file."""
        result: dict[str, str] = {}
        if not path.is_file():
            return result
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip().strip("'\"")
        return result

    @staticmethod
    def _parse_hestia_cron(content: str, out: list[MigrationCronInfo]) -> None:
        """Parse HestiaCP cron.conf which uses KEY='VALUE' format per job."""
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # HestiaCP cron.conf: MIN='5' HOUR='0' DAY='*' MONTH='*' WDAY='*' CMD='command'
            fields: dict[str, str] = {}
            for match in re.finditer(r"(\w+)='([^']*)'", line):
                fields[match.group(1)] = match.group(2)
            if "CMD" in fields:
                schedule_parts = [
                    fields.get("MIN", "*"),
                    fields.get("HOUR", "*"),
                    fields.get("DAY", "*"),
                    fields.get("MONTH", "*"),
                    fields.get("WDAY", "*"),
                ]
                out.append(MigrationCronInfo(
                    schedule=" ".join(schedule_parts),
                    command=fields["CMD"],
                ))


# ---------------------------------------------------------------------------
# Auto-detection helper
# ---------------------------------------------------------------------------

def detect_backup_type(extract_dir: Path) -> BaseMigrator:
    """Return the appropriate migrator for a given extracted backup directory.

    Raises ValueError if the backup type cannot be determined.
    """
    cpanel = CpanelMigrator(extract_dir)
    if cpanel.detect():
        return cpanel

    hestia = HestiaMigrator(extract_dir)
    if hestia.detect():
        return hestia

    raise ValueError(
        "Unrecognised backup format. Supported: cPanel full backup, HestiaCP backup."
    )


def extract_backup(backup_path: str, dest_dir: str) -> Path:
    """Extract a backup archive to *dest_dir* and return the extraction root."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    with tarfile.open(backup_path, "r:*") as tar:
        _safe_extract(tar, str(dest))

    return dest
