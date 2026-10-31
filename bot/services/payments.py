"""Платежі: створення за періоди та переходи статусів. Без aiogram.

Діаграма статусів:

    pending ──claim (учасник)──▶ claimed ──confirm (власник)──▶ paid
       ▲                            │
       └──────reject (власник)──────┘
    pending/claimed ──mark_paid (власник вручну або банк автоматично)──▶ paid

`paid` — кінцевий статус.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Member, Payment, PaymentStatus, Pool, User
from bot.db.repositories import MemberRepository, PaymentRepository, PoolRepository
from bot.services.billing import (
    add_months,
    billing_moment,
    due_periods,
    ensure_aware,
    latest_due_period,
    reminders_due,
    should_remind,
)
from bot.services.errors import DomainError, ErrorCode

logger = logging.getLogger(__name__)

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
class PoolStatus:
    """Стан збору за останній період, що настав (для /status)."""

    pool: Pool
    period: date | None  # None — перше списання ще не настало
    payments: Sequence[Payment]
    not_billed_yet: Sequence[Member]  # приєдналися після списання: платять з наступного
    next_billing: datetime

    @property
    def paid_kop(self) -> int:
        return sum(p.amount_kop for p in self.payments if p.status is PaymentStatus.PAID)

    @property
    def expected_kop(self) -> int:
        return sum(p.amount_kop for p in self.payments)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    payment: Payment
    changed: bool  # False — статус уже був цільовим (повторне натискання)
    # True, якщо цей перехід у paid закрив останній неоплачений платіж періоду в зборі
    period_completed: bool = False


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
        if created:
            logger.info("Pool %s: created %s payment(s)", pool.id, len(created))
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
        old = payment.status
        changed = apply_transition(payment, target, now)
        await self.payments.save(payment)
        if changed:
            logger.info("Payment %s: %s -> %s", payment.id, old.value, target.value)
        completed = (
            changed
            and target is PaymentStatus.PAID
            and await self.payments.count_unpaid_in_pool_period(payment.member_id, payment.period)
            == 0
        )
        return TransitionResult(payment, changed, completed)

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

    async def payments_to_remind(self, now: datetime) -> list[tuple[Payment, datetime]]:
        """Неоплачені платежі, яким зараз час нагадати, разом з моментом списання."""
        result: list[tuple[Payment, datetime]] = []
        for payment in await self.payments.list_by_status(PaymentStatus.PENDING):
            if payment.notified_at is None or not self._deliverable(payment):
                continue
            moment = self.billing_moment(payment.member.pool, payment.period)
            # Сам запит «скинь» теж рахується: щойно доставлений не доганяємо нагадуванням
            last_contact = max(
                (ensure_aware(t) for t in (payment.last_reminded_at, payment.notified_at) if t),
                default=None,
            )
            if should_remind(moment, now, payment.reminders_sent, last_contact, self.tz):
                result.append((payment, moment))
        return result

    # --- доставка запитів «скинь» --------------------------------------------

    async def payments_to_notify(self) -> list[Payment]:
        """Платежі, про які учасник ще не отримав повідомлення (і може його отримати)."""
        return [p for p in await self.payments.list_unnotified_pending() if self._deliverable(p)]

    async def mark_notified(self, payment: Payment, now: datetime) -> None:
        payment.notified_at = now
        await self.payments.save(payment)

    @staticmethod
    def _deliverable(payment: Payment) -> bool:
        member = payment.member
        return member.is_active and member.user.is_reachable and not member.pool.is_paused

    # --- перегляд ------------------------------------------------------------

    async def list_for_pool_period(self, pool: Pool, period: date) -> Sequence[Payment]:
        return await self.payments.list_for_pool_period(pool.id, period)

    async def unpaid_for_pool(self, pool: Pool) -> Sequence[Payment]:
        """Що власник може позначити оплаченим вручну (виклик після перевірки прав)."""
        return await self.payments.list_unpaid_for_pool(pool.id)

    async def member_debt(self, member_id: int, *, before: date | None = None) -> list[Payment]:
        """Неоплачені платежі учасника (накопичений борг), від найстарішого.

        `before` — лише за періоди до вказаного (для блоку «ще не оплачено раніше»).
        """
        return [
            p
            for p in await self.payments.list_unpaid_for_member(member_id)
            if before is None or p.period < before
        ]

    async def member_history(self, member: Member, limit: int = 12) -> Sequence[Payment]:
        return await self.payments.list_for_member(member.id, limit)

    async def pool_status(self, pool: Pool, now: datetime) -> PoolStatus:
        period = latest_due_period(now, pool.billing_day, self.tz, self.billing_hour)
        next_billing = self.billing_moment(pool, add_months(period, 1))
        if self.billing_moment(pool, period) < ensure_aware(pool.active_since):
            # Збір створено (або знято з паузи) після останнього списання
            return PoolStatus(pool, None, [], [], next_billing)

        payments = await self.list_for_pool_period(pool, period)
        billed = {p.member_id for p in payments}
        newcomers = [m for m in await self.members.list_active(pool.id) if m.id not in billed]
        return PoolStatus(pool, period, payments, newcomers, next_billing)

    async def owner_statuses(self, owner: User, now: datetime) -> list[PoolStatus]:
        return [
            await self.pool_status(pool, now) for pool in await self.pools.list_by_owner(owner.id)
        ]
