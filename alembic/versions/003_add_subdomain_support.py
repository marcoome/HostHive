"""Add parent_domain_id and is_subdomain to domains table.

Revision ID: 003_add_subdomain_support
Revises: 002_add_package_dns_mail_backup_limits
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_add_subdomain_support"
down_revision: Union[str, None] = "002_add_package_dns_mail_backup_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("parent_domain_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "domains",
        sa.Column("is_subdomain", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_domains_parent_domain_id", "domains", ["parent_domain_id"])
    op.create_foreign_key(
        "fk_domains_parent_domain_id",
        "domains",
        "domains",
        ["parent_domain_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_domains_parent_domain_id", "domains", type_="foreignkey")
    op.drop_index("ix_domains_parent_domain_id", table_name="domains")
    op.drop_column("domains", "is_subdomain")
    op.drop_column("domains", "parent_domain_id")
