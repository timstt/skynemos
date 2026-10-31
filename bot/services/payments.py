"""Платежі: створення за періоди та переходи статусів. Без aiogram.

Діаграма статусів:

    pending ──claim (учасник)──▶ claimed ──confirm (власник)──▶ paid
       ▲                            │
       └──────reject (власник)──────┘
    pending/claimed ──mark_paid (власник вручну або банк автоматично)──▶ paid

`paid` — кінцевий статус.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Payment, PaymentStatus, Pool, User
from bot.db.repositories import MemberRepository, PaymentRepository, PoolRepository
from bot.services.billing import billing_moment, due_periods, ensure_aware, reminders_due
from bot.services.errors import DomainError, ErrorCode

ALLOWED_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.PENDING: frozenset({PaymentStatus.CLAIMED, PaymentStatus.PAID}),
    PaymentStatus.CLAIMED: frozenset({PaymentStatus.PAID, PaymentStatus.PENDING}),
    PaymentStatus.PAID: frozenset(),
}


class PaidVia(StrEnum):
    """Хто підтвердив оплату. BANK — задел під фазу 2 (monobank API)."""

    OWNER_CONFIRMED = "owner_confirmed"  # власник підтвердив «Я скинув»
    OWNER_MANUAL = "owner_manual"  # власник позначив сам (готівка тощо)
    BANK = "bank"


@dataclass(frozen=True, slots=True)
class TransitionResult:
    payment: Payment
    changed: bool  # False — статус уже був цільовим (повторне натискання)


def apply_transition(payment: Payment, target: PaymentStatus, now: datetime) -> bool:
    """Змінює статус платежу. Повертає False, якщо статус уже `target`.

    Кидає DomainError(INVALID_TRANSITION) для недопустимого переходу.
    """
    if payment.status == target:
        return False
    if target not in ALLOWED_TRANSITIONS[payment.status]:
        raise DomainError(ErrorCode.INVALID_TRANSITION, f"{payment.status.value} -> {target.value}")

    if target is PaymentStatus.CLAIMED:
        payment.claimed_at = now
    elif target is PaymentStatus.PAID:
        payment.paid_at = now
    elif target is PaymentStatus.PENDING:
        payment.claimed_at = None
    payment.status = target
    return True


class PaymentService:
    def __init__(self, session: AsyncSession, tz: ZoneInfo, billing_hour: int) -> None:
        self.session = session
        self.tz = tz
        self.billing_hour = billing_hour
        self.pools = PoolRepository(session)
        self.members = MemberRepository(session)
        self.payments = PaymentRepository(session)

    # --- створення ---------------------------------------------------------

    def billing_moment(self, pool: Pool, period: date) -> datetime:
        return billing_moment(period, pool.billing_day, self.tz, self.billing_hour)

    async def create_due_payments(self, now: datetime) -> list[Payment]:
        """Створює платежі за всі періоди, що настали, для всіх активних зборів.

        Ідемпотентно: повторний виклик нічого не дублює. Після простою бота
        «доганяє» пропущені періоди (не більше MAX_CATCHUP_PERIODS).
        Повертає лише щойно створені платежі (їм треба надіслати повідомлення).
        """
        created: list[Payment] = []
        for pool in await self.pools.list_active():
            created += await self.create_due_payments_for_pool(pool, now)
        return created

    async def create_due_payments_for_pool(self, pool: Pool, now: datetime) -> list[Payment]:
        if pool.is_paused:
            return []
        periods = due_periods(
            now, pool.billing_day, self.tz, self.billing_hour, not_before=pool.active_since
        )
        if not periods:
            return []

        created: list[Payment] = []
        members = await self.members.list_active(pool.id)
        for period in periods:
            moment = self.billing_moment(pool, period)
            for member in members:
                # Хто приєднався після списання, платить з наступного циклу
                if ensure_aware(member.joined_at) > moment:
                    continue
                # Нульова частка (напр. 1 коп. на трьох) — нічого скидати
                if member.share_kop <= 0:
                    continue
                payment, is_new = await self.payments.create_if_absent(
                    member.id, period, member.share_kop
                )
                if is_new:
                    created.append(payment)
        return created

    # --- переходи статусів ---------------------------------------------------

    async def _load(self, payment_id: int) -> Payment:
        payment = await self.payments.get_with_relations(payment_id)
        if payment is None:
            raise DomainError(ErrorCode.PAYMENT_NOT_FOUND)
        return payment

    async def _transition(
        self, payment: Payment, target: PaymentStatus, now: datetime
    ) -> TransitionResult:
        changed = apply_transition(payment, target, now)
        await self.payments.save(payment)
        return TransitionResult(payment, changed)

    async def claim(self, payment_id: int, user: User, now: datetime) -> TransitionResult:
        """Учасник натиснув «Я скинув ✅»."""
        payment = await self._load(payment_id)
        if payment.member.user_id != user.id:
            raise DomainError(ErrorCode.NOT_A_MEMBER)
        if payment.status is PaymentStatus.PAID:
            return TransitionResult(payment, changed=False)  # уже підтверджено, не помилка
        return await self._transition(payment, PaymentStatus.CLAIMED, now)

    async def confirm(self, payment_id: int, owner: User, now: datetime) -> TransitionResult:
        """Власник: «Підтвердити» на заявці учасника."""
        payment = await self._load_for_owner(payment_id, owner)
        if payment.status is PaymentStatus.PENDING:
            # Учасник не заявляв оплату (або заявку вже відхилили) — це ручна позначка
            raise DomainError(ErrorCode.INVALID_TRANSITION, "pending -> paid via confirm")
        return await self._transition(payment, PaymentStatus.PAID, now)

    async def reject(self, payment_id: int, owner: User, now: datetime) -> TransitionResult:
        """Власник: «Не бачу оплати» — назад у pending."""
        payment = await self._load_for_owner(payment_id, owner)
        return await self._transition(payment, PaymentStatus.PENDING, now)

    async def mark_paid(self, payment_id: int, owner: User, now: datetime) -> TransitionResult:
        """Власник вручну позначає платіж оплаченим (наприклад, віддали готівкою)."""
        payment = await self._load_for_owner(payment_id, owner)
        return await self._transition(payment, PaymentStatus.PAID, now)

    async def mark_paid_automatically(
        self, payment: Payment, now: datetime, via: PaidVia = PaidVia.BANK
    ) -> TransitionResult:
        """Точка входу для фази 2: автопідтвердження за випискою банку."""
        return await self._transition(payment, PaymentStatus.PAID, now)

    async def _load_for_owner(self, payment_id: int, owner: User) -> Payment:
        payment = await self._load(payment_id)
        if payment.member.pool.owner_id != owner.id:
            raise DomainError(ErrorCode.NOT_POOL_OWNER)
        return payment

    # --- нагадування ---------------------------------------------------------

    async def record_reminder(self, payment: Payment, moment: datetime, now: datetime) -> None:
        """Фіксує надіслане нагадування. Пропущені під час простою не накопичуються."""
        payment.reminders_sent = max(payment.reminders_sent + 1, reminders_due(moment, now))
        payment.last_reminded_at = now
        await self.payments.save(payment)

    # --- перегляд ------------------------------------------------------------

    async def list_for_pool_period(self, pool: Pool, period: date) -> Sequence[Payment]:
        return await self.payments.list_for_pool_period(pool.id, period)
