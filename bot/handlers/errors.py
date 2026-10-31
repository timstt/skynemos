"""Глобальний обробник непередбачених помилок: лог + вибачення користувачу."""

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from bot import texts

logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent) -> bool:
    """Транзакцію вже відкотив DbSessionMiddleware; тут лише лог і відповідь користувачу."""
    update = event.update
    user = update.event.from_user if hasattr(update.event, "from_user") else None
    logger.error(
        "Unhandled error in update %s (user %s): %r",
        update.update_id,
        user.id if user else None,
        event.exception,
        exc_info=event.exception,
    )
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(texts.UNEXPECTED_ERROR_ALERT, show_alert=True)
        elif update.message is not None:
            await update.message.answer(texts.UNEXPECTED_ERROR)
    except TelegramAPIError as exc:
        logger.warning("Could not report error to user: %s", exc)
    return True
