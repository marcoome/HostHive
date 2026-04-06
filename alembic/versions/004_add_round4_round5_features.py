"""Add round 4-5 features: redirects, mailing lists, runtime apps, directory
privacy, git deploy, domain caching/hotlink/error-pages, email spam filters,
email alias keep-local-copy, DNS DNSSEC, and user locale.

Revision ID: 004_add_round4_round5_features
Revises: 003_add_subdomain_support
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

# revision identifiers, used by Alembic.
revision: str = "004_add_round4_round5_features"
down_revision: Union[str, None] = "003_add_subdomain_support"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. NEW TABLE: redirects
    # ------------------------------------------------------------------
    op.create_table(
        "redirects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source_path", sa.String(2048), nullable=False),
        sa.Column("destination_url", sa.String(2048), nullable=False),
        sa.Column("redirect_type", sa.Integer(), nullable=False, server_default=sa.text("301")),
        sa.Column("is_regex", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 2. NEW TABLE: mailing_lists
    # ------------------------------------------------------------------
    op.create_table(
        "mailing_lists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("list_address", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_email", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_moderated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archive_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_message_size_kb", sa.Integer(), nullable=False, server_default=sa.text("10240")),
        sa.Column("reply_to_list", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 3. NEW TABLE: mailing_list_members
    # ------------------------------------------------------------------
    op.create_table(
        "mailing_list_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("list_id", UUID(as_uuid=True), sa.ForeignKey("mailing_lists.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subscribed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 4. NEW TABLE: runtime_apps  (inherits id, created_at, updated_at from TimestampedBase)
    # ------------------------------------------------------------------
    op.create_table(
        "runtime_apps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("app_type", sa.String(10), nullable=False),
        sa.Column("app_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("app_root", sa.String(512), nullable=False),
        sa.Column("entry_point", sa.String(255), nullable=False, server_default="app.js"),
        sa.Column("runtime_version", sa.String(20), nullable=False, server_default="20"),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("env_vars", JSON(), nullable=True),
        sa.Column("startup_command", sa.Text(), nullable=True),
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pid", sa.Integer(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 5. NEW TABLE: directory_privacy
    # ------------------------------------------------------------------
    op.create_table(
        "directory_privacy",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("auth_name", sa.String(255), nullable=False, server_default="Restricted Area"),
        sa.Column("users", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 6. NEW TABLE: git_deployments
    # ------------------------------------------------------------------
    op.create_table(
        "git_deployments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("repo_url", sa.String(1024), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column("deploy_key_public", sa.Text(), nullable=True),
        sa.Column("deploy_key_private", sa.Text(), nullable=True),
        sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("build_command", sa.String(2048), nullable=True),
        sa.Column("post_deploy_hook", sa.String(2048), nullable=True),
        sa.Column("webhook_secret", sa.String(255), nullable=True),
        sa.Column("last_deploy_at", sa.DateTime(), nullable=True),
        sa.Column("last_deploy_status", sa.String(32), nullable=True),
        sa.Column("last_commit_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 7. NEW TABLE: deploy_logs
    # ------------------------------------------------------------------
    op.create_table(
        "deploy_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("git_deployments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("commit_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # 8. domains -- caching, hotlink protection, custom error pages
    # ------------------------------------------------------------------
    op.add_column("domains", sa.Column("cache_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("domains", sa.Column("cache_type", sa.String(16), nullable=False, server_default="fastcgi"))
    op.add_column("domains", sa.Column("cache_ttl", sa.Integer(), nullable=False, server_default=sa.text("3600")))
    op.add_column("domains", sa.Column("cache_bypass_cookie", sa.String(255), nullable=False, server_default="wordpress_logged_in"))
    op.add_column("domains", sa.Column("hotlink_protection", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("domains", sa.Column("hotlink_allowed_domains", sa.Text(), nullable=True))
    op.add_column("domains", sa.Column("hotlink_extensions", sa.String(512), nullable=False, server_default="jpg,jpeg,png,gif,webp,svg,mp4,mp3"))
    op.add_column("domains", sa.Column("hotlink_redirect_url", sa.String(512), nullable=True))
    op.add_column("domains", sa.Column("custom_error_pages", JSON(), nullable=True))

    # ------------------------------------------------------------------
    # 9. email_accounts -- spam filter columns
    # ------------------------------------------------------------------
    op.add_column("email_accounts", sa.Column("spam_filter_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("email_accounts", sa.Column("spam_threshold", sa.Float(), nullable=False, server_default=sa.text("5.0")))
    op.add_column("email_accounts", sa.Column("spam_action", sa.String(20), nullable=False, server_default="move"))
    op.add_column("email_accounts", sa.Column("spam_whitelist", sa.Text(), nullable=True))
    op.add_column("email_accounts", sa.Column("spam_blacklist", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # 10. email_aliases -- keep_local_copy column + widen destination to Text
    # ------------------------------------------------------------------
    op.add_column("email_aliases", sa.Column("keep_local_copy", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column(
        "email_aliases",
        "destination",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
        server_default="",
    )

    # ------------------------------------------------------------------
    # 11. dns_zones -- DNSSEC columns
    # ------------------------------------------------------------------
    op.add_column("dns_zones", sa.Column("dnssec_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("dns_zones", sa.Column("dnssec_algorithm", sa.String(64), nullable=False, server_default="ECDSAP256SHA256"))
    op.add_column("dns_zones", sa.Column("ds_record", sa.Text(), nullable=True))

    # ------------------------------------------------------------------
    # 12. users -- locale column
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("locale", sa.String(10), nullable=True, server_default="en"))


def downgrade() -> None:
    # 12. users
    op.drop_column("users", "locale")

    # 11. dns_zones
    op.drop_column("dns_zones", "ds_record")
    op.drop_column("dns_zones", "dnssec_algorithm")
    op.drop_column("dns_zones", "dnssec_enabled")

    # 10. email_aliases
    op.alter_column(
        "email_aliases",
        "destination",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
        server_default="",
    )
    op.drop_column("email_aliases", "keep_local_copy")

    # 9. email_accounts
    op.drop_column("email_accounts", "spam_blacklist")
    op.drop_column("email_accounts", "spam_whitelist")
    op.drop_column("email_accounts", "spam_action")
    op.drop_column("email_accounts", "spam_threshold")
    op.drop_column("email_accounts", "spam_filter_enabled")

    # 8. domains
    op.drop_column("domains", "custom_error_pages")
    op.drop_column("domains", "hotlink_redirect_url")
    op.drop_column("domains", "hotlink_extensions")
    op.drop_column("domains", "hotlink_allowed_domains")
    op.drop_column("domains", "hotlink_protection")
    op.drop_column("domains", "cache_bypass_cookie")
    op.drop_column("domains", "cache_ttl")
    op.drop_column("domains", "cache_type")
    op.drop_column("domains", "cache_enabled")

    # 7. deploy_logs (must drop before git_deployments due to FK)
    op.drop_table("deploy_logs")

    # 6. git_deployments
    op.drop_table("git_deployments")

    # 5. directory_privacy
    op.drop_table("directory_privacy")

    # 4. runtime_apps
    op.drop_table("runtime_apps")

    # 3. mailing_list_members (must drop before mailing_lists due to FK)
    op.drop_table("mailing_list_members")

    # 2. mailing_lists
    op.drop_table("mailing_lists")

    # 1. redirects
    op.drop_table("redirects")
