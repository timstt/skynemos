"""Етап покращень C: річні та разові збори."""

from datetime import date, datetime, timedelta

import pytest
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bot.db.models import Frequency, Pool, utcnow
from bot.db.session import create_session_factory
from bot.keyboards.callbacks import NewPoolAction, NewPoolCB, PoolAction, PoolCB
from bot.services.billing import next_occurrence_year
from bot.services.errors import DomainError, ErrorCode
from bot.services.payments import PaymentService
from bot.services.pools import NewPoolData, PoolService, validate_schedule
from bot.services.validation import parse_day_month
from tests.conftest import KYIV, MakeUser
from tests.fakes import OWNER, FakeSession, Harness
from tests.helpers import Clock, load_payments, make_job, setup_pool, update_pool

# --- розбір дати ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("05.03", (5, 3)), ("5.3", (5, 3)), (" 31/12 ", (31, 12)), ("29-02", (29, 2))],
)
def test_parse_day_month(raw: str, expected: tuple[int, int]) -> None:
    assert parse_day_month(raw) == expected


@pytest.mark.parametrize("raw", ["", "5", "32.01", "30.02", "31.04", "05.13", "0.5", "5 березня"])
def test_parse_day_month_invalid(raw: str) -> None:
    with pytest.raises(DomainError) as exc:
        parse_day_month(raw)
    assert exc.value.code is ErrorCode.INVALID_DATE


def test_next_occurrence_year_is_strictly_after_today() -> None:
    today = date(2026, 10, 31)
    assert next_occurrence_year(20, 12, today) == 2026
    assert next_occurrence_year(31, 10, today) == 2027  # сьогодні — вже пізно
    assert next_occurrence_year(1, 1, today) == 2027
    assert next_occurrence_year(29, 2, date(2027, 3, 1)) == 2028


def test_validate_schedule() -> None:
    assert validate_schedule(Frequency.MONTHLY, 5, 3, 2026) == (None, None)
    assert validate_schedule(Frequency.YEARLY, 29, 2, None) == (2, None)
    assert validate_schedule(Frequency.ONCE, 28, 2, 2027) == (2, 2027)
    for freq, day, month, year in [
        (Frequency.YEARLY, 5, None, None),
        (Frequency.YEARLY, 31, 4, None),
        (Frequency.ONCE, 5, 3, None),
        (Frequency.ONCE, 29, 2, 2027),  # невисокосний рік
    ]:
        with pytest.raises(DomainError):
            validate_schedule(freq, day, month, year)


# --- сервіс і платежі -------------------------------------------------------------------


async def test_create_yearly_and_once_pools(session: AsyncSession, make_user: MakeUser) -> None:
    service = PoolService(session)
    owner = await make_user()
    yearly = await service.create_pool(
        owner, NewPoolData("Spotify рік", 120_000, 5, True, "4441", Frequency.YEARLY, 3)
    )
    once = await service.create_pool(
        owner, NewPoolData("Подарунок", 300_000, 20, True, "4441", Frequency.ONCE, 12, 2026)
    )
    assert (yearly.frequency, yearly.billing_month, yearly.billing_year) == (
        Frequency.YEARLY,
        3,
        None,
    )
    assert (once.billing_month, once.billing_year) == (12, 2026)

    with pytest.raises(DomainError) as exc:
        await service.create_pool(owner, NewPoolData("X", 100, 5, True, "4441", Frequency.ONCE, 3))
    assert exc.value.code is ErrorCode.INVALID_DATE


async def test_yearly_pool_bills_once_a_year(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    setup = await setup_pool(
        engine, member_tgs=(201,), active_since=datetime(2026, 1, 1, tzinfo=KYIV)
    )
    await update_pool(engine, setup.pool_id, frequency=Frequency.YEARLY, billing_month=3)
    clock = Clock(datetime(2026, 3, 5, 10, tzinfo=KYIV))
    job = make_job(bot, engine, clock)

    assert (await job.run()).created == 1
    for month in (4, 6, 12):
        clock.now = datetime(2026, month, 5, 10, tzinfo=KYIV)
        assert (await job.run()).created == 0
    clock.now = datetime(2027, 3, 5, 10, tzinfo=KYIV)
    assert (await job.run()).created == 1
    assert [p.period for p in await load_payments(engine)] == [date(2026, 3, 1), date(2027, 3, 1)]


async def test_once_pool_bills_exactly_once(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    setup = await setup_pool(
        engine, member_tgs=(201,), active_since=datetime(2026, 10, 1, tzinfo=KYIV)
    )
    await update_pool(
        engine, setup.pool_id, frequency=Frequency.ONCE, billing_day=20, billing_month=12,
        billing_year=2026,
    )  # fmt: skip
    clock = Clock(datetime(2026, 12, 20, 9, tzinfo=KYIV))
    job = make_job(bot, engine, clock)

    assert (await job.run()).created == 0
    clock.now = datetime(2026, 12, 20, 10, tzinfo=KYIV)
    assert (await job.run()).created == 1
    for later in (timedelta(days=31), timedelta(days=365), timedelta(days=800)):
        clock.now = datetime(2026, 12, 20, 10, tzinfo=KYIV) + later
        assert (await job.run()).created == 0

    async with create_session_factory(engine)() as s:
        pool = await s.get(Pool, setup.pool_id)
        assert pool is not None
        status = await PaymentService(s, KYIV, 10).pool_status(pool, clock.now)
    assert status.period == date(2026, 12, 1)
    assert status.next_billing is None


# --- діалог /new та меню -------------------------------------------------------------------


async def _new_pool(h: Harness, freq: NewPoolAction, when: str) -> Pool:
    await h.send(OWNER, "/new")
    await h.send(OWNER, "Подарунок")
    await h.send(OWNER, "3000")
    await h.click(OWNER, NewPoolCB(action=freq).pack())
    await h.send(OWNER, when)
    await h.click(OWNER, NewPoolCB(action=NewPoolAction.OWNER_YES).pack())
    await h.send(OWNER, "4441 1111 2222 3333")
    await h.click(OWNER, NewPoolCB(action=NewPoolAction.CONFIRM).pack())
    async with create_session_factory(h.engine)() as s:
        return (await s.execute(select(Pool))).scalar_one()


async def test_new_yearly_pool_dialog(harness: Harness) -> None:
    pool = await _new_pool(harness, NewPoolAction.FREQ_YEARLY, "05.03")

    assert (pool.frequency, pool.billing_day, pool.billing_month) == (Frequency.YEARLY, 5, 3)
    confirm_text = harness.api.texts_to(OWNER["id"])[-2]
    assert "щороку, 5 березня" in confirm_text and "3 000 грн на рік" in confirm_text


async def test_new_once_pool_dialog_picks_next_occurrence(harness: Harness) -> None:
    today = utcnow().astimezone(KYIV).date()
    pool = await _new_pool(harness, NewPoolAction.FREQ_ONCE, "20.12")

    expected_year = next_occurrence_year(20, 12, today)
    assert (pool.frequency, pool.billing_month, pool.billing_year) == (
        Frequency.ONCE,
        12,
        expected_year,
    )
    assert f"разово, 20 грудня {expected_year}" in harness.api.texts_to(OWNER["id"])[-2]


async def test_invalid_date_in_dialog(harness: Harness) -> None:
    await harness.send(OWNER, "/new")
    await harness.send(OWNER, "Подарунок")
    await harness.send(OWNER, "3000")
    await harness.click(OWNER, NewPoolCB(action=NewPoolAction.FREQ_YEARLY).pack())
    await harness.send(OWNER, "31.02")
    assert "Не розумію дату" in harness.api.texts_to(OWNER["id"])[-1]


async def test_edit_date_of_yearly_pool(harness: Harness) -> None:
    pool = await _new_pool(harness, NewPoolAction.FREQ_YEARLY, "05.03")

    await harness.click(OWNER, PoolCB(action=PoolAction.EDIT_DAY, pool_id=pool.id).pack())
    assert "дд.мм" in harness.api.texts_to(OWNER["id"])[-1]
    await harness.send(OWNER, "15.09")

    async with create_session_factory(harness.engine)() as s:
        updated = await s.get(Pool, pool.id)
        assert updated is not None
        assert (updated.billing_day, updated.billing_month) == (15, 9)
    assert "щороку, 15 вересня" in harness.api.texts_to(OWNER["id"])[-1]
