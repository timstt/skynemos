"""Фейковий Telegram API і обв'язка для наскрізних тестів бота."""

import itertools
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import EditMessageText, GetMe, SendMessage, TelegramMethod
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncEngine

BOT_USERNAME = "skynemos_test_bot"
OWNER = {"id": 111, "is_bot": False, "first_name": "Андрій"}
GUEST = {"id": 222, "is_bot": False, "first_name": "Оля"}


class FakeSession(BaseSession):
    """Записує запити до Bot API і повертає правдоподібні відповіді.

    `blocked` — chat_id користувачів, що заблокували бота (403);
    `failing` — chat_id, для яких мережа «падає» (тимчасова помилка).
    """

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.blocked: set[int] = set()
        self.failing: set[int] = set()
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
        if isinstance(method, GetMe):
            return method.__returning__.model_validate(
                {"id": 42, "is_bot": True, "first_name": "Bot", "username": BOT_USERNAME}
            )
        if isinstance(method, SendMessage):
            chat_id = int(method.chat_id)
            if chat_id in self.blocked:
                raise TelegramForbiddenError(method, "Forbidden: bot was blocked by the user")
            if chat_id in self.failing:
                raise TelegramNetworkError(method, "Network is unreachable")
            self.requests.append(method)
            return method.__returning__.model_validate(
                message(chat_id, method.text, next(self._ids))
            )
        self.requests.append(method)
        return True

    def texts_to(self, chat_id: int) -> list[str]:
        return [
            m.text
            for m in self.requests
            if isinstance(m, SendMessage | EditMessageText) and m.chat_id == chat_id
        ]

    def sent_to(self, chat_id: int) -> list[SendMessage]:
        return [m for m in self.requests if isinstance(m, SendMessage) and m.chat_id == chat_id]

    def last_markup_buttons(self) -> list[str]:
        for m in reversed(self.requests):
            markup = getattr(m, "reply_markup", None)
            if markup is not None:
                return [b.callback_data for row in markup.inline_keyboard for b in row]
        return []

    def clear(self) -> None:
        self.requests.clear()


def buttons(method: SendMessage) -> list[str]:
    markup = method.reply_markup
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]  # type: ignore[union-attr]


def message(chat_id: int, text: str, message_id: int = 1) -> dict[str, Any]:
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
        msg = message(user["id"], text) | {"from": user}
        await self._feed({"message": msg})

    async def click(self, user: dict[str, Any], data: str) -> None:
        callback = {
            "id": str(next(self._update_ids)),
            "from": user,
            "chat_instance": "test",
            "data": data,
            "message": message(user["id"], "старе повідомлення") | {"from": {**OWNER, "id": 42}},
        }
        await self._feed({"callback_query": callback})

    async def _feed(self, payload: dict[str, Any]) -> None:
        update = Update.model_validate(
            {"update_id": next(self._update_ids), **payload}, context={"bot": self.bot}
        )
        await self.dp.feed_update(self.bot, update)
