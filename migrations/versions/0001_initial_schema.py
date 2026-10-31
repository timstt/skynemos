"""initial schema: users, pools, members, payments

Revision ID: 0001
Revises:
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column("is_reachable", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )

    op.create_table(
        "pools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("total_amount_kop", sa.Integer(), nullable=False),
        sa.Column("billing_day", sa.SmallInteger(), nullable=False),
        sa.Column("include_owner", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("owner_share_kop", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payment_details", sa.Text(), nullable=False),
        sa.Column("invite_token", sa.String(length=32), nullable=False),
        sa.Column("is_paused", sa.Boolean(), server_default=sa.false(), nullable=False),
        _created_at(),
        sa.CheckConstraint("billing_day BETWEEN 1 AND 31", name=op.f("ck_pools_billing_day_range")),
        sa.CheckConstraint("owner_share_kop >= 0", name=op.f("ck_pools_owner_share_non_negative")),
        sa.CheckConstraint("total_amount_kop > 0", name=op.f("ck_pools_total_amount_positive")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_pools_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pools")),
        sa.UniqueConstraint("invite_token", name=op.f("uq_pools_invite_token")),
    )
    op.create_index(op.f("ix_pools_owner_id"), "pools", ["owner_id"])

    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pool_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("share_kop", sa.Integer(), server_default="0", nullable=False),
        sa.Column("share_is_custom", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created_at("joined_at"),
        sa.CheckConstraint("share_kop >= 0", name=op.f("ck_members_share_non_negative")),
        sa.ForeignKeyConstraint(
            ["pool_id"], ["pools.id"], name=op.f("fk_members_pool_id_pools"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_members_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_members")),
        sa.UniqueConstraint("pool_id", "user_id", name="uq_members_pool_id_user_id"),
    )
    op.create_index(op.f("ix_members_pool_id"), "members", ["pool_id"])
    op.create_index(op.f("ix_members_user_id"), "members", ["user_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("amount_kop", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "claimed",
                "paid",
                name="payment_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("reminders_sent", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_kop >= 0", name=op.f("ck_payments_amount_non_negative")),
        sa.CheckConstraint("reminders_sent >= 0", name=op.f("ck_payments_reminders_non_negative")),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_payments_member_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("member_id", "period", name="uq_payments_member_id_period"),
    )
    op.create_index(op.f("ix_payments_member_id"), "payments", ["member_id"])
    op.create_index(op.f("ix_payments_status"), "payments", ["status"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("members")
    op.drop_table("pools")
    op.drop_table("users")
