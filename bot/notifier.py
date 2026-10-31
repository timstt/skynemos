"""Надсилання повідомлень іншим користувачам (не у відповідь на їхній апдейт)."""

import asyncio
import logging
from enum import StrEnum

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.db.repositories import UserRepository

logger = logging.getLogger(__name__)


class Delivery(StrEnum):
    SENT = "sent"
    BLOCKED = "blocked"  # користувач заблокував бота або видалив акаунт
    FAILED = "failed"  # тимчасова чи інша помилка: можна спробувати пізніше


async def notify(
    bot: Bot,
    session: AsyncSession,
    user: User,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Delivery:
    """Надсилає повідомлення й повертає результат доставки.

    Якщо користувач заблокував бота, позначає його як недоступного. При флуд-контролі
    Telegram чекає вказаний час і пробує ще раз.
    """
    for attempt in range(2):
        try:
            await bot.send_message(user.telegram_id, text, reply_markup=reply_markup)
            return Delivery.SENT
        except TelegramRetryAfter as exc:
            if attempt:
                logger.warning("Flood control again for user %s, giving up", user.id)
                return Delivery.FAILED
            logger.info("Flood control, sleeping %s s", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except TelegramForbiddenError:
            logger.info("User %s blocked the bot, marking unreachable", user.id)
            await UserRepository(session).set_reachable(user.id, False)
            return Delivery.BLOCKED
        except TelegramAPIError as exc:
            logger.warning("Failed to message user %s: %s", user.id, exc)
            return Delivery.FAILED
    return Delivery.FAILED  # pragma: no cover
