from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Member, Pool


class MemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, member_id: int) -> Member | None:
        return await self.session.get(Member, member_id)

    async def get_with_relations(self, member_id: int) -> Member | None:
        result = await self.session.execute(
            select(Member)
            .where(Member.id == member_id)
            .options(
                selectinload(Member.user),
                selectinload(Member.pool).selectinload(Pool.owner),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_pool_and_user(self, pool_id: int, user_id: int) -> Member | None:
        result = await self.session.execute(
            select(Member).where(Member.pool_id == pool_id, Member.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def add(self, pool_id: int, user_id: int, share_kop: int = 0) -> Member:
        member = Member(pool_id=pool_id, user_id=user_id, share_kop=share_kop)
        self.session.add(member)
        await self.session.flush()
        return member

    async def list_active(self, pool_id: int) -> Sequence[Member]:
        result = await self.session.execute(
            select(Member)
            .where(Member.pool_id == pool_id, Member.is_active.is_(True))
            .options(selectinload(Member.user))
            .order_by(Member.joined_at, Member.id)
        )
        return result.scalars().all()

    async def count_active(self, pool_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Member)
            .where(Member.pool_id == pool_id, Member.is_active.is_(True))
        )
        return result.scalar_one()

    async def list_active_by_user(self, user_id: int) -> Sequence[Member]:
        """Активні участі користувача разом зі зборами: для /my."""
        result = await self.session.execute(
            select(Member)
            .where(Member.user_id == user_id, Member.is_active.is_(True))
            .options(selectinload(Member.pool).selectinload(Pool.owner))
            .order_by(Member.joined_at, Member.id)
        )
        return result.scalars().all()

    async def set_active(self, member: Member, active: bool) -> None:
        member.is_active = active
        await self.session.flush()

    async def set_share(self, member: Member, share_kop: int, *, custom: bool) -> None:
        member.share_kop = share_kop
        member.share_is_custom = custom
        await self.session.flush()
