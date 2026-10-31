"""weights, co-owners, snooze and owner digest marker

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Усі нові NOT NULL колонки мають сталий дефолт: наявні рядки поводяться як раніше
    with op.batch_alter_table("pools") as batch:
        batch.add_column(
            sa.Column("owner_weight", sa.SmallInteger(), server_default="1", nullable=False)
        )
        batch.add_column(sa.Column("digest_period", sa.Date(), nullable=True))
        batch.create_check_constraint("owner_weight_range", "owner_weight BETWEEN 1 AND 10")
    with op.batch_alter_table("members") as batch:
        batch.add_column(sa.Column("weight", sa.SmallInteger(), server_default="1", nullable=False))
        batch.add_column(
            sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_check_constraint("weight_range", "weight BETWEEN 1 AND 10")
    op.add_column(
        "payments", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.drop_column("snoozed_until")
    with op.batch_alter_table("members") as batch:
        batch.drop_constraint("weight_range", type_="check")
        batch.drop_column("is_admin")
        batch.drop_column("weight")
    with op.batch_alter_table("pools") as batch:
        batch.drop_constraint("owner_weight_range", type_="check")
        batch.drop_column("digest_period")
        batch.drop_column("owner_weight")
