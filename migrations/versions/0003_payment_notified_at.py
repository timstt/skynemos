"""payments.notified_at: when the payment request was delivered

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    # Платежі, створені до цієї міграції, вважаємо вже надісланими
    op.execute("UPDATE payments SET notified_at = created_at")


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.drop_column("notified_at")
