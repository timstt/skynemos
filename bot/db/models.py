from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

# Стабільні імена обмежень, щоб Alembic-міграції були передбачуваними
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MAX_TITLE_LENGTH = 64
INVITE_TOKEN_LENGTH = 32


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Після INSERT одразу підтягувати серверні дефолти: в async лінива догрузка неможлива
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}


class PaymentStatus(enum.StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    PAID = "paid"


class Frequency(enum.StrEnum):
    """Як часто збір виставляє рахунок."""

    MONTHLY = "monthly"
    YEARLY = "yearly"  # раз на рік: billing_month + billing_day
    ONCE = "once"  # один раз: billing_year + billing_month + billing_day


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """`timestamptz`, що завжди пише UTC і завжди повертає datetime з поясом.

    Postgres і так зберігає момент часу, а SQLite (тести) відкидає пояс:
    київські 10:00 повернулися б як 10:00 UTC. Нормалізація до UTC прибирає різницю.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime is not allowed, use an aware one (UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def _now_column() -> Mapped[datetime]:
    # Python-дефолт: значення відоме одразу й однакове для Postgres і SQLite (тести)
    return mapped_column(UTCDateTime(), default=utcnow, server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    is_reachable: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = _now_column()

    owned_pools: Mapped[list[Pool]] = relationship(back_populates="owner")
    memberships: Mapped[list[Member]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        return self.first_name or (f"@{self.username}" if self.username else str(self.telegram_id))


class Pool(Base):
    """Збір: спільна регулярна витрата, яку оплачує власник."""

    __tablename__ = "pools"
    __table_args__ = (
        CheckConstraint("total_amount_kop > 0", name="total_amount_positive"),
        CheckConstraint("billing_day BETWEEN 1 AND 31", name="billing_day_range"),
        CheckConstraint("owner_share_kop >= 0", name="owner_share_non_negative"),
        CheckConstraint("owner_weight BETWEEN 1 AND 10", name="owner_weight_range"),
        CheckConstraint(
            "billing_month IS NULL OR billing_month BETWEEN 1 AND 12", name="billing_month_range"
        ),
        CheckConstraint(
            "frequency = 'monthly' OR billing_month IS NOT NULL", name="month_required"
        ),
        CheckConstraint("frequency != 'once' OR billing_year IS NOT NULL", name="year_required"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(MAX_TITLE_LENGTH), nullable=False)
    total_amount_kop: Mapped[int] = mapped_column(Integer, nullable=False)
    billing_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    include_owner: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Сума, яку фактично покриває власник: його частка, якщо він у розподілі, плюс
    # невкрита учасниками решта. Власник не є рядком у members.
    owner_share_kop: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    payment_details: Mapped[str] = mapped_column(Text, nullable=False)
    invite_token: Mapped[str] = mapped_column(
        String(INVITE_TOKEN_LENGTH), unique=True, nullable=False
    )
    is_paused: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = _now_column()
    # З якого моменту збір активний (створення або останнє зняття з паузи).
    # Платежі створюються лише за цикли, чий момент списання не раніше цієї дати.
    active_since: Mapped[datetime] = _now_column()
    frequency: Mapped[Frequency] = mapped_column(
        Enum(
            Frequency,
            name="pool_frequency",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            validate_strings=True,
        ),
        default=Frequency.MONTHLY,
        server_default=Frequency.MONTHLY.value,
    )
    billing_month: Mapped[int | None] = mapped_column(SmallInteger)  # для yearly / once
    billing_year: Mapped[int | None] = mapped_column(SmallInteger)  # для once
    # Скільки «часток» бере власник при розподілі за вагами (якщо include_owner)
    owner_weight: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    # Період, за який власнику вже надіслано підсумок на 3-й день (захист від повторів)
    digest_period: Mapped[date | None] = mapped_column(Date)

    owner: Mapped[User] = relationship(back_populates="owned_pools")
    members: Mapped[list[Member]] = relationship(
        back_populates="pool", cascade="all, delete-orphan", passive_deletes=True
    )


class Member(Base):
    """Учасник збору (не власник). Вихід зі збору = is_active=False, історія зберігається."""

    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("pool_id", "user_id", name="uq_members_pool_id_user_id"),
        CheckConstraint("share_kop >= 0", name="share_non_negative"),
        CheckConstraint("weight BETWEEN 1 AND 10", name="weight_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(
        ForeignKey("pools.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    share_kop: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # True, якщо власник вручну задав частку: авторозподіл її не чіпає
    share_is_custom: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Кількість «часток» учасника (родина з двох = 2); ручна частка має пріоритет
    weight: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    # Співвласник: може підтверджувати оплати, але не керувати збором
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
    joined_at: Mapped[datetime] = _now_column()

    pool: Mapped[Pool] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="member", cascade="all, delete-orphan", passive_deletes=True
    )


class Payment(Base):
    """Платіж учасника за місяць. `period` — перше число місяця."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("member_id", "period", name="uq_payments_member_id_period"),
        CheckConstraint("amount_kop >= 0", name="amount_non_negative"),
        CheckConstraint("reminders_sent >= 0", name="reminders_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)
    amount_kop: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda e: [m.value for m in e],
            validate_strings=True,
        ),
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
        index=True,
    )
    # Коли учаснику надіслано запит «скинь»; NULL — ще не доставлено (буде повтор)
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # «Нагадай завтра»: до цього моменту нагадувань немає, потім одне
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reminders_sent: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    last_reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = _now_column()
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    member: Mapped[Member] = relationship(back_populates="payments")
