from datetime import datetime, timedelta

import pytest
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.db.models import Payment, PaymentStatus
from bot.db.repositories import UserRepository
from bot.db.session import create_session_factory
from bot.keyboards.callbacks import PaymentAction, PaymentCB
from tests.conftest import KYIV
from tests.fakes import FakeSession, buttons
from tests.helpers import Clock, load_payments, load_user, make_job, setup_pool, update_pool

MOMENT = datetime(2026, 11, 5, 10, tzinfo=KYIV)
OCT_20 = datetime(2026, 10, 20, tzinfo=KYIV)


async def test_sends_one_request_per_member(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, active_since=OCT_20)
    job = make_job(bot, engine, Clock(MOMENT))

    report = await job.run()

    assert (report.created, report.requests_sent) == (2, 2)
    payments = await load_payments(engine)
    for tg, payment in zip((201, 202), payments, strict=True):
        [request] = api.sent_to(tg)
        assert "Час скинутися" in request.text
        assert "100 грн" in request.text and "листопад 2026" in request.text
        claim = PaymentCB(action=PaymentAction.CLAIM, payment_id=payment.id).pack()
        assert buttons(request) == [claim]
        assert payment.notified_at is not None


async def test_second_run_sends_nothing(engine: AsyncEngine, bot: Bot, api: FakeSession) -> None:
    await setup_pool(engine, active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()
    api.clear()

    clock.now = MOMENT + timedelta(hours=1)
    report = await job.run()

    assert (report.created, report.requests_sent, report.reminders_sent) == (0, 0, 0)
    assert api.requests == []


async def test_nothing_before_billing_moment(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, active_since=OCT_20)
    report = await make_job(bot, engine, Clock(MOMENT - timedelta(minutes=1))).run()
    assert report.created == 0
    assert api.requests == []


async def test_catches_up_after_downtime(engine: AsyncEngine, bot: Bot, api: FakeSession) -> None:
    await setup_pool(engine, member_tgs=(201,), active_since=datetime(2026, 8, 1, tzinfo=KYIV))

    report = await make_job(bot, engine, Clock(MOMENT + timedelta(days=1))).run()

    assert report.created == 3  # вересень, жовтень, листопад
    assert len(api.sent_to(201)) == 3


async def test_reminder_schedule(engine: AsyncEngine, bot: Bot, api: FakeSession) -> None:
    await setup_pool(engine, active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()

    reminders = []
    for days in (1, 2, 2.2, 3, 5, 6, 9):
        clock.now = MOMENT + timedelta(days=days)
        reminders.append((await job.run()).reminders_sent)

    # +2 дні: обом; того ж дня — ні; +5 днів: обом; далі тиша
    assert reminders == [0, 2, 0, 0, 2, 0, 0]
    assert "Нагадую" in api.sent_to(201)[-1].text
    assert all(p.reminders_sent == 2 for p in await load_payments(engine))


async def test_claimed_and_paid_are_not_reminded(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()
    first, second = await load_payments(engine)
    async with create_session_factory(engine)() as session:
        for payment_id, status in (
            (first.id, PaymentStatus.CLAIMED),
            (second.id, PaymentStatus.PAID),
        ):
            payment = await session.get(Payment, payment_id)
            assert payment is not None
            payment.status = status
        await session.commit()

    clock.now = MOMENT + timedelta(days=2)
    assert (await job.run()).reminders_sent == 0


async def test_paused_pool_gets_no_reminders(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    setup = await setup_pool(engine, active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()
    await update_pool(engine, setup.pool_id, is_paused=True)

    clock.now = MOMENT + timedelta(days=2)
    assert (await job.run()).reminders_sent == 0


async def test_blocked_member_owner_warned_once_then_retry_after_unblock(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, active_since=OCT_20)
    api.blocked = {201}
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)

    report = await job.run()

    assert report.requests_sent == 1
    assert len(report.blocked) == 1
    [warning] = api.sent_to(111)
    assert "заблоковано" in warning.text and "Учасник1" in warning.text
    assert (await load_user(engine, 201)).is_reachable is False

    # Наступні запуски не смикають заблокованого і не спамлять власника
    clock.now = MOMENT + timedelta(days=2)
    await job.run()
    assert len(api.sent_to(111)) == 1

    # Учасник розблокував бота й написав йому — отримує пропущений запит
    api.blocked.clear()
    async with create_session_factory(engine)() as session:
        await UserRepository(session).upsert(201, None, "Учасник1")
        await session.commit()
    clock.now = MOMENT + timedelta(days=2, hours=1)
    report = await job.run()
    assert report.requests_sent == 1
    assert "Час скинутися" in api.sent_to(201)[-1].text


async def test_network_failure_is_retried_next_run(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, member_tgs=(201,), active_since=OCT_20)
    api.failing = {201}
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)

    assert (await job.run()).requests_sent == 0
    [payment] = await load_payments(engine)
    assert payment.notified_at is None
    assert (await load_user(engine, 201)).is_reachable is True  # не плутаємо з блокуванням
    assert api.sent_to(111) == []

    api.failing.clear()
    clock.now = MOMENT + timedelta(hours=1)
    assert (await job.run()).requests_sent == 1


async def test_job_survives_unexpected_error(
    engine: AsyncEngine, bot: Bot, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = make_job(bot, engine, Clock(MOMENT))

    async def boom(*args: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(job, "_create_payments", boom)
    report = await job.run()  # не кидає виняток назовні
    assert report.created == 0
