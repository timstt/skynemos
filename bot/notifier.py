"""Надсилання повідомлень іншим користувачам (не у відповідь на їхній апдейт)."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.db.repositories import UserRepository

logger = logging.getLogger(__name__)


async def notify(
    bot: Bot,
    session: AsyncSession,
    user: User,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Надсилає повідомлення. Повертає False, якщо користувач недоступний.

    Якщо користувач заблокував бота, позначає його як недоступного.
    """
    try:
        await bot.send_message(user.telegram_id, text, reply_markup=reply_markup)
    except TelegramForbiddenError:
        logger.info("User %s blocked the bot, marking unreachable", user.id)
        await UserRepository(session).set_reachable(user.id, False)
        return False
    except TelegramBadRequest as exc:
        logger.warning("Failed to message user %s: %s", user.id, exc)
        return False
    return True
