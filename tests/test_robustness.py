"""Обробка помилок, невідомих повідомлень, застарілих кнопок і груп."""

import logging
from typing import Any

import pytest
from sqlalchemy import func, select

from bot.db.models import Pool
from bot.db.session import create_session_factory
from bot.services.pools import PoolService
from tests.fakes import OWNER, Harness, message


async def test_unexpected_error_apologises_and_logs(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(PoolService, "list_user_pools", boom)

    with caplog.at_level(logging.ERROR, logger="bot.handlers.errors"):
        await harness.send(OWNER, "/my")

    assert "щось пішло не так" in harness.api.texts_to(OWNER["id"])[-1].lower()
    assert "database exploded" in caplog.text


async def test_error_rolls_back_transaction(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bot.db.repositories import PoolRepository

    original_create = PoolRepository.create

    async def create_then_fail(self: PoolRepository, **kwargs: Any) -> Pool:
        await original_create(self, **kwargs)
        raise RuntimeError("fail after insert")

    monkeypatch.setattr(PoolRepository, "create", create_then_fail)
    await harness.send(OWNER, "/new")
    for text in ("Netflix", "300", "5"):
        await harness.send(OWNER, text)
    await harness.click(OWNER, "new:owner_yes")
    await harness.send(OWNER, "4441")
    await harness.click(OWNER, "new:confirm")

    async with create_session_factory(harness.engine)() as s:
        assert (await s.execute(select(func.count()).select_from(Pool))).scalar_one() == 0


async def test_unknown_text_gets_help_hint(harness: Harness) -> None:
    await harness.send(OWNER, "привіт, що ти вмієш?")
    assert "/help" in harness.api.texts_to(OWNER["id"])[-1]


async def test_stale_button_gets_alert_not_crash(harness: Harness) -> None:
    await harness.click(OWNER, "something:from:old:version")
    await harness.click(OWNER, "pool:view:999999")  # видалений збір
    assert harness.api.texts_to(OWNER["id"]) == []  # лише спливаючі вікна


async def test_bot_ignores_group_chats(harness: Harness) -> None:
    group_msg = message(-100500, "/help") | {"from": OWNER}
    group_msg["chat"] = {"id": -100500, "type": "group", "title": "Сусіди"}
    await harness._feed({"message": group_msg})
    assert harness.api.texts_to(-100500) == []
