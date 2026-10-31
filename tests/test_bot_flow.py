"""Наскрізні сценарії: справжній Dispatcher, middleware, FSM і БД, фейковий Telegram API."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.db.models import Member, Pool
from bot.db.session import create_session_factory
from bot.keyboards.callbacks import JoinCB, NewPoolAction, NewPoolCB, PoolAction, PoolCB
from tests.fakes import BOT_USERNAME, GUEST, OWNER, Harness


async def _create_pool(h: Harness) -> Pool:
    await h.send(OWNER, "/new")
    await h.send(OWNER, "YouTube Family")
    await h.send(OWNER, "300")
    await h.send(OWNER, "5")
    await h.click(OWNER, NewPoolCB(action=NewPoolAction.OWNER_YES).pack())
    await h.send(OWNER, "https://send.monobank.ua/jar/abc")
    await h.click(OWNER, NewPoolCB(action=NewPoolAction.CONFIRM).pack())

    async with create_session_factory(h.engine)() as s:
        return (await s.execute(select(Pool))).scalar_one()


async def test_full_create_and_join_flow(harness: Harness, engine: AsyncEngine) -> None:
    pool = await _create_pool(harness)

    owner_texts = harness.api.texts_to(OWNER["id"])
    assert "Крок 1/5" in owner_texts[0]
    assert "Перевір, чи все правильно" in owner_texts[-2]
    link = f"https://t.me/{BOT_USERNAME}?start=join_{pool.invite_token}"
    assert link in owner_texts[-1]
    assert (pool.title, pool.total_amount_kop, pool.billing_day) == ("YouTube Family", 30_000, 5)

    # Гість переходить за посиланням і бачить опис збору
    await harness.send(GUEST, f"/start join_{pool.invite_token}")
    assert "150 грн" in harness.api.texts_to(GUEST["id"])[-1]
    assert harness.api.last_markup_buttons() == [JoinCB(token=pool.invite_token).pack()]

    # Натискає «Приєднатися» двічі: дубліката немає, власник отримав одне сповіщення
    await harness.click(GUEST, JoinCB(token=pool.invite_token).pack())
    await harness.click(GUEST, JoinCB(token=pool.invite_token).pack())
    async with create_session_factory(engine)() as s:
        members = (await s.execute(select(Member))).scalars().all()
    assert [m.share_kop for m in members] == [15_000]
    notifications = [t for t in harness.api.texts_to(OWNER["id"]) if "приєднався" in t]
    assert len(notifications) == 1

    # /my у власника та учасника
    await harness.send(OWNER, "/my")
    assert PoolCB(action=PoolAction.VIEW, pool_id=pool.id).pack() in (
        harness.api.last_markup_buttons()
    )
    await harness.click(OWNER, PoolCB(action=PoolAction.VIEW, pool_id=pool.id).pack())
    card = harness.api.texts_to(OWNER["id"])[-1]
    assert "Оля — 150 грн" in card and "Ти — 150 грн" in card

    await harness.click(GUEST, PoolCB(action=PoolAction.VIEW, pool_id=pool.id).pack())
    assert "Твоя частка: <b>150 грн</b>" in harness.api.texts_to(GUEST["id"])[-1]


async def test_owner_cannot_join_via_link(harness: Harness, engine: AsyncEngine) -> None:
    pool = await _create_pool(harness)

    await harness.send(OWNER, f"/start join_{pool.invite_token}")

    assert "твій власний збір" in harness.api.texts_to(OWNER["id"])[-1]


async def test_dialog_validation_and_commands(harness: Harness) -> None:
    await harness.send(OWNER, "/new")
    await harness.send(OWNER, "x" * 65)
    assert "від 1 до 64" in harness.api.texts_to(OWNER["id"])[-1]

    await harness.send(OWNER, "Netflix")
    await harness.send(OWNER, "дорого")
    assert "Не розумію суму" in harness.api.texts_to(OWNER["id"])[-1]

    # /help посеред діалогу працює і не ламає його
    await harness.send(OWNER, "/help")
    assert "Команди" in harness.api.texts_to(OWNER["id"])[-1]
    await harness.send(OWNER, "/unknown")
    assert "/cancel" in harness.api.texts_to(OWNER["id"])[-1]

    await harness.send(OWNER, "/cancel")
    assert harness.api.texts_to(OWNER["id"])[-1] == "Скасовано 👌"


async def test_stale_create_button(harness: Harness) -> None:
    await harness.click(OWNER, NewPoolCB(action=NewPoolAction.CONFIRM).pack())
    # Відповідь у спливаючому вікні, а не повідомленням
    assert harness.api.texts_to(OWNER["id"]) == []
