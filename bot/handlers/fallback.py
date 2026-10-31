"""Останній роутер: усе, що не впіймали інші хендлери."""

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from bot import texts

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer(texts.UNKNOWN_MESSAGE)


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    """Кнопка зі старої версії бота або з видаленого повідомлення."""
    await callback.answer(texts.STALE_BUTTON, show_alert=True)
