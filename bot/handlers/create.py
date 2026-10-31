"""/new — покрокове створення збору (FSM)."""

from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards, texts
from bot.db.models import Frequency, User, utcnow
from bot.handlers.common import show
from bot.keyboards.callbacks import NewPoolAction, NewPoolCB
from bot.services.billing import next_occurrence_year
from bot.services.errors import DomainError
from bot.services.money import parse_amount
from bot.services.pools import NewPoolData, PoolService
from bot.services.validation import (
    parse_day_month,
    validate_billing_day,
    validate_payment_details,
    validate_title,
)
from bot.states import CreatePool

router = Router(name="create")


def _pool_data(data: dict[str, Any]) -> NewPoolData:
    """Дані діалогу → NewPoolData (частота зберігається в стані рядком)."""
    return NewPoolData(
        title=data["title"],
        total_amount_kop=data["total_amount_kop"],
        billing_day=data["billing_day"],
        include_owner=data["include_owner"],
        payment_details=data["payment_details"],
        frequency=Frequency(data.get("frequency", Frequency.MONTHLY.value)),
        billing_month=data.get("billing_month"),
        billing_year=data.get("billing_year"),
    )


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreatePool.title)
    await message.answer(texts.ASK_TITLE)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL)
        return
    await state.clear()
    await message.answer(texts.CANCELLED)


# Невідомі команди та не-текст під час діалогу не мають сприйматися як відповідь
@router.message(StateFilter(CreatePool), F.text.startswith("/"))
async def command_in_dialog(message: Message) -> None:
    await message.answer(texts.LOOKS_LIKE_COMMAND)


@router.message(StateFilter(CreatePool.frequency, CreatePool.include_owner, CreatePool.confirm))
async def expect_button(message: Message) -> None:
    await message.answer(texts.EXPECT_BUTTON)


@router.message(StateFilter(CreatePool), ~F.text)
async def expect_text(message: Message) -> None:
    await message.answer(texts.EXPECT_TEXT)


@router.message(CreatePool.title, F.text)
async def got_title(message: Message, state: FSMContext) -> None:
    try:
        title = validate_title(message.text or "")
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        return
    await state.update_data(title=title)
    await state.set_state(CreatePool.amount)
    await message.answer(texts.ASK_AMOUNT)


@router.message(CreatePool.amount, F.text)
async def got_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = parse_amount(message.text or "")
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        return
    await state.update_data(total_amount_kop=amount)
    await state.set_state(CreatePool.frequency)
    await message.answer(texts.ASK_FREQUENCY, reply_markup=keyboards.frequency_kb())


_FREQUENCIES = {
    NewPoolAction.FREQ_MONTHLY: Frequency.MONTHLY,
    NewPoolAction.FREQ_YEARLY: Frequency.YEARLY,
    NewPoolAction.FREQ_ONCE: Frequency.ONCE,
}


@router.callback_query(CreatePool.frequency, NewPoolCB.filter(F.action.in_(set(_FREQUENCIES))))
async def got_frequency(
    callback: CallbackQuery, callback_data: NewPoolCB, state: FSMContext
) -> None:
    frequency = _FREQUENCIES[callback_data.action]
    await state.update_data(frequency=frequency.value)
    await show(callback, f"{texts.ASK_FREQUENCY}\n\n👉 {texts.frequency_label(frequency)}")
    await callback.answer()
    if frequency is Frequency.MONTHLY:
        await state.set_state(CreatePool.billing_day)
        prompt = texts.ASK_BILLING_DAY
    else:
        await state.set_state(CreatePool.billing_date)
        prompt = texts.ask_billing_date(frequency)
    if isinstance(callback.message, Message):
        await callback.message.answer(prompt)


@router.message(CreatePool.billing_date, F.text)
async def got_billing_date(message: Message, state: FSMContext, tz: ZoneInfo) -> None:
    try:
        day, month = parse_day_month(message.text or "")
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        return
    frequency = Frequency((await state.get_data())["frequency"])
    year = None
    if frequency is Frequency.ONCE:
        year = next_occurrence_year(day, month, utcnow().astimezone(tz).date())
    await state.update_data(billing_day=day, billing_month=month, billing_year=year)
    await state.set_state(CreatePool.include_owner)
    await message.answer(texts.ASK_INCLUDE_OWNER, reply_markup=keyboards.include_owner_kb())


@router.message(CreatePool.billing_day, F.text)
async def got_billing_day(message: Message, state: FSMContext) -> None:
    try:
        day = validate_billing_day(message.text or "")
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        return
    await state.update_data(billing_day=day)
    await state.set_state(CreatePool.include_owner)
    await message.answer(texts.ASK_INCLUDE_OWNER, reply_markup=keyboards.include_owner_kb())


@router.callback_query(
    CreatePool.include_owner,
    NewPoolCB.filter(F.action.in_({NewPoolAction.OWNER_YES, NewPoolAction.OWNER_NO})),
)
async def got_include_owner(
    callback: CallbackQuery, callback_data: NewPoolCB, state: FSMContext
) -> None:
    include_owner = callback_data.action is NewPoolAction.OWNER_YES
    await state.update_data(include_owner=include_owner)
    await state.set_state(CreatePool.payment_details)
    choice = texts.BTN_OWNER_YES if include_owner else texts.BTN_OWNER_NO
    await show(callback, f"{texts.ASK_INCLUDE_OWNER}\n\n👉 {choice}")
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.ASK_DETAILS)


@router.message(CreatePool.payment_details, F.text)
async def got_details(message: Message, state: FSMContext) -> None:
    try:
        details = validate_payment_details(message.text or "")
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        return
    await state.update_data(payment_details=details)
    await state.set_state(CreatePool.confirm)
    data = _pool_data(await state.get_data())
    await message.answer(texts.confirm_pool(data), reply_markup=keyboards.confirm_create_kb())


@router.callback_query(CreatePool.confirm, NewPoolCB.filter(F.action == NewPoolAction.CONFIRM))
async def confirm_create(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    data = _pool_data(await state.get_data())
    try:
        pool = await PoolService(session).create_pool(user, data)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    await state.clear()
    link = await create_start_link(bot, f"join_{pool.invite_token}")
    await show(callback, texts.pool_created(pool, link), keyboards.open_pool_kb(pool.id))
    await callback.answer()


@router.callback_query(CreatePool.confirm, NewPoolCB.filter(F.action == NewPoolAction.CANCEL))
async def cancel_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(callback, texts.CANCELLED)
    await callback.answer()


@router.callback_query(NewPoolCB.filter())
async def stale_create_button(callback: CallbackQuery) -> None:
    """Кнопка зі старого діалогу (стан уже інший або скинувся після перезапуску)."""
    await callback.answer(texts.CREATE_SESSION_EXPIRED, show_alert=True)
