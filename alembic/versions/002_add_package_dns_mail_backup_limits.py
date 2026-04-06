"""Add max_dns_domains, max_mail_domains, max_backups to packages table.

Revision ID: 002_add_package_dns_mail_backup_limits
Revises: 001_add_all_new_features
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_add_package_dns_mail_backup_limits"
down_revision: Union[str, None] = "001_add_all_new_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("packages", sa.Column("max_dns_domains", sa.Integer(), nullable=False, server_default=sa.text("10")))
    op.add_column("packages", sa.Column("max_mail_domains", sa.Integer(), nullable=False, server_default=sa.text("10")))
    op.add_column("packages", sa.Column("max_backups", sa.Integer(), nullable=False, server_default=sa.text("5")))


def downgrade() -> None:
    op.drop_column("packages", "max_backups")
    op.drop_column("packages", "max_mail_domains")
    op.drop_column("packages", "max_dns_domains")
