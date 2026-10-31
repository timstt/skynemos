"""Етап покращень B: «Нагадай завтра», підсумок власнику, ваги, співвласник."""

from datetime import datetime, timedelta

import pytest
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bot.db.models import Member, PaymentStatus, Pool, utcnow
from bot.db.repositories import UserRepository
from bot.db.session import create_session_factory
from bot.keyboards.callbacks import (
    MemberAction,
    MemberCB,
    PaymentAction,
    PaymentCB,
    PoolAction,
    PoolCB,
)
from bot.services.billing import billing_moment, latest_due_period
from bot.services.errors import DomainError, ErrorCode
from bot.services.payments import PaymentService
from bot.services.pools import NewPoolData, PoolService
from tests.conftest import KYIV, MakeUser
from tests.fakes import GUEST, OWNER, FakeSession, Harness
from tests.helpers import Clock, load_payments, make_job, setup_pool

MOMENT = datetime(2026, 11, 5, 10, tzinfo=KYIV)
OCT_20 = datetime(2026, 10, 20, tzinfo=KYIV)
SECOND = {"id": 223, "is_bot": False, "first_name": "Макс"}


def pay_cb(action: PaymentAction, payment_id: int) -> str:
    return PaymentCB(action=action, payment_id=payment_id).pack()


# --- «Нагадай завтра» -------------------------------------------------------------


async def test_snooze_postpones_and_sends_one_extra_reminder(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, member_tgs=(201,), active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()
    [payment] = await load_payments(engine)
    async with create_session_factory(engine)() as s:
        member_user = await UserRepository(s).get_by_telegram_id(201)
        assert member_user is not None
        snoozed = await PaymentService(s, KYIV, 10).snooze(
            payment.id, member_user, MOMENT + timedelta(hours=1)
        )
        await s.commit()
    assert snoozed.snoozed_until == datetime(2026, 11, 6, 10, tzinfo=KYIV)

    sent = []
    for offset in (timedelta(hours=2), timedelta(hours=23), timedelta(days=1),
                   timedelta(days=1, hours=1), timedelta(days=2)):  # fmt: skip
        clock.now = MOMENT + offset
        sent.append((await job.run()).reminders_sent)

    # до 6-го 10:00 тиша; о 10:00 — нагадування «як просив»; 7-го — звичайне за розкладом
    assert sent == [0, 0, 1, 0, 1]
    texts_201 = [m.text for m in api.sent_to(201)]
    assert "Як ти просив(-ла)" in texts_201[1]
    assert "Нагадую 🙂" in texts_201[2]
    [payment] = await load_payments(engine)
    assert payment.reminders_sent == 1  # відкладене не рахується в ліміт
    assert payment.snoozed_until is None


async def test_snooze_button(harness: Harness) -> None:
    now = utcnow()
    period = latest_due_period(now, 1, KYIV, 10)
    await setup_pool(
        harness.engine,
        owner_tg=OWNER["id"],
        member_tgs=(GUEST["id"],),
        billing_day=1,
        active_since=billing_moment(period, 1, KYIV, 10),
    )
    await make_job(harness.bot, harness.engine, Clock(now)).run()
    [payment] = await load_payments(harness.engine)
    harness.api.clear()

    await harness.click(GUEST, pay_cb(PaymentAction.SNOOZE, payment.id))
    [payment] = await load_payments(harness.engine)
    assert payment.snoozed_until is not None
    assert harness.api.texts_to(GUEST["id"]) == []  # лише спливаюче вікно

    # Після «Я скинув» відкладати вже нічого
    await harness.click(GUEST, pay_cb(PaymentAction.CLAIM, payment.id))
    await harness.click(GUEST, pay_cb(PaymentAction.SNOOZE, payment.id))
    [payment] = await load_payments(harness.engine)
    assert payment.status is PaymentStatus.CLAIMED


# --- підсумок власнику на 3-й день ------------------------------------------------


async def test_owner_digest_on_day_three_once(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()

    clock.now = MOMENT + timedelta(days=2, hours=23)
    assert (await job.run()).digests_sent == 0
    clock.now = MOMENT + timedelta(days=3)
    assert (await job.run()).digests_sent == 1
    clock.now = MOMENT + timedelta(days=4)
    assert (await job.run()).digests_sent == 0

    [digest] = api.sent_to(111)
    assert "скинули 0 з 2" in digest.text
    assert "❌" in digest.text and "Зібрано: 0 грн з 200 грн" in digest.text


async def test_no_digest_when_everyone_paid(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    await setup_pool(engine, active_since=OCT_20)
    clock = Clock(MOMENT)
    job = make_job(bot, engine, clock)
    await job.run()
    async with create_session_factory(engine)() as s:
        owner = await UserRepository(s).get_by_telegram_id(111)
        assert owner is not None
        for payment in await load_payments(engine):
            await PaymentService(s, KYIV, 10).mark_paid(payment.id, owner, MOMENT)
        await s.commit()

    clock.now = MOMENT + timedelta(days=3)
    assert (await job.run()).digests_sent == 0
    assert api.sent_to(111) == []


# --- ваги ---------------------------------------------------------------------------


async def test_member_and_owner_weights(session: AsyncSession, make_user: MakeUser) -> None:
    service = PoolService(session)
    owner = await make_user("Власник")
    pool = await service.create_pool(owner, NewPoolData("Інтернет", 40_000, 5, True, "4441"))
    for name in ("Родина", "Соло"):
        await service.join(pool.invite_token, await make_user(name))
    family, solo = await service.list_active_members(pool)

    update = await service.set_member_weight(pool.id, owner, family.id, 2)

    assert (family.share_kop, solo.share_kop, pool.owner_share_kop) == (20_000, 10_000, 10_000)
    assert {c.member.id for c in update.changes} == {family.id, solo.id}

    await service.set_owner_weight(pool.id, owner, 3)
    assert (family.share_kop, solo.share_kop, pool.owner_share_kop) == (13_333, 6_666, 20_001)

    for bad in (0, 11):
        with pytest.raises(DomainError) as exc:
            await service.set_member_weight(pool.id, owner, family.id, bad)
        assert exc.value.code is ErrorCode.INVALID_WEIGHT
    with pytest.raises(DomainError) as exc:
        await service.set_member_weight(pool.id, family.user, solo.id, 2)
    assert exc.value.code is ErrorCode.NOT_POOL_OWNER


async def test_weight_via_menu_notifies_members(harness: Harness) -> None:
    setup = await setup_pool(
        harness.engine, owner_tg=OWNER["id"], member_tgs=(GUEST["id"], SECOND["id"])
    )
    async with create_session_factory(harness.engine)() as s:
        guest_member = (
            (
                await s.execute(
                    select(Member).where(Member.pool_id == setup.pool_id).order_by(Member.id)
                )
            )
            .scalars()
            .first()
        )
    assert guest_member is not None

    await harness.click(
        OWNER,
        MemberCB(
            action=MemberAction.SET_WEIGHT, pool_id=setup.pool_id, member_id=guest_member.id
        ).pack(),
    )
    await harness.send(OWNER, "двоє")
    assert "від 1 до 10" in harness.api.texts_to(OWNER["id"])[-1]
    await harness.send(OWNER, "2")

    # 300 грн: Оля ×2, Макс ×1, власник ×1 → 150 / 75 / 75
    assert "тепер <b>150 грн</b>" in harness.api.texts_to(GUEST["id"])[-1]
    assert "тепер <b>75 грн</b>" in harness.api.texts_to(SECOND["id"])[-1]
    assert "×2" in harness.api.texts_to(OWNER["id"])[-1]


# --- співвласник --------------------------------------------------------------------


async def _co_owner_setup(h: Harness) -> tuple[int, list[int]]:
    """Збір з днем списання 1, GUEST — співвласник, SECOND — звичайний учасник."""
    now = utcnow()
    period = latest_due_period(now, 1, KYIV, 10)
    setup = await setup_pool(
        h.engine,
        owner_tg=OWNER["id"],
        member_tgs=(GUEST["id"], SECOND["id"]),
        billing_day=1,
        active_since=billing_moment(period, 1, KYIV, 10),
    )
    async with create_session_factory(h.engine)() as s:
        members = (
            (
                await s.execute(
                    select(Member).where(Member.pool_id == setup.pool_id).order_by(Member.id)
                )
            )
            .scalars()
            .all()
        )
    await h.click(
        OWNER,
        MemberCB(
            action=MemberAction.TOGGLE_ADMIN, pool_id=setup.pool_id, member_id=members[0].id
        ).pack(),
    )
    await make_job(h.bot, h.engine, Clock(now)).run()
    return setup.pool_id, [p.id for p in await load_payments(h.engine)]


async def test_co_owner_is_notified_and_confirms_others(harness: Harness) -> None:
    _pool_id, (_guest_payment, second_payment) = await _co_owner_setup(harness)
    assert "співвласником" in harness.api.texts_to(GUEST["id"])[0]
    harness.api.clear()

    await harness.click(SECOND, pay_cb(PaymentAction.CLAIM, second_payment))
    # Запит на підтвердження отримали і власник, і співвласник
    assert "каже, що скинув" in harness.api.texts_to(OWNER["id"])[-1]
    assert "каже, що скинув" in harness.api.texts_to(GUEST["id"])[-1]

    await harness.click(GUEST, pay_cb(PaymentAction.CONFIRM, second_payment))
    statuses = {p.id: p.status for p in await load_payments(harness.engine)}
    assert statuses[second_payment] is PaymentStatus.PAID


async def test_co_owner_cannot_confirm_own_payment_or_manage_pool(harness: Harness) -> None:
    pool_id, (guest_payment, _) = await _co_owner_setup(harness)

    await harness.click(GUEST, pay_cb(PaymentAction.CLAIM, guest_payment))
    await harness.click(GUEST, pay_cb(PaymentAction.CONFIRM, guest_payment))
    await harness.click(GUEST, pay_cb(PaymentAction.MARK_PAID, guest_payment))
    statuses = {p.id: p.status for p in await load_payments(harness.engine)}
    assert statuses[guest_payment] is PaymentStatus.CLAIMED

    await harness.click(GUEST, PoolCB(action=PoolAction.EDIT_AMOUNT, pool_id=pool_id).pack())
    await harness.send(GUEST, "1")
    async with create_session_factory(harness.engine)() as s:
        pool = await s.get(Pool, pool_id)
        assert pool is not None and pool.total_amount_kop == 30_000


async def test_co_owner_sees_status_and_unpaid_list(harness: Harness) -> None:
    pool_id, (_guest_payment, second_payment) = await _co_owner_setup(harness)

    await harness.send(GUEST, "/status")
    assert "YouTube Family" in harness.api.texts_to(GUEST["id"])[-1]

    await harness.click(GUEST, PoolCB(action=PoolAction.UNPAID, pool_id=pool_id).pack())
    unpaid = [b for b in harness.api.last_markup_buttons() if b.startswith("pay:")]
    # Лише чужий платіж: свій співвласник підтверджувати не може
    assert unpaid == [pay_cb(PaymentAction.MARK_PAID, second_payment)]


async def test_leaving_resets_co_owner(harness: Harness) -> None:
    pool_id, _ = await _co_owner_setup(harness)
    await harness.click(GUEST, PoolCB(action=PoolAction.LEAVE_CONFIRM, pool_id=pool_id).pack())

    async with create_session_factory(harness.engine)() as s:
        first = (
            (await s.execute(select(Member).where(Member.pool_id == pool_id).order_by(Member.id)))
            .scalars()
            .first()
        )
    assert first is not None and (first.is_active, first.is_admin) == (False, False)
