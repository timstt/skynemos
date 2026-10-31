from aiogram.fsm.state import State, StatesGroup


class CreatePool(StatesGroup):
    title = State()
    amount = State()
    billing_day = State()
    include_owner = State()
    payment_details = State()
    confirm = State()


class EditPool(StatesGroup):
    """Власник вводить нове значення. У даних стану: pool_id (і member_id для частки)."""

    amount = State()
    billing_day = State()
    details = State()
    member_share = State()
    member_weight = State()
    owner_weight = State()
