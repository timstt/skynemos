"""Меню власника та дії учасника через справжній Dispatcher (фейковий Telegram API)."""

from sqlalchemy import func, select

from bot.db.models import Member, PaymentStatus, Pool, utcnow
from bot.db.session import create_session_factory
from bot.keyboards.callbacks import (
    JoinCB,
    MemberAction,
    MemberCB,
    PaymentAction,
    PaymentCB,
    PoolAction,
    PoolCB,
)
from bot.services.billing import billing_moment, latest_due_period
from tests.conftest import KYIV
from tests.fakes import GUEST, OWNER, Harness
from tests.helpers import Clock, load_payments, make_job, setup_pool

SECOND = {"id": 223, "is_bot": False, "first_name": "Макс"}


def pool_cb(action: PoolAction, pool_id: int) -> str:
    return PoolCB(action=action, pool_id=pool_id).pack()


async def _setup(h: Harness, **kwargs: object) -> int:
    """Збір 300 грн, власник у розподілі, учасники GUEST і SECOND — по 100 грн."""
    setup = await setup_pool(
        h.engine, owner_tg=OWNER["id"], member_tgs=(GUEST["id"], SECOND["id"]), **kwargs
    )
    return setup.pool_id


async def _members(h: Harness, pool_id: int) -> list[Member]:
    async with create_session_factory(h.engine)() as s:
        result = await s.execute(
            select(Member).where(Member.pool_id == pool_id).order_by(Member.id)
        )
        return list(result.scalars())


def last_to(h: Harness, user: dict[str, object]) -> str:
    return h.api.texts_to(int(user["id"]))[-1]  # type: ignore[call-overload]


async def test_owner_card_has_management_buttons(harness: Harness) -> None:
    pool_id = await _setup(harness)
    await harness.click(OWNER, pool_cb(PoolAction.VIEW, pool_id))

    actions = {PoolCB.unpack(b).action for b in harness.api.last_markup_buttons()}
    assert {
        PoolAction.INVITE,
        PoolAction.REGEN_INVITE,
        PoolAction.EDIT_AMOUNT,
        PoolAction.EDIT_DAY,
        PoolAction.EDIT_DETAILS,
        PoolAction.MEMBERS,
        PoolAction.UNPAID,
        PoolAction.PAUSE,
        PoolAction.DELETE,
    } <= actions


async def test_edit_amount_notifies_members(harness: Harness) -> None:
    pool_id = await _setup(harness)

    await harness.click(OWNER, pool_cb(PoolAction.EDIT_AMOUNT, pool_id))
    await harness.send(OWNER, "дорого")
    assert "Не розумію суму" in last_to(harness, OWNER)  # стан не скинувся
    await harness.send(OWNER, "600")

    assert "Збережено" in last_to(harness, OWNER) and "600 грн" in last_to(harness, OWNER)
    for user in (GUEST, SECOND):
        assert "тепер <b>200 грн</b> (було 100 грн)" in last_to(harness, user)
    # Після збереження звичайний текст уже не сприймається як сума
    await harness.send(OWNER, "900")
    assert [m.share_kop for m in await _members(harness, pool_id)] == [20_000, 20_000]


async def test_edit_day_and_details_notify_members(harness: Harness) -> None:
    pool_id = await _setup(harness)

    await harness.click(OWNER, pool_cb(PoolAction.EDIT_DAY, pool_id))
    await harness.send(OWNER, "31")
    assert "31 числа" in last_to(harness, GUEST)

    await harness.click(OWNER, pool_cb(PoolAction.EDIT_DETAILS, pool_id))
    await harness.send(OWNER, "https://send.monobank.ua/jar/new")
    assert "jar/new" in last_to(harness, SECOND)


async def test_back_button_cancels_edit(harness: Harness) -> None:
    pool_id = await _setup(harness)
    await harness.click(OWNER, pool_cb(PoolAction.EDIT_AMOUNT, pool_id))
    await harness.click(OWNER, pool_cb(PoolAction.VIEW, pool_id))  # «Назад»

    harness.api.clear()
    await harness.send(OWNER, "1000")
    assert harness.api.texts_to(GUEST["id"]) == []  # сума не змінилася, ніхто не сповіщений


async def test_set_custom_share_and_back_to_auto(harness: Harness) -> None:
    pool_id = await _setup(harness)
    guest_member, _ = await _members(harness, pool_id)

    def member_cb(action: MemberAction) -> str:
        return MemberCB(action=action, pool_id=pool_id, member_id=guest_member.id).pack()

    await harness.click(OWNER, pool_cb(PoolAction.MEMBERS, pool_id))
    await harness.click(OWNER, member_cb(MemberAction.VIEW))
    await harness.click(OWNER, member_cb(MemberAction.SET_SHARE))
    await harness.send(OWNER, "301")
    assert "не можуть перевищувати" in last_to(harness, OWNER)
    await harness.send(OWNER, "50")

    assert "тепер <b>50 грн</b>" in last_to(harness, GUEST)
    assert "тепер <b>125 грн</b>" in last_to(harness, SECOND)

    await harness.click(OWNER, member_cb(MemberAction.SHARE_AUTO))
    assert "тепер <b>100 грн</b>" in last_to(harness, GUEST)
    assert [m.share_kop for m in await _members(harness, pool_id)] == [10_000, 10_000]


async def test_remove_member_with_confirmation(harness: Harness) -> None:
    pool_id = await _setup(harness)
    guest_member, _ = await _members(harness, pool_id)
    remove = MemberCB(action=MemberAction.REMOVE, pool_id=pool_id, member_id=guest_member.id)

    await harness.click(OWNER, remove.pack())
    assert "Видалити" in last_to(harness, OWNER)
    assert [m.is_active for m in await _members(harness, pool_id)] == [True, True]

    confirm = remove.model_copy(update={"action": MemberAction.REMOVE_CONFIRM})
    await harness.click(OWNER, confirm.pack())

    assert "видалив тебе" in last_to(harness, GUEST)
    assert "тепер <b>150 грн</b>" in last_to(harness, SECOND)
    assert [m.is_active for m in await _members(harness, pool_id)] == [False, True]


async def test_pause_and_resume(harness: Harness) -> None:
    pool_id = await _setup(harness)

    await harness.click(OWNER, pool_cb(PoolAction.PAUSE, pool_id))
    assert "на паузу" in last_to(harness, GUEST)
    assert pool_cb(PoolAction.RESUME, pool_id) in harness.api.last_markup_buttons()

    await harness.click(OWNER, pool_cb(PoolAction.RESUME, pool_id))
    assert "знову активний" in last_to(harness, SECOND)
    assert pool_cb(PoolAction.PAUSE, pool_id) in harness.api.last_markup_buttons()


async def test_delete_pool_with_confirmation(harness: Harness) -> None:
    pool_id = await _setup(harness)

    await harness.click(OWNER, pool_cb(PoolAction.DELETE, pool_id))
    assert "Точно видалити" in last_to(harness, OWNER)
    await harness.click(OWNER, pool_cb(PoolAction.DELETE_CONFIRM, pool_id))

    assert "видалив збір" in last_to(harness, GUEST)
    assert "видалив збір" in last_to(harness, SECOND)
    async with create_session_factory(harness.engine)() as s:
        assert (await s.execute(select(func.count()).select_from(Pool))).scalar_one() == 0


async def test_regenerate_invite_invalidates_old_button(harness: Harness) -> None:
    pool_id = await _setup(harness)
    async with create_session_factory(harness.engine)() as s:
        pool = await s.get(Pool, pool_id)
        assert pool is not None
        old_token = pool.invite_token

    await harness.click(OWNER, pool_cb(PoolAction.REGEN_INVITE, pool_id))
    assert "Старе посилання більше не працює" in last_to(harness, OWNER)
    assert old_token not in last_to(harness, OWNER)

    newcomer = {"id": 999, "is_bot": False, "first_name": "Новий"}
    await harness.click(newcomer, JoinCB(token=old_token).pack())
    assert len(await _members(harness, pool_id)) == 2


async def test_mark_paid_manually(harness: Harness) -> None:
    now = utcnow()
    period = latest_due_period(now, 1, KYIV, 10)
    pool_id = await _setup(harness, billing_day=1, active_since=billing_moment(period, 1, KYIV, 10))
    await make_job(harness.bot, harness.engine, Clock(now)).run()
    harness.api.clear()

    await harness.click(OWNER, pool_cb(PoolAction.UNPAID, pool_id))
    unpaid_buttons = [b for b in harness.api.last_markup_buttons() if b.startswith("pay:")]
    assert len(unpaid_buttons) == 2

    await harness.click(OWNER, unpaid_buttons[0])

    assert "позначив(-ла) твою оплату" in last_to(harness, GUEST)
    statuses = [p.status for p in await load_payments(harness.engine)]
    assert statuses == [PaymentStatus.PAID, PaymentStatus.PENDING]
    remaining = [b for b in harness.api.last_markup_buttons() if b.startswith("pay:")]
    assert len(remaining) == 1

    # Учасник не може позначити оплату вручну
    await harness.click(SECOND, remaining[0])
    assert [p.status for p in await load_payments(harness.engine)][1] is PaymentStatus.PENDING


async def test_member_history_and_leave(harness: Harness) -> None:
    now = utcnow()
    period = latest_due_period(now, 1, KYIV, 10)
    pool_id = await _setup(harness, billing_day=1, active_since=billing_moment(period, 1, KYIV, 10))
    await make_job(harness.bot, harness.engine, Clock(now)).run()

    await harness.click(GUEST, pool_cb(PoolAction.VIEW, pool_id))
    actions = {PoolCB.unpack(b).action for b in harness.api.last_markup_buttons()}
    assert {PoolAction.HISTORY, PoolAction.LEAVE} <= actions

    await harness.click(GUEST, pool_cb(PoolAction.HISTORY, pool_id))
    assert "100 грн · ❌ не оплачено" in last_to(harness, GUEST)

    await harness.click(GUEST, pool_cb(PoolAction.LEAVE, pool_id))
    assert "Вийти зі збору" in last_to(harness, GUEST)
    await harness.click(GUEST, pool_cb(PoolAction.LEAVE_CONFIRM, pool_id))

    assert "вийшов(-ла) зі збору" in last_to(harness, OWNER)
    assert [m.is_active for m in await _members(harness, pool_id)] == [False, True]


async def test_member_cannot_use_owner_actions(harness: Harness) -> None:
    pool_id = await _setup(harness)
    _, second_member = await _members(harness, pool_id)

    await harness.click(GUEST, pool_cb(PoolAction.DELETE_CONFIRM, pool_id))
    await harness.click(GUEST, pool_cb(PoolAction.PAUSE, pool_id))
    await harness.click(
        GUEST,
        MemberCB(
            action=MemberAction.REMOVE_CONFIRM, pool_id=pool_id, member_id=second_member.id
        ).pack(),
    )
    await harness.click(GUEST, pool_cb(PoolAction.EDIT_AMOUNT, pool_id))
    await harness.send(GUEST, "1")

    async with create_session_factory(harness.engine)() as s:
        pool = await s.get(Pool, pool_id)
        assert pool is not None
        assert (pool.is_paused, pool.total_amount_kop) == (False, 30_000)
    assert [m.is_active for m in await _members(harness, pool_id)] == [True, True]
    assert harness.api.texts_to(SECOND["id"]) == []


def test_payment_cb_mark_paid_packs() -> None:
    packed = PaymentCB(action=PaymentAction.MARK_PAID, payment_id=7).pack()
    assert packed == "pay:mark:7"


async def test_rename_pool_notifies_members(harness: Harness) -> None:
    pool_id = await _setup(harness)

    await harness.click(OWNER, pool_cb(PoolAction.EDIT_TITLE, pool_id))
    await harness.send(OWNER, "x" * 65)
    assert "від 1 до 64" in last_to(harness, OWNER)  # стан не скинувся
    await harness.send(OWNER, "  YouTube   Premium ")

    async with create_session_factory(harness.engine)() as s:
        pool = await s.get(Pool, pool_id)
        assert pool is not None and pool.title == "YouTube Premium"
    assert "тепер називається <b>YouTube Premium</b>" in last_to(harness, GUEST)
    assert "Збережено" in last_to(harness, OWNER)
