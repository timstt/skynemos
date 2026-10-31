from bot.db.models import MAX_TITLE_LENGTH
from bot.services.errors import DomainError, ErrorCode

MAX_DETAILS_LENGTH = 500


def validate_title(raw: str) -> str:
    title = " ".join(raw.split())
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise DomainError(ErrorCode.INVALID_TITLE)
    return title


def validate_billing_day(raw: str | int) -> int:
    try:
        day = int(str(raw).strip())
    except ValueError as exc:
        raise DomainError(ErrorCode.INVALID_BILLING_DAY) from exc
    if not 1 <= day <= 31:
        raise DomainError(ErrorCode.INVALID_BILLING_DAY)
    return day


def validate_payment_details(raw: str) -> str:
    details = raw.strip()
    if not details or len(details) > MAX_DETAILS_LENGTH:
        raise DomainError(ErrorCode.INVALID_DETAILS)
    return details
