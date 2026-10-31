"""Кнопки «Я скинув» / «Підтвердити» / «Не бачу оплати» та /status через справжній Dispatcher."""

from datetime import timedelta

from bot.db.models import PaymentStatus, utcnow
from bot.keyboards.callbacks import PaymentAction, PaymentCB
from bot.services.billing import billing_moment, latest_due_period
from tests.conftest import KYIV
from tests.fakes import GUEST, OWNER, Harness, buttons
from tests.helpers import Clock, load_payments, make_job, setup_pool, update_pool

STRANGER = {"id": 333, "is_bot": False, "first_name": "Чужий"}


def cb(action: PaymentAction, payment_id: int) -> str:
    return PaymentCB(action=action, payment_id=payment_id).pack()


async def _billed(h: Harness, member_tgs: tuple[int, ...] = (GUEST["id"],)) -> list[int]:
    """Збір із днем списання 1, платежі за поточний цикл уже надіслано. Повертає id платежів."""
    now = utcnow()
    period = latest_due_period(now, 1, KYIV, 10)
    await setup_pool(
        h.engine,
        owner_tg=OWNER["id"],
        member_tgs=member_tgs,
        total_kop=40_000 if len(member_tgs) == 3 else 30_000,
        billing_day=1,
        active_since=billing_moment(period, 1, KYIV, 10),  # рівно один цикл
    )
    await make_job(h.bot, h.engine, Clock(now)).run()
    h.api.clear()
    return [p.id for p in await load_payments(h.engine)]


async def test_claim_then_confirm(harness: Harness) -> None:
    [payment_id] = await _billed(harness)

    await harness.click(GUEST, cb(PaymentAction.CLAIM, payment_id))

    assert "Чекаємо, поки власник підтвердить" in harness.api.texts_to(GUEST["id"])[-1]
    [owner_msg] = harness.api.sent_to(OWNER["id"])
    # Ім'я оновилося з Telegram при натисканні кнопки (middleware)
    assert "Оля" in owner_msg.text and "150 грн" in owner_msg.text
    assert buttons(owner_msg) == [
        cb(PaymentAction.CONFIRM, payment_id),
        cb(PaymentAction.REJECT, payment_id),
    ]

    # Подвійний клік: власник не отримує другого запиту
    await harness.click(GUEST, cb(PaymentAction.CLAIM, payment_id))
    assert len(harness.api.sent_to(OWNER["id"])) == 1

    await harness.click(OWNER, cb(PaymentAction.CONFIRM, payment_id))
    owner_texts = harness.api.texts_to(OWNER["id"])
    assert "Підтверджено" in owner_texts[-2]
    # Це був єдиний платіж періоду — власник отримує «усі скинули»
    assert "Усі скинули" in owner_texts[-1]
    assert "підтвердив(-ла) твою оплату" in harness.api.sent_to(GUEST["id"])[-1].text
    [payment] = await load_payments(harness.engine)
    assert payment.status is PaymentStatus.PAID

    # Повторне «Підтвердити» нічого не надсилає учаснику
    sent_before = len(harness.api.sent_to(GUEST["id"]))
    await harness.click(OWNER, cb(PaymentAction.CONFIRM, payment_id))
    assert len(harness.api.sent_to(GUEST["id"])) == sent_before


async def test_reject_returns_to_pending_and_member_can_claim_again(harness: Harness) -> None:
    [payment_id] = await _billed(harness)
    await harness.click(GUEST, cb(PaymentAction.CLAIM, payment_id))

    await harness.click(OWNER, cb(PaymentAction.REJECT, payment_id))

    rejected = harness.api.sent_to(GUEST["id"])[-1]
    assert "поки не бачить твоєї оплати" in rejected.text
    assert buttons(rejected) == [
        cb(PaymentAction.CLAIM, payment_id),
        cb(PaymentAction.SNOOZE, payment_id),
    ]
    [payment] = await load_payments(harness.engine)
    assert payment.status is PaymentStatus.PENDING

    # Стара кнопка «Підтвердити» після відхилення не проводить оплату
    await harness.click(OWNER, cb(PaymentAction.CONFIRM, payment_id))
    [payment] = await load_payments(harness.engine)
    assert payment.status is PaymentStatus.PENDING

    await harness.click(GUEST, cb(PaymentAction.CLAIM, payment_id))
    await harness.click(OWNER, cb(PaymentAction.CONFIRM, payment_id))
    [payment] = await load_payments(harness.engine)
    assert payment.status is PaymentStatus.PAID


async def test_strangers_cannot_press_payment_buttons(harness: Harness) -> None:
    [payment_id] = await _billed(harness)

    await harness.click(STRANGER, cb(PaymentAction.CLAIM, payment_id))
    await harness.click(STRANGER, cb(PaymentAction.CONFIRM, payment_id))
    await harness.click(GUEST, cb(PaymentAction.CONFIRM, payment_id))  # учасник не власник

    [payment] = await load_payments(harness.engine)
    assert payment.status is PaymentStatus.PENDING
    assert harness.api.sent_to(OWNER["id"]) == []


async def test_status_shows_each_member(harness: Harness) -> None:
    ids = await _billed(harness, member_tgs=(GUEST["id"], 223, 224))
    second = {"id": 223, "is_bot": False, "first_name": "Учасник2"}
    await harness.click(GUEST, cb(PaymentAction.CLAIM, ids[0]))
    await harness.click(OWNER, cb(PaymentAction.CONFIRM, ids[0]))
    await harness.click(second, cb(PaymentAction.CLAIM, ids[1]))

    await harness.send(OWNER, "/status")

    status = harness.api.texts_to(OWNER["id"])[-1]
    assert '✅ <a href="tg://user?id=222">Оля</a> — 100 грн' in status
    assert "Учасник2</a> — 100 грн (чекає підтвердження)" in status
    assert '❌ <a href="tg://user?id=224">Учасник3</a> — 100 грн' in status
    assert "Зібрано: 100 грн з 300 грн" in status


async def test_status_before_first_billing(harness: Harness) -> None:
    await setup_pool(
        harness.engine,
        owner_tg=OWNER["id"],
        member_tgs=(GUEST["id"],),
        active_since=utcnow() + timedelta(minutes=1),
    )
    await harness.send(OWNER, "/status")
    assert "Перше списання" in harness.api.texts_to(OWNER["id"])[-1]


async def test_status_without_own_pools(harness: Harness) -> None:
    await harness.send(GUEST, "/status")
    assert "немає зборів, де ти власник" in harness.api.texts_to(GUEST["id"])[-1]


async def test_status_of_paused_pool_has_no_billing_date(harness: Harness) -> None:
    setup = await setup_pool(
        harness.engine,
        owner_tg=OWNER["id"],
        member_tgs=(GUEST["id"],),
        active_since=utcnow() + timedelta(minutes=1),
    )
    await update_pool(harness.engine, setup.pool_id, is_paused=True)

    await harness.send(OWNER, "/status")

    status = harness.api.texts_to(OWNER["id"])[-1]
    assert "на паузі" in status
    assert "Перше списання" not in status
    assert "Списань не буде, поки збір на паузі" in status
