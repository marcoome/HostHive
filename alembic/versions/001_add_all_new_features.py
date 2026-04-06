"""Add all new features: 2FA, WebAuthn, antivirus, DNS cluster, database users,
autoresponder, incremental backups, Cloudflare DNS, reseller bandwidth, and
new columns on domains/packages/email_accounts.

Revision ID: 001_add_all_new_features
Revises: (initial migration)
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "001_add_all_new_features"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. users -- Two-Factor Authentication columns
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("totp_secret", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("totp_backup_codes", sa.JSON(), nullable=True))

    # ------------------------------------------------------------------
    # 2. users -- Backup preference columns
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("backup_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("backup_frequency", sa.String(16), nullable=True, server_default="daily"))
    op.add_column("users", sa.Column("backup_type", sa.String(16), nullable=True, server_default="full"))
    op.add_column("users", sa.Column("backup_retention_days", sa.Integer(), nullable=False, server_default=sa.text("30")))
    op.add_column("users", sa.Column("backup_retention_count", sa.Integer(), nullable=False, server_default=sa.text("5")))
    op.add_column("users", sa.Column("last_backup_at", sa.DateTime(), nullable=True))

    # ------------------------------------------------------------------
    # 3. NEW TABLE: webauthn_credentials
    # ------------------------------------------------------------------
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False, unique=True, index=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("device_name", sa.String(128), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # ------------------------------------------------------------------
    # 4. NEW TABLE: antivirus_scans (ScanResult)
    # ------------------------------------------------------------------
    scan_status_enum = sa.Enum("pending", "running", "completed", "failed", name="scan_status", create_type=False)
    op.execute("CREATE TYPE scan_status AS ENUM ('pending', 'running', 'completed', 'failed')")

    op.create_table(
        "antivirus_scans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("scan_path", sa.String(1024), nullable=False),
        sa.Column("status", scan_status_enum, nullable=False, server_default="pending"),
        sa.Column("files_scanned", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("infected_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("quarantined_files", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
    )

    # ------------------------------------------------------------------
    # 5. NEW TABLE: antivirus_quarantine (QuarantineEntry)
    # ------------------------------------------------------------------
    op.create_table(
        "antivirus_quarantine",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("scan_id", UUID(as_uuid=True), sa.ForeignKey("antivirus_scans.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("original_path", sa.String(1024), nullable=False),
        sa.Column("quarantine_path", sa.String(1024), nullable=False),
        sa.Column("threat_name", sa.String(512), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("restored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # ------------------------------------------------------------------
    # 6. NEW TABLE: dns_cluster_nodes
    # ------------------------------------------------------------------
    op.create_table(
        "dns_cluster_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hostname", sa.String(255), nullable=False, unique=True),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default=sa.text("53")),
        sa.Column("api_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False, server_default="slave"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 7. domains -- new columns
    # ------------------------------------------------------------------
    op.add_column("domains", sa.Column("webserver", sa.String(16), nullable=False, server_default="nginx"))
    op.add_column("domains", sa.Column("custom_nginx_config", sa.Text(), nullable=True))
    op.add_column("domains", sa.Column("catch_all_address", sa.String(255), nullable=True))
    # nginx_template type change: String(32) -> String(64) (widen)
    op.alter_column(
        "domains",
        "nginx_template",
        existing_type=sa.String(32),
        type_=sa.String(64),
        existing_nullable=True,
    )

    # ------------------------------------------------------------------
    # 8. packages -- new columns
    # ------------------------------------------------------------------
    op.add_column("packages", sa.Column("shell_access", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("packages", sa.Column("shell_type", sa.String(16), nullable=False, server_default="nologin"))
    op.add_column("packages", sa.Column(
        "created_by", UUID(as_uuid=True), nullable=True,
    ))
    op.create_foreign_key(
        "fk_packages_created_by_users",
        "packages", "users",
        ["created_by"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_packages_created_by", "packages", ["created_by"])

    # ------------------------------------------------------------------
    # 9. NEW TABLE: database_users
    # ------------------------------------------------------------------
    op.create_table(
        "database_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("database_id", UUID(as_uuid=True), sa.ForeignKey("databases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_encrypted", sa.String(512), nullable=False),
        sa.Column("permissions", sa.String(256), nullable=False, server_default="ALL"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 10. databases -- new columns
    # ------------------------------------------------------------------
    op.add_column("databases", sa.Column("remote_access", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("databases", sa.Column("allowed_hosts", sa.Text(), nullable=True, server_default='["localhost"]'))

    # ------------------------------------------------------------------
    # 11. email_accounts -- autoresponder & quota columns
    # ------------------------------------------------------------------
    op.add_column("email_accounts", sa.Column("autoresponder_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("email_accounts", sa.Column("autoresponder_subject", sa.String(255), nullable=True))
    op.add_column("email_accounts", sa.Column("autoresponder_body", sa.Text(), nullable=True))
    op.add_column("email_accounts", sa.Column("autoresponder_start_date", sa.DateTime(), nullable=True))
    op.add_column("email_accounts", sa.Column("autoresponder_end_date", sa.DateTime(), nullable=True))
    op.add_column("email_accounts", sa.Column("quota_used_mb", sa.Float(), nullable=False, server_default=sa.text("0.0")))
    op.add_column("email_accounts", sa.Column("max_emails_per_hour", sa.Integer(), nullable=False, server_default=sa.text("200")))

    # ------------------------------------------------------------------
    # 12. backups -- incremental backup & remote storage columns
    # ------------------------------------------------------------------
    op.add_column("backups", sa.Column(
        "parent_backup_id", UUID(as_uuid=True), nullable=True,
    ))
    op.create_foreign_key(
        "fk_backups_parent_backup_id",
        "backups", "backups",
        ["parent_backup_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column("backups", sa.Column("backup_metadata", JSONB(), nullable=True))
    op.add_column("backups", sa.Column("remote_key", sa.String(512), nullable=True))

    # ------------------------------------------------------------------
    # 13. dns_zones -- Cloudflare integration columns
    # ------------------------------------------------------------------
    op.add_column("dns_zones", sa.Column("cloudflare_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("dns_zones", sa.Column("cloudflare_config", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # 14. reseller_limits -- used_bandwidth_gb column
    # ------------------------------------------------------------------
    op.add_column("reseller_limits", sa.Column("used_bandwidth_gb", sa.Float(), nullable=False, server_default=sa.text("0.0")))


def downgrade() -> None:
    # 14. reseller_limits
    op.drop_column("reseller_limits", "used_bandwidth_gb")

    # 13. dns_zones
    op.drop_column("dns_zones", "cloudflare_config")
    op.drop_column("dns_zones", "cloudflare_enabled")

    # 12. backups
    op.drop_column("backups", "remote_key")
    op.drop_column("backups", "backup_metadata")
    op.drop_constraint("fk_backups_parent_backup_id", "backups", type_="foreignkey")
    op.drop_column("backups", "parent_backup_id")

    # 11. email_accounts
    op.drop_column("email_accounts", "max_emails_per_hour")
    op.drop_column("email_accounts", "quota_used_mb")
    op.drop_column("email_accounts", "autoresponder_end_date")
    op.drop_column("email_accounts", "autoresponder_start_date")
    op.drop_column("email_accounts", "autoresponder_body")
    op.drop_column("email_accounts", "autoresponder_subject")
    op.drop_column("email_accounts", "autoresponder_enabled")

    # 10. databases
    op.drop_column("databases", "allowed_hosts")
    op.drop_column("databases", "remote_access")

    # 9. database_users
    op.drop_table("database_users")

    # 8. packages
    op.drop_index("ix_packages_created_by", "packages")
    op.drop_constraint("fk_packages_created_by_users", "packages", type_="foreignkey")
    op.drop_column("packages", "created_by")
    op.drop_column("packages", "shell_type")
    op.drop_column("packages", "shell_access")

    # 7. domains
    op.alter_column(
        "domains",
        "nginx_template",
        existing_type=sa.String(64),
        type_=sa.String(32),
        existing_nullable=True,
    )
    op.drop_column("domains", "catch_all_address")
    op.drop_column("domains", "custom_nginx_config")
    op.drop_column("domains", "webserver")

    # 6. dns_cluster_nodes
    op.drop_table("dns_cluster_nodes")

    # 5. antivirus_quarantine
    op.drop_table("antivirus_quarantine")

    # 4. antivirus_scans
    op.drop_table("antivirus_scans")
    op.execute("DROP TYPE IF EXISTS scan_status")

    # 3. webauthn_credentials
    op.drop_table("webauthn_credentials")

    # 2. users -- backup preferences
    op.drop_column("users", "last_backup_at")
    op.drop_column("users", "backup_retention_count")
    op.drop_column("users", "backup_retention_days")
    op.drop_column("users", "backup_type")
    op.drop_column("users", "backup_frequency")
    op.drop_column("users", "backup_enabled")

    # 1. users -- 2FA
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
