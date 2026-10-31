from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.filters import CommandObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.handlers.start import cmd_help, cmd_start, start_join
from bot.services.pools import NewPoolData, PoolService
from tests.conftest import MakeUser


def make_message(first_name: str = "Андрій") -> AsyncMock:
    message = AsyncMock()
    message.from_user = SimpleNamespace(first_name=first_name)
    return message


async def test_start_greets_user_and_escapes_name() -> None:
    message = make_message("<Оля>")
    await cmd_start(message)

    text = message.answer.await_args.args[0]
    assert "&lt;Оля&gt;" in text
    assert "/help" in text


async def test_help() -> None:
    message = make_message()
    await cmd_help(message)

    message.answer.assert_awaited_once_with(texts.HELP)


async def test_start_join_shows_preview(session: AsyncSession, make_user: MakeUser) -> None:
    owner = await make_user("Андрій")
    pool = await PoolService(session).create_pool(
        owner, NewPoolData("Netflix <4K>", 30_000, 31, True, "4441")
    )
    guest = await make_user("Оля")
    message, state = make_message(), AsyncMock()

    await start_join(
        message,
        CommandObject(command="start", args=f"join_{pool.invite_token}"),
        session,
        guest,
        state,
    )

    text = message.answer.await_args.args[0]
    assert "Netflix &lt;4K&gt;" in text
    assert "150 грн" in text  # 300 грн на двох: власник + Оля
    assert "останній день" in text  # день 31
    state.clear.assert_awaited_once()


async def test_start_join_unknown_token(session: AsyncSession, make_user: MakeUser) -> None:
    message = make_message()
    await start_join(
        message,
        CommandObject(command="start", args="join_missing"),
        session,
        await make_user(),
        AsyncMock(),
    )

    assert "не знайдено" in message.answer.await_args.args[0]
