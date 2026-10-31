from enum import StrEnum


class ErrorCode(StrEnum):
    # Валідація вводу
    INVALID_TITLE = "invalid_title"
    INVALID_AMOUNT = "invalid_amount"
    INVALID_BILLING_DAY = "invalid_billing_day"
    INVALID_DETAILS = "invalid_details"
    # Збори та учасники
    POOL_NOT_FOUND = "pool_not_found"
    NOT_POOL_OWNER = "not_pool_owner"
    OWNER_CANNOT_JOIN = "owner_cannot_join"
    POOL_FULL = "pool_full"
    NOT_A_MEMBER = "not_a_member"
    MEMBER_NOT_FOUND = "member_not_found"
    INVALID_SHARE = "invalid_share"
    # Платежі
    PAYMENT_NOT_FOUND = "payment_not_found"
    INVALID_TRANSITION = "invalid_transition"


class DomainError(Exception):
    """Помилка бізнес-логіки. Handler перетворює `code` на текст для користувача."""

    def __init__(self, code: ErrorCode, message: str = "") -> None:
        super().__init__(message or code.value)
        self.code = code
