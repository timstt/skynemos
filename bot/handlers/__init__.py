from aiogram import Router

from bot.handlers import start


def get_root_router() -> Router:
    """Збирає всі роутери застосунку в один."""
    root = Router(name="root")
    root.include_router(start.router)
    return root
