"""Підготовка даних для тестів джоби та кнопок оплати (з комітом у БД)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.db.models import Member, Payment, Pool, User
from bot.db.repositories import MemberRepository, PoolRepository, UserRepository
from bot.db.session import create_session_factory
from bot.scheduler import BillingJob
from bot.services.pools import NewPoolData, PoolService
from tests.conftest import KYIV

LONG_AGO = datetime(2025, 1, 1, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Setup:
    pool_id: int
    owner_tg: int
    member_tgs: list[int]


async def setup_pool(
    engine: AsyncEngine,
    *,
    owner_tg: int = 111,
    member_tgs: Sequence[int] = (201, 202),
    total_kop: int = 30_000,
    billing_day: int = 5,
    active_since: datetime = LONG_AGO,
) -> Setup:
    async with create_session_factory(engine)() as session:
        users = UserRepository(session)
        owner = await users.upsert(owner_tg, None, "Андрій")
        pools = PoolService(session)
        pool = await pools.create_pool(
            owner, NewPoolData("YouTube Family", total_kop, billing_day, True, "4441 1111")
        )
        for i, tg in enumerate(member_tgs):
            await pools.join(pool.invite_token, await users.upsert(tg, None, f"Учасник{i + 1}"))
        await PoolRepository(session).update(pool, active_since=active_since)
        for member in await MemberRepository(session).list_active(pool.id):
            member.joined_at = LONG_AGO
        await session.commit()
        return Setup(pool.id, owner_tg, list(member_tgs))


def make_job(bot: Bot, engine: AsyncEngine, clock: Clock) -> BillingJob:
    return BillingJob(
        bot, create_session_factory(engine), KYIV, billing_hour=10, clock=clock, send_delay=0
    )


async def load_payments(engine: AsyncEngine) -> list[Payment]:
    async with create_session_factory(engine)() as session:
        return list((await session.execute(select(Payment).order_by(Payment.id))).scalars())


async def load_user(engine: AsyncEngine, telegram_id: int) -> User:
    async with create_session_factory(engine)() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        assert user is not None
        return user


async def update_pool(engine: AsyncEngine, pool_id: int, **fields: object) -> None:
    async with create_session_factory(engine)() as session:
        pool = await session.get(Pool, pool_id)
        assert pool is not None
        await PoolRepository(session).update(pool, **fields)
        await session.commit()


async def set_member_joined(engine: AsyncEngine, member_id: int, when: datetime) -> None:
    async with create_session_factory(engine)() as session:
        member = await session.get(Member, member_id)
        assert member is not None
        member.joined_at = when
        await session.commit()
