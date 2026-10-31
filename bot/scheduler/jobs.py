"""Щогодинна джоба: створює платежі, надсилає запити «скинь» і нагадування.

Одна джоба проходить по всіх зборах (не окрема джоба на кожен збір). Кожен крок
ідемпотентний, тому повторний або паралельний запуск нічого не дублює:
* платежі — унікальний індекс (member_id, period);
* запит «скинь» — надсилається, поки `notified_at` порожнє;
* нагадування — `reminders_sent` + не частіше разу на день.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import keyboards, texts
from bot.db.models import Payment, utcnow
from bot.notifier import Delivery, notify
from bot.services.payments import PaymentService

logger = logging.getLogger(__name__)


@dataclass
class JobReport:
    created: int = 0
    requests_sent: int = 0
    reminders_sent: int = 0
    blocked: list[int] = field(default_factory=list)  # id учасників, що заблокували бота


class BillingJob:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        tz: ZoneInfo,
        billing_hour: int,
        *,
        clock: Callable[[], datetime] = utcnow,
        send_delay: float = 0.05,  # ~20 повідомлень/с, ліміт Telegram — 30/с
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.tz = tz
        self.billing_hour = billing_hour
        self.clock = clock
        self.send_delay = send_delay
        self._lock = asyncio.Lock()

    def _service(self, session: AsyncSession) -> PaymentService:
        return PaymentService(session, self.tz, self.billing_hour)

    async def run(self) -> JobReport:
        # Запуск при старті й щогодинний не мають перекриватися в одному процесі
        async with self._lock:
            now = self.clock()
            report = JobReport()
            try:
                await self._create_payments(now, report)
                await self._send_requests(now, report)
                await self._send_reminders(now, report)
            except Exception:
                logger.exception("Billing job failed")
            logger.info(
                "Billing job: created=%s requests=%s reminders=%s blocked=%s",
                report.created,
                report.requests_sent,
                report.reminders_sent,
                len(report.blocked),
            )
            return report

    async def _create_payments(self, now: datetime, report: JobReport) -> None:
        async with self.session_factory() as session:
            created = await self._service(session).create_due_payments(now)
            await session.commit()
        report.created = len(created)

    async def _send_requests(self, now: datetime, report: JobReport) -> None:
        async with self.session_factory() as session:
            service = self._service(session)
            for payment in await service.payments_to_notify():
                delivery = await notify(
                    self.bot,
                    session,
                    payment.member.user,
                    texts.payment_request(payment),
                    keyboards.payment_request_kb(payment.id),
                )
                if delivery is Delivery.SENT:
                    await service.mark_notified(payment, now)
                    report.requests_sent += 1
                elif delivery is Delivery.BLOCKED:
                    await self._warn_owner(session, payment, report)
                # Комітимо після кожного: падіння посеред циклу не призведе до повторів
                await session.commit()
                await asyncio.sleep(self.send_delay)

    async def _send_reminders(self, now: datetime, report: JobReport) -> None:
        async with self.session_factory() as session:
            service = self._service(session)
            for payment, moment in await service.payments_to_remind(now):
                delivery = await notify(
                    self.bot,
                    session,
                    payment.member.user,
                    texts.payment_reminder(payment),
                    keyboards.payment_request_kb(payment.id),
                )
                if delivery is Delivery.SENT:
                    await service.record_reminder(payment, moment, now)
                    report.reminders_sent += 1
                elif delivery is Delivery.BLOCKED:
                    await self._warn_owner(session, payment, report)
                await session.commit()
                await asyncio.sleep(self.send_delay)

    async def _warn_owner(self, session: AsyncSession, payment: Payment, report: JobReport) -> None:
        """Учасник щойно заблокував бота: кажемо власнику (один раз, далі учасника пропускаємо)."""
        report.blocked.append(payment.member_id)
        await notify(
            self.bot, session, payment.member.pool.owner, texts.owner_member_unreachable(payment)
        )
