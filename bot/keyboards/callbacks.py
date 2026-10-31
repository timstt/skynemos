from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class NewPoolAction(StrEnum):
    OWNER_YES = "owner_yes"
    OWNER_NO = "owner_no"
    CONFIRM = "confirm"
    CANCEL = "cancel"


class NewPoolCB(CallbackData, prefix="new"):
    action: NewPoolAction


class JoinCB(CallbackData, prefix="join"):
    token: str


class PoolAction(StrEnum):
    LIST = "list"
    VIEW = "view"
    INVITE = "invite"


class PoolCB(CallbackData, prefix="pool"):
    action: PoolAction
    pool_id: int = 0
