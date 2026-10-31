import html

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot import texts

router = Router(name="start")

JOIN_PREFIX = "join_"


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    if command.args and command.args.startswith(JOIN_PREFIX):
        # Флоу приєднання реалізуємо на етапі 3
        await message.answer(texts.JOIN_NOT_READY)
        return

    name = message.from_user.first_name if message.from_user else "друже"
    await message.answer(texts.START.format(name=html.escape(name)))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)
