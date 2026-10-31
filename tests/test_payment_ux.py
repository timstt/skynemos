"""Етап покращень A: посилання для оплати, «усі скинули», накопичений борг."""

from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.db.models import utcnow
from bot.keyboards.callbacks import PaymentAction, PaymentCB, PoolAction, PoolCB
from bot.services.billing import billing_moment, latest_due_period
from tests.conftest import KYIV
from tests.fakes import GUEST, OWNER, FakeSession, Harness
from tests.helpers import Clock, load_payments, make_job, setup_pool, update_pool

MOMENT = datetime(2026, 11, 5, 10, tzinfo=KYIV)
SECOND = {"id": 223, "is_bot": False, "first_name": "Макс"}


def cb(action: PaymentAction, payment_id: int) -> str:
    return PaymentCB(action=action, payment_id=payment_id).pack()


async def test_request_has_pay_link_button(engine: AsyncEngine, bot: Bot, api: FakeSession) -> None:
    setup = await setup_pool(
        engine, member_tgs=(201,), active_since=datetime(2026, 10, 20, tzinfo=KYIV)
    )
    await update_pool(
        engine, setup.pool_id, payment_details="Банка: https://send.monobank.ua/jar/AbC123"
    )

    await make_job(bot, engine, Clock(MOMENT)).run()

    [request] = api.sent_to(201)
    rows = request.reply_markup.inline_keyboard  # type: ignore[union-attr]
    assert rows[0][0].url == "https://send.monobank.ua/jar/AbC123"
    assert rows[0][0].text == "💳 Відкрити банку"
    assert rows[1][0].callback_data.startswith("pay:claim:")  # type: ignore[union-attr]


async def test_card_number_is_copyable_in_request(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    setup = await setup_pool(
        engine, member_tgs=(201,), active_since=datetime(2026, 10, 20, tzinfo=KYIV)
    )
    await update_pool(engine, setup.pool_id, payment_details="4441 1111 2222 3333")

    await make_job(bot, engine, Clock(MOMENT)).run()

    [request] = api.sent_to(201)
    assert "<code>4441 1111 2222 3333</code>" in request.text
    # Без посилання в реквізитах: лише «Я скинув» і «Нагадай завтра»
    assert len(request.reply_markup.inline_keyboard) == 2  # type: ignore[union-attr]


async def test_debt_block_lists_only_earlier_periods(
    engine: AsyncEngine, bot: Bot, api: FakeSession
) -> None:
    # Простій: доганяємо вересень, жовтень, листопад
    await setup_pool(engine, member_tgs=(201,), active_since=datetime(2026, 8, 1, tzinfo=KYIV))

    await make_job(bot, engine, Clock(MOMENT + timedelta(days=1))).run()

    september, october, november = (m.text for m in api.sent_to(201))
    assert "Ще не оплачено раніше" not in september
    assert "• вересень 2026 — 150 грн" in october and "жовтень 2026 —" not in october.split("⚠️")[1]
    assert "Разом з цим платежем: <b>450 грн</b>" in november


async def _billed(h: Harness) -> tuple[int, list[int]]:
    """Повертає (pool_id, [id платежів GUEST і SECOND])."""
    now = utcnow()
    period = latest_due_period(now, 1, KYIV, 10)
    setup = await setup_pool(
        h.engine,
        owner_tg=OWNER["id"],
        member_tgs=(GUEST["id"], SECOND["id"]),
        billing_day=1,
        active_since=billing_moment(period, 1, KYIV, 10),
    )
    await make_job(h.bot, h.engine, Clock(now)).run()
    h.api.clear()
    return setup.pool_id, [p.id for p in await load_payments(h.engine)]


async def test_all_paid_announced_once_after_last_payment(harness: Harness) -> None:
    _, (first, second) = await _billed(harness)

    await harness.click(GUEST, cb(PaymentAction.CLAIM, first))
    await harness.click(OWNER, cb(PaymentAction.CONFIRM, first))
    assert not any("Усі скинули" in t for t in harness.api.texts_to(OWNER["id"]))

    await harness.click(OWNER, cb(PaymentAction.MARK_PAID, second))
    assert sum("Усі скинули" in t for t in harness.api.texts_to(OWNER["id"])) == 1

    # Повторне натискання не дублює привітання
    await harness.click(OWNER, cb(PaymentAction.CONFIRM, first))
    assert sum("Усі скинули" in t for t in harness.api.texts_to(OWNER["id"])) == 1


async def test_member_card_shows_debt(harness: Harness) -> None:
    pool_id, (first, _) = await _billed(harness)

    await harness.click(GUEST, PoolCB(action=PoolAction.VIEW, pool_id=pool_id).pack())
    assert "⚠️ Не оплачено: <b>100 грн</b>" in harness.api.texts_to(GUEST["id"])[-1]

    await harness.click(OWNER, cb(PaymentAction.MARK_PAID, first))
    await harness.click(GUEST, PoolCB(action=PoolAction.VIEW, pool_id=pool_id).pack())
    assert "✅ Боргів немає" in harness.api.texts_to(GUEST["id"])[-1]
