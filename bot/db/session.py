from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, *, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    kwargs.setdefault("pool_pre_ping", True)
    engine = create_async_engine(database_url, echo=echo, **kwargs)
    if engine.dialect.name == "sqlite":
        _enable_sqlite_foreign_keys(engine)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    # SQLite за замовчуванням ігнорує FOREIGN KEY та ON DELETE CASCADE
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
