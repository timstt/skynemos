import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import DatabaseSettings
from bot.db.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    # URL, переданий програмно (наприклад, у тестах), має пріоритет над .env
    return config.attributes.get("database_url") or DatabaseSettings().database_url


def _configure(**kwargs: object) -> None:
    url = str(kwargs.pop("url", "")) or None
    is_sqlite = (url or get_url()).startswith("sqlite")
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite не вміє ALTER COLUMN: batch-режим перебудовує таблицю
        render_as_batch=is_sqlite,
        url=url,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    """Генерує SQL без підключення до БД: `alembic upgrade head --sql`."""
    _configure(url=get_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        # Підключення передали ззовні (тести): використовуємо його
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
