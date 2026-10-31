from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def upsert(self, telegram_id: int, username: str | None, first_name: str) -> User:
        """Створює користувача або оновлює його ім'я. Будь-яка взаємодія = бот доступний."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            self.session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            user.is_reachable = True
        await self.session.flush()
        return user

    async def set_reachable(self, user_id: int, reachable: bool) -> None:
        user = await self.get(user_id)
        if user is not None:
            user.is_reachable = reachable
            await self.session.flush()
