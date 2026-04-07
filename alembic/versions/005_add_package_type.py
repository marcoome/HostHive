"""Add package_type column to packages table.

Introduces the ``package_type`` enum (``user`` / ``reseller``) which
distinguishes regular hosting plans from wholesale reseller allocations,
and adds a ``package_type`` column (default ``'user'``) to the
``packages`` table.

- ``user`` packages may only be assigned to ``UserRole.USER`` accounts.
- ``reseller`` packages may only be assigned to ``UserRole.RESELLER``
  accounts and define their wholesale pool (max sub-users, total disk,
  total bandwidth, total domains).

All existing package rows are backfilled to ``'user'`` via the column's
server default, preserving the pre-migration behavior.

Revision ID: 005_add_package_type
Revises: 004_add_round4_round5_features
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005_add_package_type"
down_revision: Union[str, None] = "004_add_round4_round5_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Name of the native Postgres enum type. Must match the ``name=`` kwarg
# used in api/models/packages.py::Package.package_type.
PACKAGE_TYPE_ENUM_NAME = "package_type"
PACKAGE_TYPE_VALUES = ("user", "reseller")


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Create the enum type if it does not already exist.
    #    (``checkfirst=True`` makes this a no-op when the type is
    #    already present, e.g. on environments bootstrapped from
    #    metadata rather than migrations.)
    # ------------------------------------------------------------------
    package_type_enum = sa.Enum(
        *PACKAGE_TYPE_VALUES,
        name=PACKAGE_TYPE_ENUM_NAME,
    )
    package_type_enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Add the packages.package_type column with a 'user' default so
    #    every pre-existing row is backfilled automatically.
    # ------------------------------------------------------------------
    op.add_column(
        "packages",
        sa.Column(
            "package_type",
            sa.Enum(
                *PACKAGE_TYPE_VALUES,
                name=PACKAGE_TYPE_ENUM_NAME,
                create_type=False,
            ),
            nullable=False,
            server_default="user",
        ),
    )

    # ------------------------------------------------------------------
    # 3. Index for filter queries (GET /packages?type=user|reseller).
    # ------------------------------------------------------------------
    op.create_index(
        "ix_packages_package_type",
        "packages",
        ["package_type"],
    )

    # ------------------------------------------------------------------
    # 4. Reseller-allocation columns (only meaningful when
    #    package_type == 'reseller'). Kept at zero for user-type rows.
    # ------------------------------------------------------------------
    op.add_column(
        "packages",
        sa.Column(
            "max_users",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "packages",
        sa.Column(
            "max_total_disk_gb",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "packages",
        sa.Column(
            "max_total_bandwidth_gb",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "packages",
        sa.Column(
            "max_total_domains",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    # 4. Reseller allocation columns
    op.drop_column("packages", "max_total_domains")
    op.drop_column("packages", "max_total_bandwidth_gb")
    op.drop_column("packages", "max_total_disk_gb")
    op.drop_column("packages", "max_users")

    # 3. Index
    op.drop_index("ix_packages_package_type", table_name="packages")

    # 2. Column
    op.drop_column("packages", "package_type")

    # 1. Enum type -- drop last so no column still references it.
    bind = op.get_bind()
    sa.Enum(
        *PACKAGE_TYPE_VALUES,
        name=PACKAGE_TYPE_ENUM_NAME,
    ).drop(bind, checkfirst=True)
