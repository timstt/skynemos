import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import texts
from bot.config import Settings, get_settings
from bot.db.session import create_engine, create_session_factory
from bot.handlers import get_root_router
from bot.handlers.errors import on_error
from bot.integrations import create_storage, setup_sentry
from bot.middlewares import DbSessionMiddleware, UserMiddleware
from bot.scheduler import BillingJob, create_scheduler

logger = logging.getLogger(__name__)

DEFAULT_TZ = ZoneInfo("Europe/Kyiv")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # Сторонні бібліотеки балакучі на INFO: лишаємо їм лише попередження
    for noisy in ("aiogram.event", "apscheduler", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, logging.getLogger().level))


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tz: ZoneInfo = DEFAULT_TZ,
    billing_hour: int = 10,
    storage: BaseStorage | None = None,
) -> Dispatcher:
    # Без Redis стан діалогу /new губиться при перезапуску (див. DECISIONS.md).
    # tz і billing_hour потрапляють у хендлери як однойменні аргументи.
    dp = Dispatcher(storage=storage or MemoryStorage(), tz=tz, billing_hour=billing_hour)
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserMiddleware())
    dp.errors.register(on_error)
    dp.include_router(get_root_router())
    return dp


async def main(settings: Settings) -> None:
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        # Без прев'ю посилань: інакше під кожним повідомленням з t.me/username картка профілю
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    dp = create_dispatcher(
        session_factory,
        tz=settings.tz,
        billing_hour=settings.billing_hour,
        storage=create_storage(settings.redis_url),
    )

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
        await dp.storage.close()
        await bot.session.close()
        await engine.dispose()


def run() -> None:
    try:
        settings = get_settings()
    except ValidationError as exc:
        setup_logging("INFO")
        logger.critical("Помилка конфігурації, перевір .env:\n%s", exc)
        raise SystemExit(1) from None
    setup_logging(settings.log_level)
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else None
    setup_sentry(dsn, settings.environment)
    try:
        asyncio.run(main(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинено")


if __name__ == "__main__":
    run()
