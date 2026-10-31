from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Member, Payment, PaymentStatus
from bot.db.repositories import (
    MemberRepository,
    PaymentRepository,
    PoolRepository,
    UserRepository,
)
from tests.conftest import MakePool, MakeUser

PERIOD = date(2026, 11, 1)


# --- users ---------------------------------------------------------------


async def test_user_upsert_creates_then_updates(session: AsyncSession) -> None:
    repo = UserRepository(session)
    created = await repo.upsert(42, "andriy", "Андрій")
    await repo.set_reachable(created.id, False)

    updated = await repo.upsert(42, "andriy_new", "Андрій К.")

    assert updated.id == created.id
    assert updated.username == "andriy_new"
    assert updated.is_reachable is True  # нова взаємодія означає, що бот знову доступний
    assert await repo.get_by_telegram_id(42) is updated
    assert await repo.get_by_telegram_id(43) is None


async def test_user_display_name(session: AsyncSession) -> None:
    repo = UserRepository(session)
    assert (await repo.upsert(1, "olya", "")).display_name == "@olya"
    assert (await repo.upsert(2, None, "Макс")).display_name == "Макс"


# --- pools ---------------------------------------------------------------


async def test_pool_create_and_lookup(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    owner = await make_user()
    pool = await make_pool(owner, invite_token="abc")
    repo = PoolRepository(session)

    assert pool.owner_share_kop == 30_000  # поки учасників немає, усе на власнику
    assert pool.is_paused is False
    found = await repo.get_by_invite_token("abc")
    assert found is not None and found.id == pool.id
    assert await repo.get_by_invite_token("nope") is None
    assert [p.id for p in await repo.list_by_owner(owner.id)] == [pool.id]


async def test_pool_without_owner_starts_with_full_owner_share(make_pool: MakePool) -> None:
    # Поки учасників немає, усю суму покриває власник, навіть якщо він не в розподілі
    pool = await make_pool(include_owner=False)
    assert pool.owner_share_kop == 30_000


async def test_list_active_skips_paused(session: AsyncSession, make_pool: MakePool) -> None:
    active = await make_pool()
    paused = await make_pool()
    repo = PoolRepository(session)
    await repo.update(paused, is_paused=True)

    assert [p.id for p in await repo.list_active()] == [active.id]


async def test_pool_update_rejects_unknown_field(
    session: AsyncSession, make_pool: MakePool
) -> None:
    pool = await make_pool()
    with pytest.raises(AttributeError):
        await PoolRepository(session).update(pool, not_a_field=1)


async def test_invite_token_unique(make_pool: MakePool) -> None:
    await make_pool(invite_token="same")
    with pytest.raises(IntegrityError):
        await make_pool(invite_token="same")


async def test_billing_day_check_constraint(make_pool: MakePool) -> None:
    with pytest.raises(IntegrityError):
        await make_pool(billing_day=32)


async def test_total_amount_check_constraint(make_pool: MakePool) -> None:
    with pytest.raises(IntegrityError):
        await make_pool(total_amount_kop=0)


async def test_delete_pool_cascades(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    pool = await make_pool()
    member = await MemberRepository(session).add(pool.id, (await make_user()).id, 10_000)
    await PaymentRepository(session).create_if_absent(member.id, PERIOD, 10_000)
    session.expunge_all()

    repo = PoolRepository(session)
    loaded = await repo.get(pool.id)
    assert loaded is not None
    await repo.delete(loaded)

    assert (await session.execute(select(Member))).first() is None
    assert (await session.execute(select(Payment))).first() is None


# --- members -------------------------------------------------------------


async def test_member_add_list_count(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    pool = await make_pool()
    repo = MemberRepository(session)
    andriy = await repo.add(pool.id, (await make_user("Андрій")).id)
    olya = await repo.add(pool.id, (await make_user("Оля")).id)
    await repo.set_active(olya, False)

    active = await repo.list_active(pool.id)
    assert [m.id for m in active] == [andriy.id]
    assert active[0].user.first_name == "Андрій"
    assert await repo.count_active(pool.id) == 1


async def test_member_unique_per_pool(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    pool = await make_pool()
    user = await make_user()
    repo = MemberRepository(session)
    await repo.add(pool.id, user.id)
    assert await repo.get_by_pool_and_user(pool.id, user.id) is not None
    with pytest.raises(IntegrityError):
        await repo.add(pool.id, user.id)


async def test_member_set_share(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    pool = await make_pool()
    repo = MemberRepository(session)
    member = await repo.add(pool.id, (await make_user()).id, 10_000)
    await repo.set_share(member, 5_000, custom=True)

    assert (member.share_kop, member.share_is_custom) == (5_000, True)


async def test_list_active_by_user(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    user = await make_user()
    pool_a = await make_pool(title="Netflix")
    pool_b = await make_pool(title="Інтернет")
    repo = MemberRepository(session)
    await repo.add(pool_a.id, user.id)
    left = await repo.add(pool_b.id, user.id)
    await repo.set_active(left, False)

    memberships = await repo.list_active_by_user(user.id)
    assert [m.pool.title for m in memberships] == ["Netflix"]
    assert memberships[0].pool.owner.first_name == "Власник"


# --- payments ------------------------------------------------------------


async def _member(session: AsyncSession, make_user: MakeUser, make_pool: MakePool) -> Member:
    pool = await make_pool()
    return await MemberRepository(session).add(pool.id, (await make_user()).id, 10_000)


async def test_create_if_absent_is_idempotent(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    member = await _member(session, make_user, make_pool)
    repo = PaymentRepository(session)

    first, created_first = await repo.create_if_absent(member.id, PERIOD, 10_000)
    second, created_second = await repo.create_if_absent(member.id, PERIOD, 99_999)

    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert second.amount_kop == 10_000
    assert first.status is PaymentStatus.PENDING
    assert first.reminders_sent == 0


async def test_create_if_absent_handles_race(
    session: AsyncSession,
    make_user: MakeUser,
    make_pool: MakePool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = await _member(session, make_user, make_pool)
    repo = PaymentRepository(session)
    existing, _ = await repo.create_if_absent(member.id, PERIOD, 10_000)

    # Імітуємо гонку: перша перевірка «не бачить» платіж, який уже існує
    original = repo.get_for_member_period
    calls = 0

    async def blind_first_lookup(member_id: int, period: date) -> Payment | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await original(member_id, period)

    monkeypatch.setattr(repo, "get_for_member_period", blind_first_lookup)
    payment, created = await repo.create_if_absent(member.id, PERIOD, 10_000)

    assert created is False
    assert payment.id == existing.id
    assert len((await session.execute(select(Payment))).scalars().all()) == 1


async def test_payment_unique_index(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    member = await _member(session, make_user, make_pool)
    session.add(Payment(member_id=member.id, period=PERIOD, amount_kop=1))
    await session.flush()
    session.add(Payment(member_id=member.id, period=PERIOD, amount_kop=1))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_payment_status_rejects_unknown_value(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    member = await _member(session, make_user, make_pool)
    session.add(Payment(member_id=member.id, period=PERIOD, amount_kop=1, status="refunded"))
    with pytest.raises(Exception, match="refunded"):
        await session.flush()


async def test_payment_listing(
    session: AsyncSession, make_user: MakeUser, make_pool: MakePool
) -> None:
    pool = await make_pool()
    members = MemberRepository(session)
    andriy = await members.add(pool.id, (await make_user("Андрій")).id, 10_000)
    olya = await members.add(pool.id, (await make_user("Оля")).id, 10_000)
    repo = PaymentRepository(session)

    for period in (date(2026, 9, 1), date(2026, 10, 1), PERIOD):
        await repo.create_if_absent(andriy.id, period, 10_000)
    p_olya, _ = await repo.create_if_absent(olya.id, PERIOD, 10_000)
    p_olya.status = PaymentStatus.CLAIMED
    await repo.save(p_olya)

    in_period = await repo.list_for_pool_period(pool.id, PERIOD)
    assert [p.member.user.first_name for p in in_period] == ["Андрій", "Оля"]

    history = await repo.list_for_member(andriy.id, limit=2)
    assert [p.period for p in history] == [PERIOD, date(2026, 10, 1)]

    claimed = await repo.list_by_status(PaymentStatus.CLAIMED, period=PERIOD)
    assert [p.id for p in claimed] == [p_olya.id]
    assert claimed[0].member.pool.owner.first_name == "Власник"
    assert len(await repo.list_by_status(PaymentStatus.PENDING)) == 3

    loaded = await repo.get_with_relations(p_olya.id)
    assert loaded is not None and loaded.member.user.first_name == "Оля"
