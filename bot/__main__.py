import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import texts
from bot.config import Settings, get_settings
from bot.db.session import create_engine, create_session_factory
from bot.handlers import get_root_router
from bot.middlewares import DbSessionMiddleware, UserMiddleware
from bot.scheduler import BillingJob, create_scheduler

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Europe/Kyiv")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tz: ZoneInfo = DEFAULT_TZ,
    billing_hour: int = 10,
) -> Dispatcher:
    # MemoryStorage: стан діалогу /new губиться при перезапуску (див. DECISIONS.md).
    # tz і billing_hour потрапляють у хендлери як однойменні аргументи.
    dp = Dispatcher(storage=MemoryStorage(), tz=tz, billing_hour=billing_hour)
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserMiddleware())
    dp.include_router(get_root_router())
    return dp


async def main(settings: Settings) -> None:
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    dp = create_dispatcher(session_factory, tz=settings.tz, billing_hour=settings.billing_hour)

    job = BillingJob(bot, session_factory, settings.tz, settings.billing_hour)
    scheduler = create_scheduler(job, settings.tz)

    await bot.set_my_commands(
        [BotCommand(command=cmd, description=desc) for cmd, desc in texts.COMMANDS.items()]
    )
    scheduler.start()
    # Одразу при старті: доганяємо платежі й нагадування, пропущені під час простою
    catch_up = asyncio.create_task(job.run())
    logger.info("Бот запускається (polling)")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        if not catch_up.done():
            catch_up.cancel()
        await bot.session.close()
        await engine.dispose()


def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    try:
        asyncio.run(main(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинено")


if __name__ == "__main__":
    run()
