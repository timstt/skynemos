from functools import cache

from aiogram import Router

from bot.handlers import create, manage, start


@cache
def get_root_router() -> Router:
    """Збирає всі роутери. Порядок важливий: команди (/help, /my) мають спрацьовувати
    навіть посеред діалогу /new, тому роутер create із «ловлею» тексту — останній."""
    root = Router(name="root")
    root.include_routers(start.router, manage.router, create.router)
    return root
