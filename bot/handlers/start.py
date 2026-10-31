import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards, texts
from bot.db.models import User
from bot.handlers.common import show
from bot.keyboards.callbacks import JoinCB
from bot.notifier import notify
from bot.services.errors import DomainError
from bot.services.pools import JoinStatus, PoolService

router = Router(name="start")

JOIN_PREFIX = "join_"


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(JOIN_PREFIX)))
async def start_join(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()  # перехід за посиланням перериває незавершений /new
    token = (command.args or "").removeprefix(JOIN_PREFIX)
    try:
        preview = await PoolService(session).preview_join(token, user)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        return

    if preview.already_member:
        await message.answer(
            texts.already_member(preview.pool), reply_markup=keyboards.open_pool_kb(preview.pool.id)
        )
        return
    await message.answer(texts.join_preview(preview), reply_markup=keyboards.join_kb(token))


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "друже"
    await message.answer(texts.START.format(name=html.escape(name)))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.callback_query(JoinCB.filter())
async def join_pool(
    callback: CallbackQuery,
    callback_data: JoinCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    try:
        result = await PoolService(session).join(callback_data.token, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return

    if result.status is JoinStatus.ALREADY_MEMBER:
        await show(
            callback, texts.already_member(result.pool), keyboards.open_pool_kb(result.pool.id)
        )
        await callback.answer()
        return

    await show(callback, texts.joined(result), keyboards.open_pool_kb(result.pool.id))
    await callback.answer()
    await notify(bot, session, result.pool.owner, texts.owner_member_joined(result, user))
