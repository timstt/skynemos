from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.db.models import Member, Payment, Pool
from bot.keyboards.callbacks import (
    JoinCB,
    MemberAction,
    MemberCB,
    NewPoolAction,
    NewPoolCB,
    PaymentAction,
    PaymentCB,
    PoolAction,
    PoolCB,
)
from bot.services.money import format_money


def include_owner_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_OWNER_YES, callback_data=NewPoolCB(action=NewPoolAction.OWNER_YES))
    kb.button(text=texts.BTN_OWNER_NO, callback_data=NewPoolCB(action=NewPoolAction.OWNER_NO))
    kb.adjust(1)
    return kb.as_markup()


def confirm_create_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_CREATE, callback_data=NewPoolCB(action=NewPoolAction.CONFIRM))
    kb.button(text=texts.BTN_CANCEL, callback_data=NewPoolCB(action=NewPoolAction.CANCEL))
    kb.adjust(2)
    return kb.as_markup()


def join_kb(token: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_JOIN, callback_data=JoinCB(token=token))
    return kb.as_markup()


def my_pools_kb(owned: Sequence[Pool], memberships: Sequence[Member]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for pool in owned:
        kb.button(
            text=f"👑 {pool.title}",
            callback_data=PoolCB(action=PoolAction.VIEW, pool_id=pool.id),
        )
    for member in memberships:
        kb.button(
            text=f"🙋 {member.pool.title}",
            callback_data=PoolCB(action=PoolAction.VIEW, pool_id=member.pool_id),
        )
    kb.adjust(1)
    return kb.as_markup()


def _pool_btn(kb: InlineKeyboardBuilder, text: str, action: PoolAction, pool_id: int) -> None:
    kb.button(text=text, callback_data=PoolCB(action=action, pool_id=pool_id))


def owner_pool_kb(pool: Pool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _pool_btn(kb, texts.BTN_INVITE_LINK, PoolAction.INVITE, pool.id)
    _pool_btn(kb, texts.BTN_REGEN_INVITE, PoolAction.REGEN_INVITE, pool.id)
    _pool_btn(kb, texts.BTN_EDIT_AMOUNT, PoolAction.EDIT_AMOUNT, pool.id)
    _pool_btn(kb, texts.BTN_EDIT_DAY, PoolAction.EDIT_DAY, pool.id)
    _pool_btn(kb, texts.BTN_EDIT_DETAILS, PoolAction.EDIT_DETAILS, pool.id)
    _pool_btn(kb, texts.BTN_MEMBERS, PoolAction.MEMBERS, pool.id)
    _pool_btn(kb, texts.BTN_MARK_PAID, PoolAction.UNPAID, pool.id)
    if pool.is_paused:
        _pool_btn(kb, texts.BTN_RESUME, PoolAction.RESUME, pool.id)
    else:
        _pool_btn(kb, texts.BTN_PAUSE, PoolAction.PAUSE, pool.id)
    _pool_btn(kb, texts.BTN_DELETE, PoolAction.DELETE, pool.id)
    kb.button(text=texts.BTN_BACK_TO_LIST, callback_data=PoolCB(action=PoolAction.LIST))
    kb.adjust(2, 3, 1, 1, 1, 1, 1)
    return kb.as_markup()


def member_pool_kb(pool_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _pool_btn(kb, texts.BTN_HISTORY, PoolAction.HISTORY, pool_id)
    _pool_btn(kb, texts.BTN_LEAVE, PoolAction.LEAVE, pool_id)
    kb.button(text=texts.BTN_BACK_TO_LIST, callback_data=PoolCB(action=PoolAction.LIST))
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb(
    yes_text: str, yes: CallbackData, no_text: str, no: CallbackData
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=yes_text, callback_data=yes)
    kb.button(text=no_text, callback_data=no)
    kb.adjust(2)
    return kb.as_markup()


def members_kb(pool: Pool, members: Sequence[Member]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for member in members:
        kb.button(
            text=f"{texts.plain_name(member.user)} — {format_money(member.share_kop)}",
            callback_data=MemberCB(action=MemberAction.VIEW, pool_id=pool.id, member_id=member.id),
        )
    _pool_btn(kb, texts.BTN_BACK, PoolAction.VIEW, pool.id)
    kb.adjust(1)
    return kb.as_markup()


def member_manage_kb(pool_id: int, member: Member) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    def cb(action: MemberAction) -> MemberCB:
        return MemberCB(action=action, pool_id=pool_id, member_id=member.id)

    kb.button(text=texts.BTN_SET_SHARE, callback_data=cb(MemberAction.SET_SHARE))
    if member.share_is_custom:
        kb.button(text=texts.BTN_SHARE_AUTO, callback_data=cb(MemberAction.SHARE_AUTO))
    kb.button(text=texts.BTN_REMOVE_MEMBER, callback_data=cb(MemberAction.REMOVE))
    _pool_btn(kb, texts.BTN_BACK, PoolAction.MEMBERS, pool_id)
    kb.adjust(1)
    return kb.as_markup()


def unpaid_kb(pool_id: int, payments: Sequence[Payment]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for payment in payments:
        kb.button(
            text=texts.unpaid_button(payment),
            callback_data=PaymentCB(action=PaymentAction.MARK_PAID, payment_id=payment.id),
        )
    _pool_btn(kb, texts.BTN_BACK, PoolAction.VIEW, pool_id)
    kb.adjust(1)
    return kb.as_markup()


def back_to_pool_kb(pool_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_BACK, callback_data=PoolCB(action=PoolAction.VIEW, pool_id=pool_id))
    return kb.as_markup()


def open_pool_kb(pool_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=texts.BTN_OPEN_POOL, callback_data=PoolCB(action=PoolAction.VIEW, pool_id=pool_id)
    )
    return kb.as_markup()


def payment_request_kb(payment_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=texts.BTN_CLAIM,
        callback_data=PaymentCB(action=PaymentAction.CLAIM, payment_id=payment_id),
    )
    return kb.as_markup()


def owner_claim_kb(payment_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=texts.BTN_CONFIRM,
        callback_data=PaymentCB(action=PaymentAction.CONFIRM, payment_id=payment_id),
    )
    kb.button(
        text=texts.BTN_REJECT,
        callback_data=PaymentCB(action=PaymentAction.REJECT, payment_id=payment_id),
    )
    kb.adjust(2)
    return kb.as_markup()
