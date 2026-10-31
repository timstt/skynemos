from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Member, Payment, PaymentStatus, Pool, User
from bot.db.repositories import MemberRepository, PoolRepository
from bot.services.errors import DomainError, ErrorCode
from bot.services.payments import (
    ALLOWED_TRANSITIONS,
    PaymentService,
    Reminder,
    apply_transition,
)
from bot.services.pools import NewPoolData, PoolService
from tests.conftest import MakeUser

KYIV = ZoneInfo("Europe/Kyiv")
LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)
NOV = date(2026, 11, 1)
NOV_MOMENT = datetime(2026, 11, 5, 10, tzinfo=KYIV)


def kyiv(*args: int) -> datetime:
    return datetime(*args, tzinfo=KYIV)  # type: ignore[misc]


@pytest.fixture
def service(session: AsyncSession) -> PaymentService:
    return PaymentService(session, KYIV, billing_hour=10)


async def make_pool_with_members(
    session: AsyncSession,
    make_user: MakeUser,
    *,
    members: int = 2,
    total_kop: int = 30_000,
    billing_day: int = 5,
    include_owner: bool = True,
    active_since: datetime = LONG_AGO,
    joined_at: datetime = LONG_AGO,
) -> tuple[Pool, User, list[Member]]:
    owner = await make_user("Власник")
    pools = PoolService(session)
    pool = await pools.create_pool(
        owner, NewPoolData("Netflix", total_kop, billing_day, include_owner, "4441")
    )
    for i in range(members):
        await pools.join(pool.invite_token, await make_user(f"Учасник {i}"))
    await PoolRepository(session).update(pool, active_since=active_since)
    active = list(await MemberRepository(session).list_active(pool.id))
    for member in active:
        member.joined_at = joined_at
    await session.flush()
    return pool, owner, active


async def count_payments(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Payment))).scalar_one()


# --- створення платежів ------------------------------------------------------


async def test_creates_payment_per_member_at_billing_moment(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    _, _, members = await make_pool_with_members(session, make_user)

    assert await service.create_due_payments(NOV_MOMENT - timedelta(minutes=1)) != []  # жовтень
    created = await service.create_due_payments(NOV_MOMENT)

    assert {(p.member_id, p.period, p.amount_kop) for p in created} == {
        (m.id, NOV, 10_000) for m in members
    }
    assert all(p.status is PaymentStatus.PENDING for p in created)


async def test_creation_is_idempotent(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    await make_pool_with_members(session, make_user, active_since=kyiv(2026, 11, 1))

    first = await service.create_due_payments(NOV_MOMENT)
    second = await service.create_due_payments(NOV_MOMENT + timedelta(hours=1))
    third = await service.create_due_payments(NOV_MOMENT + timedelta(days=3))

    assert len(first) == 2
    assert second == third == []
    assert await count_payments(session) == 2


async def test_nothing_before_billing_moment(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    await make_pool_with_members(session, make_user, active_since=kyiv(2026, 11, 1))
    assert await service.create_due_payments(NOV_MOMENT - timedelta(seconds=1)) == []


async def test_paused_pool_is_skipped(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool, _, _ = await make_pool_with_members(session, make_user)
    await PoolRepository(session).update(pool, is_paused=True)

    assert await service.create_due_payments(NOV_MOMENT) == []
    assert await service.create_due_payments_for_pool(pool, NOV_MOMENT) == []


async def test_pool_created_after_billing_day_starts_next_month(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    await make_pool_with_members(
        session, make_user, active_since=kyiv(2026, 11, 10), joined_at=kyiv(2026, 11, 10)
    )

    assert await service.create_due_payments(kyiv(2026, 11, 20)) == []
    created = await service.create_due_payments(kyiv(2026, 12, 5, 10))
    assert {p.period for p in created} == {date(2026, 12, 1)}


async def test_member_who_joined_after_billing_pays_from_next_cycle(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool, _, members = await make_pool_with_members(
        session, make_user, members=1, active_since=kyiv(2026, 11, 1)
    )
    await service.create_due_payments(NOV_MOMENT)

    newcomer = await make_user("Новенький")
    await PoolService(session).join(pool.invite_token, newcomer)
    late = await MemberRepository(session).get_by_pool_and_user(pool.id, newcomer.id)
    assert late is not None
    late.joined_at = kyiv(2026, 11, 7)
    await session.flush()

    assert await service.create_due_payments(kyiv(2026, 11, 8)) == []
    december = await service.create_due_payments(kyiv(2026, 12, 5, 10))
    assert {p.member_id for p in december} == {members[0].id, late.id}


async def test_existing_payments_keep_amount_when_shares_change(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool, _, _ = await make_pool_with_members(
        session, make_user, members=1, active_since=kyiv(2026, 11, 1)
    )
    [payment] = await service.create_due_payments(NOV_MOMENT)
    assert payment.amount_kop == 15_000

    await PoolService(session).join(pool.invite_token, await make_user())  # частки → 100 грн

    await session.refresh(payment)
    assert payment.amount_kop == 15_000


async def test_catches_up_missed_periods_after_downtime(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    await make_pool_with_members(
        session, make_user, members=1, active_since=kyiv(2026, 7, 1), joined_at=kyiv(2026, 7, 1)
    )

    created = await service.create_due_payments(NOV_MOMENT + timedelta(days=1))

    # Пропущено 5 періодів (лип–лист), але доганяємо не більше трьох останніх
    assert sorted(p.period for p in created) == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]


async def test_zero_share_member_gets_no_payment(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    # 1 копійка на трьох: обом учасникам по 0, копійка у власника
    await make_pool_with_members(session, make_user, total_kop=1)
    assert await service.create_due_payments(NOV_MOMENT) == []


async def test_day_31_creates_february_payment_on_28th(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    await make_pool_with_members(
        session, make_user, members=1, billing_day=31, active_since=kyiv(2027, 2, 1)
    )
    assert await service.create_due_payments(kyiv(2027, 2, 28, 9)) == []
    created = await service.create_due_payments(kyiv(2027, 2, 28, 10))
    assert [p.period for p in created] == [date(2027, 2, 1)]


async def test_inactive_member_gets_no_payment(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    _, _, members = await make_pool_with_members(session, make_user)
    await MemberRepository(session).set_active(members[0], False)

    created = await service.create_due_payments(NOV_MOMENT)
    assert members[0].id not in {p.member_id for p in created}


# --- переходи статусів (чиста функція) ---------------------------------------

ALL_STATUSES = list(PaymentStatus)
NOW = datetime(2026, 11, 6, tzinfo=UTC)


@pytest.mark.parametrize("source", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_apply_transition_matrix(source: PaymentStatus, target: PaymentStatus) -> None:
    payment = Payment(status=source, amount_kop=1, reminders_sent=0)
    if source == target:
        assert apply_transition(payment, target, NOW) is False
    elif target in ALLOWED_TRANSITIONS[source]:
        assert apply_transition(payment, target, NOW) is True
        assert payment.status is target
    else:
        with pytest.raises(DomainError) as exc:
            apply_transition(payment, target, NOW)
        assert exc.value.code is ErrorCode.INVALID_TRANSITION
        assert payment.status is source


def test_paid_is_final() -> None:
    assert ALLOWED_TRANSITIONS[PaymentStatus.PAID] == frozenset()


def test_transition_timestamps() -> None:
    payment = Payment(status=PaymentStatus.PENDING, amount_kop=1, reminders_sent=0)
    apply_transition(payment, PaymentStatus.CLAIMED, NOW)
    assert payment.claimed_at == NOW
    apply_transition(payment, PaymentStatus.PENDING, NOW)
    assert payment.claimed_at is None
    apply_transition(payment, PaymentStatus.PAID, NOW)
    assert payment.paid_at == NOW


# --- переходи статусів через сервіс ------------------------------------------


async def _payment(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> tuple[Payment, User, User]:
    _, owner, members = await make_pool_with_members(session, make_user, members=1)
    payments = await service.create_due_payments(NOV_MOMENT)
    payment = next(p for p in payments if p.period == NOV)
    member_user = await session.get(User, members[0].user_id)
    assert member_user is not None
    return payment, owner, member_user


async def test_claim_confirm_flow(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    payment, owner, member = await _payment(service, session, make_user)

    claimed = await service.claim(payment.id, member, NOW)
    assert claimed.changed and claimed.payment.status is PaymentStatus.CLAIMED
    assert (await service.claim(payment.id, member, NOW)).changed is False  # подвійний клік

    confirmed = await service.confirm(payment.id, owner, NOW)
    assert confirmed.payment.status is PaymentStatus.PAID
    assert confirmed.payment.paid_at == NOW
    # Учасник ще раз тисне «Я скинув» на старому повідомленні — не помилка
    assert (await service.claim(payment.id, member, NOW)).changed is False


async def test_reject_returns_to_pending(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    payment, owner, member = await _payment(service, session, make_user)
    await service.claim(payment.id, member, NOW)

    result = await service.reject(payment.id, owner, NOW)

    assert result.payment.status is PaymentStatus.PENDING
    assert result.payment.claimed_at is None
    with pytest.raises(DomainError) as exc:
        await service.confirm(payment.id, owner, NOW)  # після відхилення нема що підтверджувати
    assert exc.value.code is ErrorCode.INVALID_TRANSITION


async def test_mark_paid_manually_from_pending(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    payment, owner, _ = await _payment(service, session, make_user)

    result = await service.mark_paid(payment.id, owner, NOW)

    assert result.payment.status is PaymentStatus.PAID
    with pytest.raises(DomainError):
        await service.reject(payment.id, owner, NOW)  # paid — кінцевий


async def test_permissions(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    payment, owner, member = await _payment(service, session, make_user)
    stranger = await make_user("Чужий")

    with pytest.raises(DomainError) as exc:
        await service.claim(payment.id, owner, NOW)
    assert exc.value.code is ErrorCode.NOT_A_MEMBER
    for action in (service.confirm, service.reject, service.mark_paid):
        for user in (member, stranger):
            with pytest.raises(DomainError) as exc:
                await action(payment.id, user, NOW)
            assert exc.value.code is ErrorCode.NOT_POOL_OWNER
    with pytest.raises(DomainError) as exc:
        await service.claim(999_999, member, NOW)
    assert exc.value.code is ErrorCode.PAYMENT_NOT_FOUND


async def test_automatic_confirmation_hook(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    payment, _, member = await _payment(service, session, make_user)
    await service.claim(payment.id, member, NOW)

    result = await service.mark_paid_automatically(payment, NOW)

    assert result.payment.status is PaymentStatus.PAID


async def test_record_reminder_skips_missed_ones(
    service: PaymentService, session: AsyncSession, make_user: MakeUser
) -> None:
    payment, _, _ = await _payment(service, session, make_user)

    await service.record_reminder(Reminder(payment, NOV_MOMENT), NOV_MOMENT + timedelta(days=2))
    assert payment.reminders_sent == 1

    # Після простою на 6-й день: одне нагадування закриває обидва пропущені
    payment.reminders_sent = 0
    await service.record_reminder(Reminder(payment, NOV_MOMENT), NOV_MOMENT + timedelta(days=6))
    assert payment.reminders_sent == 2
    assert payment.last_reminded_at == NOV_MOMENT + timedelta(days=6)
