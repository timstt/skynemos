"""pools.active_since: from when the pool generates payments

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Три кроки, бо SQLite не дозволяє ADD COLUMN з NOT NULL і нестатичним дефолтом
    with op.batch_alter_table("pools") as batch:
        batch.add_column(sa.Column("active_since", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE pools SET active_since = created_at")
    with op.batch_alter_table("pools") as batch:
        batch.alter_column(
            "active_since",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    with op.batch_alter_table("pools") as batch:
        batch.drop_column("active_since")
