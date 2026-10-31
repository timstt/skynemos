"""Кнопки платежів («Я скинув», «Підтвердити», «Не бачу оплати») та /status."""

from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards, texts
from bot.db.models import PaymentStatus, User, utcnow
from bot.handlers.common import show
from bot.keyboards.callbacks import PaymentAction, PaymentCB
from bot.notifier import notify
from bot.services.errors import DomainError
from bot.services.payments import PaymentService, TransitionResult

router = Router(name="payments")


async def _announce_if_completed(bot: Bot, session: AsyncSession, result: TransitionResult) -> None:
    """Останній платіж періоду підтверджено: радісне повідомлення власнику."""
    if result.period_completed:
        pool = result.payment.member.pool
        await notify(bot, session, pool.owner, texts.owner_all_paid(pool, result.payment.period))


@router.callback_query(PaymentCB.filter(F.action == PaymentAction.CLAIM))
async def claim(
    callback: CallbackQuery,
    callback_data: PaymentCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    service = PaymentService(session, tz, billing_hour)
    try:
        result = await service.claim(callback_data.payment_id, user, utcnow())
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return

    payment = result.payment
    if not result.changed:
        paid = payment.status is PaymentStatus.PAID
        already = texts.ALREADY_PAID if paid else texts.ALREADY_CLAIMED
        await callback.answer(already, show_alert=True)
        return

    await show(callback, texts.payment_claimed_member(payment))
    await callback.answer("Передав власнику на перевірку 👌")
    await notify(
        bot,
        session,
        payment.member.pool.owner,
        texts.owner_claim(payment),
        keyboards.owner_claim_kb(payment.id),
    )


@router.callback_query(PaymentCB.filter(F.action == PaymentAction.CONFIRM))
async def confirm(
    callback: CallbackQuery,
    callback_data: PaymentCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    service = PaymentService(session, tz, billing_hour)
    try:
        result = await service.confirm(callback_data.payment_id, user, utcnow())
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return

    await show(callback, texts.owner_confirmed(result.payment))
    if not result.changed:
        await callback.answer(texts.ALREADY_PAID)
        return
    await callback.answer("Підтверджено ✅")
    await notify(bot, session, result.payment.member.user, texts.member_confirmed(result.payment))
    await _announce_if_completed(bot, session, result)


@router.callback_query(PaymentCB.filter(F.action == PaymentAction.REJECT))
async def reject(
    callback: CallbackQuery,
    callback_data: PaymentCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    service = PaymentService(session, tz, billing_hour)
    try:
        result = await service.reject(callback_data.payment_id, user, utcnow())
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return

    payment = result.payment
    await show(callback, texts.owner_rejected(payment))
    if not result.changed:
        await callback.answer(texts.ALREADY_REJECTED)
        return
    await callback.answer("Учаснику повідомлено")
    await notify(
        bot,
        session,
        payment.member.user,
        texts.member_rejected(payment),
        keyboards.payment_request_kb(payment),
    )


@router.message(Command("status"))
async def cmd_status(
    message: Message, session: AsyncSession, user: User, tz: ZoneInfo, billing_hour: int
) -> None:
    statuses = await PaymentService(session, tz, billing_hour).owner_statuses(user, utcnow())
    if not statuses:
        await message.answer(texts.STATUS_NO_POOLS)
        return
    await message.answer(texts.statuses(statuses))


@router.callback_query(PaymentCB.filter(F.action == PaymentAction.MARK_PAID))
async def mark_paid(
    callback: CallbackQuery,
    callback_data: PaymentCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    """Власник вручну позначає платіж оплаченим (зі списку «Позначити оплату вручну»)."""
    service = PaymentService(session, tz, billing_hour)
    try:
        result = await service.mark_paid(callback_data.payment_id, user, utcnow())
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return

    payment = result.payment
    pool = payment.member.pool
    if result.changed:
        await callback.answer(texts.MARKED_PAID_ALERT)
        await notify(bot, session, payment.member.user, texts.member_marked_paid(payment))
        await _announce_if_completed(bot, session, result)
    else:
        await callback.answer(texts.ALREADY_PAID)
    unpaid = await service.unpaid_for_pool(pool)
    text = texts.unpaid_list(pool) if unpaid else texts.NO_UNPAID
    await show(
        callback,
        f"{texts.marked_paid_owner(payment)}\n\n{text}",
        keyboards.unpaid_kb(pool.id, unpaid),
    )
