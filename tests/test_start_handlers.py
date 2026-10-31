from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.filters import CommandObject

from bot import texts
from bot.handlers.start import cmd_help, cmd_start


def make_message(first_name: str = "Андрій") -> AsyncMock:
    message = AsyncMock()
    message.from_user = SimpleNamespace(first_name=first_name)
    return message


async def test_start_greets_user_and_escapes_name() -> None:
    message = make_message("<Оля>")
    await cmd_start(message, CommandObject(command="start"))

    text = message.answer.await_args.args[0]
    assert "&lt;Оля&gt;" in text
    assert "/help" in text


async def test_start_with_join_payload() -> None:
    message = make_message()
    await cmd_start(message, CommandObject(command="start", args="join_abc123"))

    message.answer.assert_awaited_once_with(texts.JOIN_NOT_READY)


async def test_help() -> None:
    message = make_message()
    await cmd_help(message)

    message.answer.assert_awaited_once_with(texts.HELP)
