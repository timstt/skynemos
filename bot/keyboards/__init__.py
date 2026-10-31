from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.db.models import Member, Pool
from bot.keyboards.callbacks import (
    JoinCB,
    NewPoolAction,
    NewPoolCB,
    PaymentAction,
    PaymentCB,
    PoolAction,
    PoolCB,
)


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


def owner_pool_kb(pool: Pool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=texts.BTN_INVITE_LINK,
        callback_data=PoolCB(action=PoolAction.INVITE, pool_id=pool.id),
    )
    kb.button(text=texts.BTN_BACK_TO_LIST, callback_data=PoolCB(action=PoolAction.LIST))
    kb.adjust(1)
    return kb.as_markup()


def member_pool_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_BACK_TO_LIST, callback_data=PoolCB(action=PoolAction.LIST))
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
