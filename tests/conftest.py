from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.pool import StaticPool

from bot.db.models import Base, Pool, User
from bot.db.repositories import PoolRepository, UserRepository
from bot.db.session import create_engine, create_session_factory

MakeUser = Callable[..., Awaitable[User]]
MakePool = Callable[..., Awaitable[Pool]]


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    # StaticPool: одне з'єднання, інакше кожне отримало б свою порожню in-memory БД
    engine = create_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with create_session_factory(engine)() as session:
        yield session


@pytest.fixture
def make_user(session: AsyncSession) -> MakeUser:
    counter = iter(range(1000, 10_000))

    async def _make(first_name: str = "Тест") -> User:
        return await UserRepository(session).upsert(next(counter), None, first_name)

    return _make


@pytest.fixture
def make_pool(session: AsyncSession, make_user: MakeUser) -> MakePool:
    counter = iter(range(10_000))

    async def _make(owner: User | None = None, **overrides: Any) -> Pool:
        owner = owner or await make_user("Власник")
        fields: dict[str, Any] = {
            "title": "YouTube Family",
            "total_amount_kop": 30_000,
            "billing_day": 5,
            "include_owner": True,
            "payment_details": "4441 1111 2222 3333",
            "invite_token": f"token{next(counter)}",
        }
        fields.update(overrides)
        return await PoolRepository(session).create(owner_id=owner.id, **fields)

    return _make
