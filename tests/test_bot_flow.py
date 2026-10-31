"""Наскрізні сценарії: справжній Dispatcher, middleware, FSM і БД, фейковий Telegram API."""

import itertools
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, GetMe, SendMessage, TelegramMethod
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.__main__ import create_dispatcher
from bot.db.models import Member, Pool
from bot.db.session import create_session_factory
from bot.handlers import get_root_router
from bot.keyboards.callbacks import JoinCB, NewPoolAction, NewPoolCB, PoolAction, PoolCB

BOT_USERNAME = "skynemos_test_bot"
OWNER = {"id": 111, "is_bot": False, "first_name": "Андрій"}
GUEST = {"id": 222, "is_bot": False, "first_name": "Оля"}


class FakeSession(BaseSession):
    """Записує запити до Bot API і повертає правдоподібні відповіді."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self._ids = itertools.count(1000)

    async def close(self) -> None:
        pass

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура з BaseSession
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, GetMe):
            return method.__returning__.model_validate(
                {"id": 42, "is_bot": True, "first_name": "Bot", "username": BOT_USERNAME}
            )
        if isinstance(method, SendMessage):
            return method.__returning__.model_validate(
                _message(int(method.chat_id), method.text, next(self._ids))
            )
        return True

    def texts_to(self, chat_id: int) -> list[str]:
        return [
            m.text
            for m in self.requests
            if isinstance(m, SendMessage | EditMessageText) and m.chat_id == chat_id
        ]

    def last_markup_buttons(self) -> list[str]:
        for m in reversed(self.requests):
            markup = getattr(m, "reply_markup", None)
            if markup is not None:
                return [b.callback_data for row in markup.inline_keyboard for b in row]
        return []


def _message(chat_id: int, text: str, message_id: int = 1) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "date": int(datetime.now(UTC).timestamp()),
        "chat": {"id": chat_id, "type": "private"},
        "text": text,
    }


class Harness:
    def __init__(self, dp: Dispatcher, bot: Bot, api: FakeSession, engine: AsyncEngine) -> None:
        self.dp, self.bot, self.api, self.engine = dp, bot, api, engine
        self._update_ids = itertools.count(1)

    async def send(self, user: dict[str, Any], text: str) -> None:
        msg = _message(user["id"], text) | {"from": user}
        await self._feed({"message": msg})

    async def click(self, user: dict[str, Any], data: str) -> None:
        callback = {
            "id": str(next(self._update_ids)),
            "from": user,
            "chat_instance": "test",
            "data": data,
            "message": _message(user["id"], "старе повідомлення") | {"from": {**OWNER, "id": 42}},
        }
        await self._feed({"callback_query": callback})

    async def _feed(self, payload: dict[str, Any]) -> None:
        update = Update.model_validate(
            {"update_id": next(self._update_ids), **payload}, context={"bot": self.bot}
        )
        await self.dp.feed_update(self.bot, update)


@pytest.fixture
async def harness(engine: AsyncEngine) -> AsyncGenerator[Harness, None]:
    api = FakeSession()
    bot = Bot("42:TEST", session=api)
    dp = create_dispatcher(create_session_factory(engine))
    yield Harness(dp, bot, api, engine)
    # Роутери — модульні синглтони: від'єднуємо, щоб наступний тест підключив їх знову
    get_root_router()._parent_router = None


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
