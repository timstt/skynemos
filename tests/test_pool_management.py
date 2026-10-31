from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Member, Payment, Pool, User
from bot.services.errors import DomainError, ErrorCode
from bot.services.pools import NewPoolData, PoolService
from tests.conftest import MakeUser

NOW = datetime(2026, 11, 10, tzinfo=UTC)


@pytest.fixture
def service(session: AsyncSession) -> PoolService:
    return PoolService(session)


async def _pool(
    service: PoolService, make_user: MakeUser, members: int = 2, total: int = 30_000
) -> tuple[Pool, User, list[Member]]:
    owner = await make_user("Власник")
    pool = await service.create_pool(owner, NewPoolData("Netflix", total, 5, True, "4441"))
    for i in range(members):
        await service.join(pool.invite_token, await make_user(f"У{i}"))
    return pool, owner, list(await service.list_active_members(pool))


def shares(members: list[Member]) -> list[int]:
    return [m.share_kop for m in members]


async def test_regenerate_invite_invalidates_old_link(
    service: PoolService, make_user: MakeUser
) -> None:
    pool, owner, _ = await _pool(service, make_user, members=0)
    old = pool.invite_token

    await service.regenerate_invite(pool.id, owner)

    assert pool.invite_token != old
    with pytest.raises(DomainError) as exc:
        await service.join(old, await make_user())
    assert exc.value.code is ErrorCode.POOL_NOT_FOUND


async def test_update_total_recalculates_and_reports_changes(
    service: PoolService, make_user: MakeUser
) -> None:
    pool, owner, members = await _pool(service, make_user)

    update = await service.update_total(pool.id, owner, 60_000)

    assert pool.total_amount_kop == 60_000
    assert shares(members) == [20_000, 20_000]
    assert {(c.old_kop, c.new_kop) for c in update.changes} == {(10_000, 20_000)}
    assert len(update.changes) == 2


async def test_update_total_resets_custom_shares_that_no_longer_fit(
    service: PoolService, make_user: MakeUser
) -> None:
    pool, owner, members = await _pool(service, make_user)
    await service.set_member_share(pool.id, owner, members[0].id, 25_000)

    update = await service.update_total(pool.id, owner, 20_000)

    assert update.custom_reset is True
    assert members[0].share_is_custom is False
    assert sum(shares(members)) + pool.owner_share_kop == 20_000


async def test_update_billing_day_and_details(service: PoolService, make_user: MakeUser) -> None:
    pool, owner, _ = await _pool(service, make_user, members=0)

    await service.update_billing_day(pool.id, owner, 31)
    await service.update_details(pool.id, owner, "  нова картка  ")

    assert (pool.billing_day, pool.payment_details) == (31, "нова картка")
    with pytest.raises(DomainError):
        await service.update_billing_day(pool.id, owner, 0)
    with pytest.raises(DomainError):
        await service.update_details(pool.id, owner, " ")


async def test_set_member_share_custom_and_back_to_auto(
    service: PoolService, make_user: MakeUser
) -> None:
    pool, owner, members = await _pool(service, make_user)  # 300 грн на трьох

    update = await service.set_member_share(pool.id, owner, members[0].id, 5_000)

    assert shares(members) == [5_000, 12_500]
    assert pool.owner_share_kop == 12_500
    assert {c.member.id for c in update.changes} == {members[0].id, members[1].id}

    await service.set_member_share(pool.id, owner, members[0].id, None)
    assert shares(members) == [10_000, 10_000]
    assert members[0].share_is_custom is False


async def test_set_member_share_rejects_overflow(service: PoolService, make_user: MakeUser) -> None:
    pool, owner, members = await _pool(service, make_user)
    await service.set_member_share(pool.id, owner, members[0].id, 20_000)

    for bad in (30_001, 10_001):  # більше за суму; разом з іншою ручною частиною — теж
        with pytest.raises(DomainError) as exc:
            await service.set_member_share(pool.id, owner, members[1].id, bad)
        assert exc.value.code is ErrorCode.INVALID_SHARE
    # Рівно залишок — можна; власнику тоді 0
    await service.set_member_share(pool.id, owner, members[1].id, 10_000)
    assert pool.owner_share_kop == 0


async def test_remove_member(
    service: PoolService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool, owner, members = await _pool(service, make_user)

    removal = await service.remove_member(pool.id, owner, members[0].id)

    assert removal.member.is_active is False
    assert removal.member.user.first_name == "У0"
    assert members[1].share_kop == 15_000
    assert [c.member.id for c in removal.changes] == [members[1].id]
    with pytest.raises(DomainError) as exc:
        await service.remove_member(pool.id, owner, members[0].id)  # уже видалений
    assert exc.value.code is ErrorCode.MEMBER_NOT_FOUND


async def test_member_from_other_pool_is_rejected(
    service: PoolService, make_user: MakeUser
) -> None:
    pool_a, owner, _ = await _pool(service, make_user)
    _, _, others = await _pool(service, make_user)

    with pytest.raises(DomainError) as exc:
        await service.remove_member(pool_a.id, owner, others[0].id)
    assert exc.value.code is ErrorCode.MEMBER_NOT_FOUND
    with pytest.raises(DomainError):
        await service.set_member_share(pool_a.id, owner, others[0].id, 100)


async def test_pause_and_resume_moves_active_since(
    service: PoolService, make_user: MakeUser
) -> None:
    pool, owner, _ = await _pool(service, make_user, members=0)

    await service.set_paused(pool.id, owner, True, NOW)
    assert pool.is_paused is True
    await service.set_paused(pool.id, owner, False, NOW)
    assert pool.is_paused is False
    assert pool.active_since == NOW

    # Повторне «відновити» не зсуває дату
    await service.set_paused(pool.id, owner, False, datetime(2027, 1, 1, tzinfo=UTC))
    assert pool.active_since == NOW


async def test_delete_pool_returns_members_and_cascades(
    service: PoolService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool, owner, members = await _pool(service, make_user)
    session.add(Payment(member_id=members[0].id, period=NOW.date().replace(day=1), amount_kop=1))
    await session.flush()

    deleted = await service.delete_pool(pool.id, owner)

    assert deleted.title == "Netflix"
    assert sorted(u.first_name for u in deleted.members) == ["У0", "У1"]
    for model in (Pool, Member, Payment):
        count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        assert count == 0


async def test_leave_pool(service: PoolService, make_user: MakeUser) -> None:
    pool, _, members = await _pool(service, make_user)
    leaver = members[0].user

    removal = await service.leave_pool(pool.id, leaver)

    assert removal.member.is_active is False
    assert removal.pool.owner.first_name == "Власник"
    assert members[1].share_kop == 15_000
    with pytest.raises(DomainError) as exc:
        await service.leave_pool(pool.id, leaver)
    assert exc.value.code is ErrorCode.NOT_A_MEMBER


@pytest.mark.parametrize(
    "action",
    ["regenerate", "total", "day", "details", "share", "remove", "pause", "delete"],
)
async def test_only_owner_can_manage(
    service: PoolService, make_user: MakeUser, action: str
) -> None:
    pool, _, members = await _pool(service, make_user)
    intruder = members[1].user  # навіть учасник цього збору
    calls = {
        "regenerate": lambda: service.regenerate_invite(pool.id, intruder),
        "total": lambda: service.update_total(pool.id, intruder, 100),
        "day": lambda: service.update_billing_day(pool.id, intruder, 3),
        "details": lambda: service.update_details(pool.id, intruder, "x"),
        "share": lambda: service.set_member_share(pool.id, intruder, members[0].id, 1),
        "remove": lambda: service.remove_member(pool.id, intruder, members[0].id),
        "pause": lambda: service.set_paused(pool.id, intruder, True, NOW),
        "delete": lambda: service.delete_pool(pool.id, intruder),
    }
    with pytest.raises(DomainError) as exc:
        await calls[action]()
    assert exc.value.code is ErrorCode.NOT_POOL_OWNER
