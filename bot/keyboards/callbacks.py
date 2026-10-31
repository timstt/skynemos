from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class NewPoolAction(StrEnum):
    OWNER_YES = "owner_yes"
    OWNER_NO = "owner_no"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    FREQ_MONTHLY = "monthly"
    FREQ_YEARLY = "yearly"
    FREQ_ONCE = "once"


class NewPoolCB(CallbackData, prefix="new"):
    action: NewPoolAction


class JoinCB(CallbackData, prefix="join"):
    token: str


class PoolAction(StrEnum):
    LIST = "list"
    VIEW = "view"
    # власник
    INVITE = "invite"
    REGEN_INVITE = "regen"
    EDIT_TITLE = "title"
    EDIT_AMOUNT = "amount"
    EDIT_DAY = "day"
    EDIT_DETAILS = "details"
    MEMBERS = "members"
    UNPAID = "unpaid"
    PAUSE = "pause"
    RESUME = "resume"
    DELETE = "delete"
    DELETE_CONFIRM = "delete_ok"
    OWNER_WEIGHT = "owner_weight"
    # учасник
    HISTORY = "history"
    LEAVE = "leave"
    LEAVE_CONFIRM = "leave_ok"


class PoolCB(CallbackData, prefix="pool"):
    action: PoolAction
    pool_id: int = 0


class MemberAction(StrEnum):
    VIEW = "view"
    SET_SHARE = "share"
    SHARE_AUTO = "auto"
    REMOVE = "remove"
    REMOVE_CONFIRM = "remove_ok"
    SET_WEIGHT = "weight"
    TOGGLE_ADMIN = "admin"


class MemberCB(CallbackData, prefix="mem"):
    action: MemberAction
    pool_id: int
    member_id: int


class PaymentAction(StrEnum):
    CLAIM = "claim"
    CONFIRM = "confirm"
    REJECT = "reject"
    MARK_PAID = "mark"  # власник вручну (готівка тощо)
    SNOOZE = "snooze"  # учасник: «Нагадай завтра»


class PaymentCB(CallbackData, prefix="pay"):
    action: PaymentAction
    payment_id: int
