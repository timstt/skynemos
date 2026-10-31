"""Бізнес-логіка зборів: створення, приєднання, перерахунок часток. Без aiogram."""

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Member, Pool, User
from bot.db.repositories import MemberRepository, PoolRepository
from bot.services.errors import DomainError, ErrorCode
from bot.services.shares import ShareInput, SharePlan, compute_shares
from bot.services.validation import (
    validate_billing_day,
    validate_payment_details,
    validate_title,
)

MAX_MEMBERS = 10
_TOKEN_BYTES = 12  # → 16 символів base64url, вміщується в deep link (≤ 64)
_TOKEN_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class NewPoolData:
    title: str
    total_amount_kop: int
    billing_day: int
    include_owner: bool
    payment_details: str


class JoinStatus(StrEnum):
    JOINED = "joined"
    REJOINED = "rejoined"
    ALREADY_MEMBER = "already_member"


@dataclass(frozen=True, slots=True)
class JoinPreview:
    pool: Pool
    members_count: int
    estimated_share_kop: int
    already_member: bool


@dataclass(frozen=True, slots=True)
class JoinResult:
    status: JoinStatus
    pool: Pool
    member: Member
    members_count: int


@dataclass(frozen=True, slots=True)
class UserPools:
    owned: Sequence[Pool]
    memberships: Sequence[Member]


class PoolService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pools = PoolRepository(session)
        self.members = MemberRepository(session)

    # --- створення ---------------------------------------------------------

    async def create_pool(self, owner: User, data: NewPoolData) -> Pool:
        if data.total_amount_kop <= 0:
            raise DomainError(ErrorCode.INVALID_AMOUNT)
        return await self.pools.create(
            owner_id=owner.id,
            title=validate_title(data.title),
            total_amount_kop=data.total_amount_kop,
            billing_day=validate_billing_day(data.billing_day),
            include_owner=data.include_owner,
            payment_details=validate_payment_details(data.payment_details),
            invite_token=await self._new_invite_token(),
        )

    async def _new_invite_token(self) -> str:
        for _ in range(_TOKEN_ATTEMPTS):
            token = secrets.token_urlsafe(_TOKEN_BYTES)
            if await self.pools.get_by_invite_token(token) is None:
                return token
        raise RuntimeError("Could not generate a unique invite token")  # pragma: no cover

    # --- приєднання --------------------------------------------------------

    async def get_pool_by_token(self, token: str) -> Pool:
        pool = await self.pools.get_by_invite_token(token)
        if pool is None:
            raise DomainError(ErrorCode.POOL_NOT_FOUND)
        return pool

    async def preview_join(self, token: str, user: User) -> JoinPreview:
        """Що побачить користувач до натискання «Приєднатися»."""
        pool = await self.get_pool_by_token(token)
        if pool.owner_id == user.id:
            raise DomainError(ErrorCode.OWNER_CANNOT_JOIN)

        active = list(await self.members.list_active(pool.id))
        current = next((m for m in active if m.user_id == user.id), None)
        if current is not None:
            return JoinPreview(pool, len(active), current.share_kop, already_member=True)
        if len(active) >= MAX_MEMBERS:
            raise DomainError(ErrorCode.POOL_FULL)

        # Частка, якби користувач уже приєднався (id=0 — тимчасовий)
        plan = compute_shares(
            pool.total_amount_kop,
            pool.include_owner,
            [*self._share_inputs(active), ShareInput(member_id=0)],
        )
        return JoinPreview(pool, len(active), plan.member_shares[0], already_member=False)

    async def join(self, token: str, user: User) -> JoinResult:
        pool = await self.get_pool_by_token(token)
        if pool.owner_id == user.id:
            raise DomainError(ErrorCode.OWNER_CANNOT_JOIN)

        member = await self.members.get_by_pool_and_user(pool.id, user.id)
        if member is not None and member.is_active:
            count = await self.members.count_active(pool.id)
            return JoinResult(JoinStatus.ALREADY_MEMBER, pool, member, count)

        if await self.members.count_active(pool.id) >= MAX_MEMBERS:
            raise DomainError(ErrorCode.POOL_FULL)

        if member is None:
            member = await self.members.add(pool.id, user.id)
            status = JoinStatus.JOINED
        else:
            await self.members.set_share(member, 0, custom=False)
            await self.members.set_active(member, True)
            status = JoinStatus.REJOINED

        await self.recalculate_shares(pool)
        count = await self.members.count_active(pool.id)
        return JoinResult(status, pool, member, count)

    # --- частки ------------------------------------------------------------

    async def recalculate_shares(self, pool: Pool) -> SharePlan:
        """Перераховує частки активних учасників і власника та зберігає їх.

        Уже створені платежі не змінюються: нові частки діють з наступного циклу.
        """
        active = list(await self.members.list_active(pool.id))
        plan = compute_shares(pool.total_amount_kop, pool.include_owner, self._share_inputs(active))
        for member in active:
            custom = member.share_is_custom and not plan.custom_reset
            await self.members.set_share(member, plan.member_shares[member.id], custom=custom)
        await self.pools.update(pool, owner_share_kop=plan.owner_share_kop)
        return plan

    @staticmethod
    def _share_inputs(members: Sequence[Member]) -> list[ShareInput]:
        return [ShareInput(m.id, m.share_kop if m.share_is_custom else None) for m in members]

    # --- перегляд ----------------------------------------------------------

    async def list_user_pools(self, user: User) -> UserPools:
        return UserPools(
            owned=await self.pools.list_by_owner(user.id),
            memberships=await self.members.list_active_by_user(user.id),
        )

    async def get_owned_pool(self, pool_id: int, user: User) -> Pool:
        """Збір з учасниками, якщо `user` його власник."""
        pool = await self.pools.get_with_members(pool_id)
        if pool is None:
            raise DomainError(ErrorCode.POOL_NOT_FOUND)
        if pool.owner_id != user.id:
            raise DomainError(ErrorCode.NOT_POOL_OWNER)
        return pool

    async def get_membership(self, pool_id: int, user: User) -> Member:
        member = await self.members.get_by_pool_and_user(pool_id, user.id)
        if member is None or not member.is_active:
            raise DomainError(ErrorCode.NOT_A_MEMBER)
        loaded = await self.members.get_with_relations(member.id)
        assert loaded is not None
        return loaded

    async def list_active_members(self, pool: Pool) -> Sequence[Member]:
        return await self.members.list_active(pool.id)
