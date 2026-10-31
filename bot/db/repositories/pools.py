from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Member, Pool


class PoolRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        owner_id: int,
        title: str,
        total_amount_kop: int,
        billing_day: int,
        include_owner: bool,
        payment_details: str,
        invite_token: str,
    ) -> Pool:
        pool = Pool(
            owner_id=owner_id,
            title=title,
            total_amount_kop=total_amount_kop,
            billing_day=billing_day,
            include_owner=include_owner,
            # Учасників ще немає, тож усю суму поки що покриває власник
            owner_share_kop=total_amount_kop,
            payment_details=payment_details,
            invite_token=invite_token,
        )
        self.session.add(pool)
        await self.session.flush()
        return pool

    async def get(self, pool_id: int) -> Pool | None:
        return await self.session.get(Pool, pool_id)

    async def get_with_members(self, pool_id: int) -> Pool | None:
        """Збір разом з учасниками (усіма, включно з неактивними) та їхніми користувачами."""
        result = await self.session.execute(
            select(Pool)
            .where(Pool.id == pool_id)
            .options(
                selectinload(Pool.owner),
                selectinload(Pool.members).selectinload(Member.user),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_invite_token(self, token: str) -> Pool | None:
        result = await self.session.execute(
            select(Pool).where(Pool.invite_token == token).options(selectinload(Pool.owner))
        )
        return result.scalar_one_or_none()

    async def list_by_owner(self, owner_id: int) -> Sequence[Pool]:
        result = await self.session.execute(
            select(Pool).where(Pool.owner_id == owner_id).order_by(Pool.created_at, Pool.id)
        )
        return result.scalars().all()

    async def list_active(self) -> Sequence[Pool]:
        """Усі збори не на паузі: для планувальника."""
        result = await self.session.execute(
            select(Pool)
            .where(Pool.is_paused.is_(False))
            .options(selectinload(Pool.owner))
            .order_by(Pool.id)
        )
        return result.scalars().all()

    async def update(self, pool: Pool, **fields: Any) -> Pool:
        for name, value in fields.items():
            if not hasattr(Pool, name):
                raise AttributeError(f"Pool has no field {name!r}")
            setattr(pool, name, value)
        await self.session.flush()
        return pool

    async def delete(self, pool: Pool) -> None:
        await self.session.delete(pool)
        await self.session.flush()
