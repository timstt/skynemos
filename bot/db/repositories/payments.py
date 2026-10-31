from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Member, Payment, PaymentStatus, Pool


class PaymentRepository:
    """Доступ до платежів. Переходи статусів перевіряє сервіс, а не репозиторій."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: int) -> Payment | None:
        return await self.session.get(Payment, payment_id)

    async def get_with_relations(self, payment_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.id == payment_id)
            .options(
                selectinload(Payment.member).selectinload(Member.user),
                selectinload(Payment.member).selectinload(Member.pool).selectinload(Pool.owner),
            )
        )
        return result.scalar_one_or_none()

    async def get_for_member_period(self, member_id: int, period: date) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.member_id == member_id, Payment.period == period)
        )
        return result.scalar_one_or_none()

    async def create_if_absent(
        self, member_id: int, period: date, amount_kop: int
    ) -> tuple[Payment, bool]:
        """Створює платіж за період, якщо його ще немає.

        Повертає (платіж, чи_створено). Унікальний індекс (member_id, period) гарантує,
        що навіть паралельні виклики не створять дублікат.
        """
        existing = await self.get_for_member_period(member_id, period)
        if existing is not None:
            return existing, False

        payment = Payment(member_id=member_id, period=period, amount_kop=amount_kop)
        try:
            async with self.session.begin_nested():
                self.session.add(payment)
        except IntegrityError:
            # Хтось інший встиг створити платіж між SELECT та INSERT
            existing = await self.get_for_member_period(member_id, period)
            if existing is None:
                raise
            return existing, False
        return payment, True

    async def list_for_pool_period(self, pool_id: int, period: date) -> Sequence[Payment]:
        result = await self.session.execute(
            select(Payment)
            .join(Payment.member)
            .where(Member.pool_id == pool_id, Payment.period == period)
            .options(selectinload(Payment.member).selectinload(Member.user))
            .order_by(Member.joined_at, Member.id)
        )
        return result.scalars().all()

    async def list_unpaid_for_pool(self, pool_id: int) -> Sequence[Payment]:
        """Неоплачені (pending/claimed) платежі збору, від найстаріших."""
        result = await self.session.execute(
            select(Payment)
            .join(Payment.member)
            .where(Member.pool_id == pool_id, Payment.status != PaymentStatus.PAID)
            .options(selectinload(Payment.member).selectinload(Member.user))
            .order_by(Payment.period, Member.joined_at, Member.id)
        )
        return result.scalars().all()

    async def count_unpaid_in_pool_period(self, member_id: int, period: date) -> int:
        """Скільки неоплачених платежів за `period` у зборі, до якого належить `member_id`."""
        pool_id = select(Member.pool_id).where(Member.id == member_id).scalar_subquery()
        result = await self.session.execute(
            select(func.count())
            .select_from(Payment)
            .join(Payment.member)
            .where(
                Member.pool_id == pool_id,
                Payment.period == period,
                Payment.status != PaymentStatus.PAID,
            )
        )
        return result.scalar_one()

    async def list_unpaid_for_member(self, member_id: int) -> Sequence[Payment]:
        """Неоплачені платежі учасника, від найстарішого (для показу боргу)."""
        result = await self.session.execute(
            select(Payment)
            .where(Payment.member_id == member_id, Payment.status != PaymentStatus.PAID)
            .order_by(Payment.period)
        )
        return result.scalars().all()

    async def list_for_member(self, member_id: int, limit: int = 12) -> Sequence[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.member_id == member_id)
            .order_by(Payment.period.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_status(
        self, status: PaymentStatus, *, period: date | None = None
    ) -> Sequence[Payment]:
        """Платежі з певним статусом (для нагадувань) разом з учасником, збором і власником."""
        stmt = (
            select(Payment)
            .where(Payment.status == status)
            .options(
                selectinload(Payment.member).selectinload(Member.user),
                selectinload(Payment.member).selectinload(Member.pool).selectinload(Pool.owner),
            )
            .order_by(Payment.id)
        )
        if period is not None:
            stmt = stmt.where(Payment.period == period)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_unnotified_pending(self) -> Sequence[Payment]:
        """Платежі pending, про які учасник ще не отримав повідомлення."""
        result = await self.session.execute(
            select(Payment)
            .where(Payment.status == PaymentStatus.PENDING, Payment.notified_at.is_(None))
            .options(
                selectinload(Payment.member).selectinload(Member.user),
                selectinload(Payment.member).selectinload(Member.pool).selectinload(Pool.owner),
            )
            .order_by(Payment.id)
        )
        return result.scalars().all()

    async def save(self, payment: Payment) -> Payment:
        await self.session.flush()
        return payment
