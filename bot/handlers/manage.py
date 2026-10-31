"""/my і картки зборів. Меню керування власника з'явиться на етапі 6."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards, texts
from bot.db.models import User
from bot.handlers.common import show
from bot.keyboards.callbacks import PoolAction, PoolCB
from bot.services.errors import DomainError, ErrorCode
from bot.services.pools import PoolService

router = Router(name="manage")


async def _pools_list(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup | None]:
    pools = await PoolService(session).list_user_pools(user)
    if not pools.owned and not pools.memberships:
        return texts.NO_POOLS, None
    return (
        texts.my_pools(pools.owned, pools.memberships),
        keyboards.my_pools_kb(pools.owned, pools.memberships),
    )


@router.message(Command("my"))
async def cmd_my(message: Message, session: AsyncSession, user: User) -> None:
    text, kb = await _pools_list(session, user)
    await message.answer(text, reply_markup=kb)


@router.callback_query(PoolCB.filter(F.action == PoolAction.LIST))
async def show_list(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    text, kb = await _pools_list(session, user)
    await show(callback, text, kb)
    await callback.answer()


@router.callback_query(PoolCB.filter(F.action == PoolAction.VIEW))
async def show_pool(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User
) -> None:
    service = PoolService(session)
    try:
        pool = await service.get_owned_pool(callback_data.pool_id, user)
    except DomainError as exc:
        if exc.code is not ErrorCode.NOT_POOL_OWNER:
            await callback.answer(texts.error_text(exc), show_alert=True)
            return
    else:
        members = await service.list_active_members(pool)
        await show(callback, texts.owner_pool_card(pool, members), keyboards.owner_pool_kb(pool))
        await callback.answer()
        return

    try:
        member = await service.get_membership(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    await show(callback, texts.member_pool_card(member), keyboards.member_pool_kb())
    await callback.answer()


@router.callback_query(PoolCB.filter(F.action == PoolAction.INVITE))
async def show_invite(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    try:
        pool = await PoolService(session).get_owned_pool(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    link = await create_start_link(bot, f"join_{pool.invite_token}")
    await show(callback, texts.invite_link(pool, link), keyboards.back_to_pool_kb(pool.id))
    await callback.answer()
