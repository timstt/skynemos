import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot import texts
from bot.config import Settings, get_settings
from bot.handlers import get_root_router

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(get_root_router())
    return dp


async def main(settings: Settings) -> None:
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    await bot.set_my_commands(
        [BotCommand(command=cmd, description=desc) for cmd, desc in texts.COMMANDS.items()]
    )
    logger.info("Бот запускається (polling)")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    try:
        asyncio.run(main(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинено")


if __name__ == "__main__":
    run()
