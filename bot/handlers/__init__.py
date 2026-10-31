from functools import cache

from aiogram import F, Router
from aiogram.enums import ChatType

from bot.handlers import create, fallback, manage, payments, start


@cache
def get_root_router() -> Router:
    """Збирає всі роутери. Порядок важливий:
    * команди (/help, /my) мають спрацьовувати навіть посеред діалогу /new,
      тому роутер create із «ловлею» тексту — передостанній;
    * fallback (невідомі повідомлення й застарілі кнопки) — завжди останній.
    """
    root = Router(name="root")
    # Бот працює лише в особистих чатах: у групі він не має відповідати на кожне повідомлення
    root.message.filter(F.chat.type == ChatType.PRIVATE)
    root.include_routers(
        start.router, manage.router, payments.router, create.router, fallback.router
    )
    return root
