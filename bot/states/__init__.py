from aiogram.fsm.state import State, StatesGroup


class CreatePool(StatesGroup):
    title = State()
    amount = State()
    billing_day = State()
    include_owner = State()
    payment_details = State()
    confirm = State()
