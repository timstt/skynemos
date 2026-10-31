import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Pool, User
from bot.db.repositories import MemberRepository
from bot.services.errors import DomainError, ErrorCode
from bot.services.pools import MAX_MEMBERS, JoinStatus, NewPoolData, PoolService
from tests.conftest import MakeUser


def pool_data(**overrides: object) -> NewPoolData:
    fields: dict[str, object] = {
        "title": "YouTube Family",
        "total_amount_kop": 30_000,
        "billing_day": 5,
        "include_owner": True,
        "payment_details": "https://send.monobank.ua/jar/xxx",
    }
    fields.update(overrides)
    return NewPoolData(**fields)  # type: ignore[arg-type]


@pytest.fixture
def service(session: AsyncSession) -> PoolService:
    return PoolService(session)


async def _pool(service: PoolService, owner: User, **overrides: object) -> Pool:
    return await service.create_pool(owner, pool_data(**overrides))


async def test_create_pool(service: PoolService, make_user: MakeUser) -> None:
    owner = await make_user()
    pool = await _pool(service, owner, title="  Netflix  ")

    assert pool.title == "Netflix"
    assert pool.owner_share_kop == 30_000
    assert 16 <= len(pool.invite_token) <= 32
    other = await _pool(service, owner)
    assert other.invite_token != pool.invite_token


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"title": ""}, ErrorCode.INVALID_TITLE),
        ({"billing_day": 0}, ErrorCode.INVALID_BILLING_DAY),
        ({"payment_details": " "}, ErrorCode.INVALID_DETAILS),
        ({"total_amount_kop": 0}, ErrorCode.INVALID_AMOUNT),
    ],
)
async def test_create_pool_validation(
    service: PoolService, make_user: MakeUser, overrides: dict[str, object], code: ErrorCode
) -> None:
    with pytest.raises(DomainError) as exc:
        await _pool(service, await make_user(), **overrides)
    assert exc.value.code is code


async def test_join_splits_equally(service: PoolService, make_user: MakeUser) -> None:
    pool = await _pool(service, await make_user())  # 300 грн, власник у розподілі

    for name in ("Андрій", "Оля", "Макс", "Ira"):
        result = await service.join(pool.invite_token, await make_user(name))
        assert result.status is JoinStatus.JOINED

    members = await service.list_active_members(pool)
    assert [m.share_kop for m in members] == [6_000] * 4
    assert pool.owner_share_kop == 6_000
    assert result.members_count == 4


async def test_join_without_owner_remainder_to_first(
    service: PoolService, make_user: MakeUser
) -> None:
    pool = await _pool(service, await make_user(), include_owner=False, total_amount_kop=10_000)
    for _ in range(3):
        await service.join(pool.invite_token, await make_user())

    members = await service.list_active_members(pool)
    assert [m.share_kop for m in members] == [3_334, 3_333, 3_333]
    assert pool.owner_share_kop == 0


async def test_join_twice_does_not_duplicate(service: PoolService, make_user: MakeUser) -> None:
    pool = await _pool(service, await make_user())
    user = await make_user()

    await service.join(pool.invite_token, user)
    again = await service.join(pool.invite_token, user)

    assert again.status is JoinStatus.ALREADY_MEMBER
    assert again.members_count == 1


async def test_rejoin_reactivates_and_resets_custom_share(
    service: PoolService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool = await _pool(service, await make_user())
    user = await make_user()
    first = await service.join(pool.invite_token, user)
    members_repo = MemberRepository(session)
    await members_repo.set_share(first.member, 1_000, custom=True)
    await members_repo.set_active(first.member, False)

    result = await service.join(pool.invite_token, user)

    assert result.status is JoinStatus.REJOINED
    assert result.member.id == first.member.id
    assert result.member.share_is_custom is False
    assert result.member.share_kop == 15_000


async def test_owner_cannot_join_own_pool(service: PoolService, make_user: MakeUser) -> None:
    owner = await make_user()
    pool = await _pool(service, owner)

    for call in (service.join, service.preview_join):
        with pytest.raises(DomainError) as exc:
            await call(pool.invite_token, owner)
        assert exc.value.code is ErrorCode.OWNER_CANNOT_JOIN


async def test_pool_is_limited_to_max_members(service: PoolService, make_user: MakeUser) -> None:
    pool = await _pool(service, await make_user())
    for _ in range(MAX_MEMBERS):
        await service.join(pool.invite_token, await make_user())

    late = await make_user()
    for call in (service.join, service.preview_join):
        with pytest.raises(DomainError) as exc:
            await call(pool.invite_token, late)
        assert exc.value.code is ErrorCode.POOL_FULL


async def test_existing_member_can_open_link_of_full_pool(
    service: PoolService, make_user: MakeUser
) -> None:
    pool = await _pool(service, await make_user())
    first = await make_user()
    await service.join(pool.invite_token, first)
    for _ in range(MAX_MEMBERS - 1):
        await service.join(pool.invite_token, await make_user())

    preview = await service.preview_join(pool.invite_token, first)
    assert preview.already_member is True
    assert (await service.join(pool.invite_token, first)).status is JoinStatus.ALREADY_MEMBER


async def test_unknown_token(service: PoolService, make_user: MakeUser) -> None:
    with pytest.raises(DomainError) as exc:
        await service.join("nope", await make_user())
    assert exc.value.code is ErrorCode.POOL_NOT_FOUND


async def test_preview_estimates_share(service: PoolService, make_user: MakeUser) -> None:
    pool = await _pool(service, await make_user())
    await service.join(pool.invite_token, await make_user())

    preview = await service.preview_join(pool.invite_token, await make_user())

    assert preview.already_member is False
    assert preview.members_count == 1
    assert preview.estimated_share_kop == 10_000  # 300 грн на трьох з власником


async def test_custom_share_survives_new_member(
    service: PoolService, session: AsyncSession, make_user: MakeUser
) -> None:
    pool = await _pool(service, await make_user())
    first = await service.join(pool.invite_token, await make_user())
    await MemberRepository(session).set_share(first.member, 5_000, custom=True)

    await service.join(pool.invite_token, await make_user())

    shares = [m.share_kop for m in await service.list_active_members(pool)]
    assert shares == [5_000, 12_500]
    assert pool.owner_share_kop == 12_500


async def test_list_user_pools_and_access(service: PoolService, make_user: MakeUser) -> None:
    owner = await make_user()
    member = await make_user()
    stranger = await make_user()
    pool = await _pool(service, owner)
    await service.join(pool.invite_token, member)

    owner_pools = await service.list_user_pools(owner)
    member_pools = await service.list_user_pools(member)
    assert [p.id for p in owner_pools.owned] == [pool.id]
    assert owner_pools.memberships == []
    assert [m.pool_id for m in member_pools.memberships] == [pool.id]

    assert (await service.get_owned_pool(pool.id, owner)).id == pool.id
    assert (await service.get_membership(pool.id, member)).pool.title == "YouTube Family"
    with pytest.raises(DomainError) as exc:
        await service.get_owned_pool(pool.id, member)
    assert exc.value.code is ErrorCode.NOT_POOL_OWNER
    with pytest.raises(DomainError) as exc:
        await service.get_membership(pool.id, stranger)
    assert exc.value.code is ErrorCode.NOT_A_MEMBER
    with pytest.raises(DomainError) as exc:
        await service.get_owned_pool(999, owner)
    assert exc.value.code is ErrorCode.POOL_NOT_FOUND
