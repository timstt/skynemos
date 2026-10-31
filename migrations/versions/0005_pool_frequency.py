"""pool frequency: monthly / yearly / once

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Наявні збори — щомісячні (сталий дефолт), поведінка не змінюється
    with op.batch_alter_table("pools") as batch:
        batch.add_column(
            sa.Column(
                "frequency",
                sa.Enum(
                    "monthly",
                    "yearly",
                    "once",
                    name="pool_frequency",
                    native_enum=False,
                    create_constraint=True,
                    length=16,
                ),
                server_default="monthly",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("billing_month", sa.SmallInteger(), nullable=True))
        batch.add_column(sa.Column("billing_year", sa.SmallInteger(), nullable=True))
        batch.create_check_constraint(
            "billing_month_range", "billing_month IS NULL OR billing_month BETWEEN 1 AND 12"
        )
        batch.create_check_constraint(
            "month_required", "frequency = 'monthly' OR billing_month IS NOT NULL"
        )
        batch.create_check_constraint(
            "year_required", "frequency != 'once' OR billing_year IS NOT NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("pools") as batch:
        batch.drop_constraint("year_required", type_="check")
        batch.drop_constraint("month_required", type_="check")
        batch.drop_constraint("billing_month_range", type_="check")
        batch.drop_constraint("pool_frequency", type_="check")
        batch.drop_column("billing_year")
        batch.drop_column("billing_month")
        batch.drop_column("frequency")
