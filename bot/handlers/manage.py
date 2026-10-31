"""/my, картки зборів, меню керування власника та дії учасника.

Кожна дія власника, що зачіпає учасників, супроводжується їм сповіщенням.
"""

from collections.abc import Iterable
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.deep_linking import create_start_link
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards, texts
from bot.db.models import Frequency, Pool, User, utcnow
from bot.handlers.common import show
from bot.keyboards.callbacks import MemberAction, MemberCB, PoolAction, PoolCB
from bot.notifier import notify
from bot.services.billing import next_occurrence_year
from bot.services.errors import DomainError, ErrorCode
from bot.services.money import parse_amount
from bot.services.payments import PaymentService
from bot.services.pools import PoolService, ShareChange
from bot.services.validation import parse_day_month, validate_billing_day
from bot.states import EditPool

router = Router(name="manage")


# --- допоміжне -------------------------------------------------------------------


async def _pools_list(session: AsyncSession, user: User) -> tuple[str, InlineKeyboardMarkup | None]:
    pools = await PoolService(session).list_user_pools(user)
    if not pools.owned and not pools.memberships:
        return texts.NO_POOLS, None
    return (
        texts.my_pools(pools.owned, pools.memberships),
        keyboards.my_pools_kb(pools.owned, pools.memberships),
    )


async def _owner_card(service: PoolService, pool: Pool) -> tuple[str, InlineKeyboardMarkup]:
    members = await service.list_active_members(pool)
    return texts.owner_pool_card(pool, members), keyboards.owner_pool_kb(pool)


async def _notify_users(bot: Bot, session: AsyncSession, users: Iterable[User], text: str) -> None:
    for user in users:
        await notify(bot, session, user, text)


async def _notify_share_changes(
    bot: Bot, session: AsyncSession, pool: Pool, changes: Iterable[ShareChange]
) -> None:
    for change in changes:
        await notify(
            bot,
            session,
            change.member.user,
            texts.member_share_changed(pool, change.old_kop, change.new_kop),
        )


async def _owned_pool_or_alert(
    callback: CallbackQuery, service: PoolService, pool_id: int, user: User
) -> Pool | None:
    try:
        return await service.get_owned_pool(pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return None


# --- список і картка збору ---------------------------------------------------------


@router.message(Command("my"))
async def cmd_my(message: Message, session: AsyncSession, user: User) -> None:
    text, kb = await _pools_list(session, user)
    await message.answer(text, reply_markup=kb)


@router.callback_query(PoolCB.filter(F.action == PoolAction.LIST))
async def show_list(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    text, kb = await _pools_list(session, user)
    await show(callback, text, kb)
    await callback.answer()


@router.callback_query(PoolCB.filter(F.action == PoolAction.VIEW))
async def show_pool(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    await state.clear()  # «Назад» з режиму редагування скасовує його
    service = PoolService(session)
    try:
        pool = await service.get_owned_pool(callback_data.pool_id, user)
    except DomainError as exc:
        if exc.code is not ErrorCode.NOT_POOL_OWNER:
            await callback.answer(texts.error_text(exc), show_alert=True)
            return
    else:
        await show(callback, *await _owner_card(service, pool))
        await callback.answer()
        return

    try:
        member = await service.get_membership(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    debt = await PaymentService(session, tz, billing_hour).member_debt(member.id)
    await show(
        callback,
        texts.member_pool_card(member, debt),
        keyboards.member_pool_kb(member.pool_id, is_admin=member.is_admin),
    )
    await callback.answer()


# --- посилання-запрошення ----------------------------------------------------------


@router.callback_query(PoolCB.filter(F.action.in_({PoolAction.INVITE, PoolAction.REGEN_INVITE})))
async def show_invite(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    regenerate = callback_data.action is PoolAction.REGEN_INVITE
    try:
        if regenerate:
            pool = await service.regenerate_invite(callback_data.pool_id, user)
        else:
            pool = await service.get_owned_pool(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    link = await create_start_link(bot, f"join_{pool.invite_token}")
    text = texts.invite_regenerated(pool, link) if regenerate else texts.invite_link(pool, link)
    await show(callback, text, keyboards.back_to_pool_kb(pool.id))
    await callback.answer()


# --- редагування суми, дня, реквізитів -----------------------------------------------

_EDIT_STATES = {
    PoolAction.EDIT_TITLE: (EditPool.title, texts.ask_new_title),
    PoolAction.EDIT_AMOUNT: (EditPool.amount, texts.ask_new_amount),
    PoolAction.EDIT_DAY: (EditPool.billing_day, texts.ask_new_day),
    PoolAction.EDIT_DETAILS: (EditPool.details, texts.ask_new_details),
}


@router.callback_query(PoolCB.filter(F.action.in_(set(_EDIT_STATES))))
async def start_edit(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    pool = await _owned_pool_or_alert(callback, PoolService(session), callback_data.pool_id, user)
    if pool is None:
        return
    new_state, prompt = _EDIT_STATES[callback_data.action]
    if callback_data.action is PoolAction.EDIT_DAY and pool.frequency is not Frequency.MONTHLY:
        new_state, prompt = EditPool.billing_date, texts.ask_new_date
    await state.set_state(new_state)
    await state.update_data(pool_id=pool.id)
    await show(callback, prompt(pool), keyboards.back_to_pool_kb(pool.id))
    await callback.answer()


@router.message(StateFilter(EditPool), F.text.startswith("/"))
async def command_while_editing(message: Message) -> None:
    await message.answer(texts.EXPECT_TEXT_INPUT)


@router.message(StateFilter(EditPool), ~F.text)
async def non_text_while_editing(message: Message) -> None:
    await message.answer(texts.EXPECT_TEXT_INPUT)


async def _finish_edit(
    message: Message, state: FSMContext, service: PoolService, pool: Pool, note: str = ""
) -> None:
    await state.clear()
    text, kb = await _owner_card(service, pool)
    await message.answer(f"{texts.SAVED}{note}\n\n{text}", reply_markup=kb)


@router.message(EditPool.title, F.text)
async def got_new_title(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    try:
        pool, old_title = await service.update_title(
            (await state.get_data())["pool_id"], user, message.text or ""
        )
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_TITLE:
            await state.clear()
        return
    if pool.title != old_title:
        members = await service.list_active_members(pool)
        await _notify_users(
            bot, session, (m.user for m in members), texts.member_title_changed(old_title, pool)
        )
    await _finish_edit(message, state, service, pool)


@router.message(EditPool.amount, F.text)
async def got_new_amount(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    try:
        amount = parse_amount(message.text or "")
        update = await service.update_total((await state.get_data())["pool_id"], user, amount)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_AMOUNT:
            await state.clear()
        return
    await _notify_share_changes(bot, session, update.pool, update.changes)
    note = texts.custom_shares_reset_note() if update.custom_reset else ""
    await _finish_edit(message, state, service, update.pool, note)


@router.message(EditPool.billing_day, F.text)
async def got_new_day(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    try:
        day = validate_billing_day(message.text or "")
        pool = await service.update_billing_day((await state.get_data())["pool_id"], user, day)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_BILLING_DAY:
            await state.clear()
        return
    members = await service.list_active_members(pool)
    await _notify_users(bot, session, (m.user for m in members), texts.member_day_changed(pool))
    await _finish_edit(message, state, service, pool)


@router.message(EditPool.billing_date, F.text)
async def got_new_date(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    bot: Bot,
    tz: ZoneInfo,
) -> None:
    service = PoolService(session)
    try:
        day, month = parse_day_month(message.text or "")
        pool = await service.get_owned_pool((await state.get_data())["pool_id"], user)
        year = None
        if pool.frequency is Frequency.ONCE:
            year = next_occurrence_year(day, month, utcnow().astimezone(tz).date())
        pool = await service.update_billing_date(pool.id, user, day, month, year)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_DATE:
            await state.clear()
        return
    members = await service.list_active_members(pool)
    await _notify_users(bot, session, (m.user for m in members), texts.member_day_changed(pool))
    await _finish_edit(message, state, service, pool)


@router.message(EditPool.details, F.text)
async def got_new_details(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    try:
        pool = await service.update_details(
            (await state.get_data())["pool_id"], user, message.text or ""
        )
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_DETAILS:
            await state.clear()
        return
    members = await service.list_active_members(pool)
    await _notify_users(bot, session, (m.user for m in members), texts.member_details_changed(pool))
    await _finish_edit(message, state, service, pool)


# --- учасники та частки ----------------------------------------------------------------


@router.callback_query(PoolCB.filter(F.action == PoolAction.MEMBERS))
async def show_members(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    service = PoolService(session)
    pool = await _owned_pool_or_alert(callback, service, callback_data.pool_id, user)
    if pool is None:
        return
    members = await service.list_active_members(pool)
    await show(callback, texts.members_list(pool, members), keyboards.members_kb(pool, members))
    await callback.answer()


@router.callback_query(MemberCB.filter())
async def member_action(
    callback: CallbackQuery,
    callback_data: MemberCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    service = PoolService(session)
    action = callback_data.action
    try:
        pool = await service.get_owned_pool(callback_data.pool_id, user)
        member = await service.get_active_member(pool, callback_data.member_id)

        if action is MemberAction.VIEW:
            await show(
                callback, texts.member_card(member), keyboards.member_manage_kb(pool.id, member)
            )
        elif action is MemberAction.SET_SHARE:
            await state.set_state(EditPool.member_share)
            await state.update_data(pool_id=pool.id, member_id=member.id)
            await show(
                callback,
                texts.ask_member_share(pool, member),
                keyboards.back_to_pool_kb(pool.id),
            )
        elif action is MemberAction.SHARE_AUTO:
            update = await service.set_member_share(pool.id, user, member.id, None)
            await _notify_share_changes(bot, session, pool, update.changes)
            await show(
                callback, texts.member_card(member), keyboards.member_manage_kb(pool.id, member)
            )
        elif action is MemberAction.SET_WEIGHT:
            await state.set_state(EditPool.member_weight)
            await state.update_data(pool_id=pool.id, member_id=member.id)
            await show(
                callback, texts.ask_member_weight(member), keyboards.back_to_pool_kb(pool.id)
            )
        elif action is MemberAction.TOGGLE_ADMIN:
            member = await service.set_admin(pool.id, user, member.id, not member.is_admin)
            text = (
                texts.member_admin_granted(pool)
                if member.is_admin
                else texts.member_admin_revoked(pool)
            )
            await notify(bot, session, member.user, text)
            await show(
                callback, texts.member_card(member), keyboards.member_manage_kb(pool.id, member)
            )
        elif action is MemberAction.REMOVE:
            await show(
                callback,
                texts.confirm_remove_member(member),
                keyboards.confirm_kb(
                    texts.BTN_DELETE_CONFIRM,
                    MemberCB(
                        action=MemberAction.REMOVE_CONFIRM, pool_id=pool.id, member_id=member.id
                    ),
                    texts.BTN_KEEP,
                    MemberCB(action=MemberAction.VIEW, pool_id=pool.id, member_id=member.id),
                ),
            )
        elif action is MemberAction.REMOVE_CONFIRM:
            removal = await service.remove_member(pool.id, user, member.id)
            await notify(bot, session, removal.member.user, texts.member_removed(pool))
            await _notify_share_changes(bot, session, pool, removal.changes)
            members = await service.list_active_members(pool)
            await show(
                callback, texts.members_list(pool, members), keyboards.members_kb(pool, members)
            )
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    await callback.answer()


@router.message(EditPool.member_share, F.text)
async def got_member_share(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    data = await state.get_data()
    try:
        share = parse_amount(message.text or "", allow_zero=True)
        update = await service.set_member_share(data["pool_id"], user, data["member_id"], share)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code not in {ErrorCode.INVALID_AMOUNT, ErrorCode.INVALID_SHARE}:
            await state.clear()
        return
    await _notify_share_changes(bot, session, update.pool, update.changes)
    await _finish_edit(message, state, service, update.pool)


@router.message(EditPool.member_weight, F.text)
async def got_member_weight(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    data = await state.get_data()
    try:
        weight = _parse_weight(message.text or "")
        update = await service.set_member_weight(data["pool_id"], user, data["member_id"], weight)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_WEIGHT:
            await state.clear()
        return
    await _notify_share_changes(bot, session, update.pool, update.changes)
    await _finish_edit(message, state, service, update.pool)


@router.callback_query(PoolCB.filter(F.action == PoolAction.OWNER_WEIGHT))
async def start_owner_weight(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    pool = await _owned_pool_or_alert(callback, PoolService(session), callback_data.pool_id, user)
    if pool is None:
        return
    await state.set_state(EditPool.owner_weight)
    await state.update_data(pool_id=pool.id)
    await show(callback, texts.ask_owner_weight(pool), keyboards.back_to_pool_kb(pool.id))
    await callback.answer()


@router.message(EditPool.owner_weight, F.text)
async def got_owner_weight(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    service = PoolService(session)
    try:
        weight = _parse_weight(message.text or "")
        update = await service.set_owner_weight((await state.get_data())["pool_id"], user, weight)
    except DomainError as exc:
        await message.answer(texts.error_text(exc))
        if exc.code is not ErrorCode.INVALID_WEIGHT:
            await state.clear()
        return
    await _notify_share_changes(bot, session, update.pool, update.changes)
    await _finish_edit(message, state, service, update.pool)


def _parse_weight(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise DomainError(ErrorCode.INVALID_WEIGHT) from exc


# --- ручна позначка оплати ---------------------------------------------------------------


@router.callback_query(PoolCB.filter(F.action == PoolAction.UNPAID))
async def show_unpaid(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    try:
        pool = await PoolService(session).get_managed_pool(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    payments = await PaymentService(session, tz, billing_hour).unpaid_for_pool(pool)
    if pool.owner_id != user.id:
        # Співвласник не підтверджує власні платежі
        payments = [p for p in payments if p.member.user_id != user.id]
    text = texts.unpaid_list(pool) if payments else texts.NO_UNPAID
    await show(callback, text, keyboards.unpaid_kb(pool.id, payments))
    await callback.answer()


# --- пауза та видалення ------------------------------------------------------------------


@router.callback_query(PoolCB.filter(F.action.in_({PoolAction.PAUSE, PoolAction.RESUME})))
async def toggle_pause(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    service = PoolService(session)
    paused = callback_data.action is PoolAction.PAUSE
    try:
        pool = await service.get_owned_pool(callback_data.pool_id, user)
        was_paused = pool.is_paused
        pool = await service.set_paused(pool.id, user, paused, utcnow())
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return

    if was_paused == paused:
        await callback.answer()
    else:
        members = [m.user for m in await service.list_active_members(pool)]
        if paused:
            await _notify_users(bot, session, members, texts.member_pool_paused(pool))
            await callback.answer(texts.PAUSED_ALERT, show_alert=True)
        else:
            status = await PaymentService(session, tz, billing_hour).pool_status(pool, utcnow())
            await _notify_users(
                bot, session, members, texts.member_pool_resumed(pool, status.next_billing)
            )
            await callback.answer(texts.resumed_alert(status.next_billing), show_alert=True)
    await show(callback, *await _owner_card(service, pool))


@router.callback_query(PoolCB.filter(F.action == PoolAction.DELETE))
async def ask_delete(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User
) -> None:
    pool = await _owned_pool_or_alert(callback, PoolService(session), callback_data.pool_id, user)
    if pool is None:
        return
    await show(
        callback,
        texts.confirm_delete(pool),
        keyboards.confirm_kb(
            texts.BTN_DELETE_CONFIRM,
            PoolCB(action=PoolAction.DELETE_CONFIRM, pool_id=pool.id),
            texts.BTN_KEEP,
            PoolCB(action=PoolAction.VIEW, pool_id=pool.id),
        ),
    )
    await callback.answer()


@router.callback_query(PoolCB.filter(F.action == PoolAction.DELETE_CONFIRM))
async def delete_pool(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    try:
        deleted = await PoolService(session).delete_pool(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    await _notify_users(bot, session, deleted.members, texts.member_pool_deleted(deleted.title))
    text, kb = await _pools_list(session, user)
    await show(callback, f"{texts.pool_deleted(deleted.title)}\n\n{text}", kb)
    await callback.answer()


# --- дії учасника --------------------------------------------------------------------------


@router.callback_query(PoolCB.filter(F.action == PoolAction.HISTORY))
async def show_history(
    callback: CallbackQuery,
    callback_data: PoolCB,
    session: AsyncSession,
    user: User,
    tz: ZoneInfo,
    billing_hour: int,
) -> None:
    try:
        member = await PoolService(session).get_membership(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    payments = await PaymentService(session, tz, billing_hour).member_history(member)
    await show(
        callback, texts.payment_history(member, payments), keyboards.back_to_pool_kb(member.pool_id)
    )
    await callback.answer()


@router.callback_query(PoolCB.filter(F.action == PoolAction.LEAVE))
async def ask_leave(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User
) -> None:
    try:
        member = await PoolService(session).get_membership(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    await show(
        callback,
        texts.confirm_leave(member.pool),
        keyboards.confirm_kb(
            texts.BTN_LEAVE_CONFIRM,
            PoolCB(action=PoolAction.LEAVE_CONFIRM, pool_id=member.pool_id),
            texts.BTN_STAY,
            PoolCB(action=PoolAction.VIEW, pool_id=member.pool_id),
        ),
    )
    await callback.answer()


@router.callback_query(PoolCB.filter(F.action == PoolAction.LEAVE_CONFIRM))
async def leave_pool(
    callback: CallbackQuery, callback_data: PoolCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    try:
        removal = await PoolService(session).leave_pool(callback_data.pool_id, user)
    except DomainError as exc:
        await callback.answer(texts.error_text(exc), show_alert=True)
        return
    await notify(
        bot, session, removal.pool.owner, texts.owner_member_left(removal.pool, removal.member)
    )
    text, kb = await _pools_list(session, user)
    await show(callback, f"{texts.left_pool(removal.pool)}\n\n{text}", kb)
    await callback.answer()
