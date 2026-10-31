import calendar
import re

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


def parse_day_month(raw: str) -> tuple[int, int]:
    """«05.03», «5.3», «5/3», «05-03» → (день, місяць). 29 лютого дозволено (у невисокосні — 28)."""
    match = re.fullmatch(r"\s*(\d{1,2})\s*[./-]\s*(\d{1,2})\s*", raw)
    if match is None:
        raise DomainError(ErrorCode.INVALID_DATE)
    day, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise DomainError(ErrorCode.INVALID_DATE)
    max_day = 29 if month == 2 else calendar.monthrange(2001, month)[1]
    if not 1 <= day <= max_day:
        raise DomainError(ErrorCode.INVALID_DATE)
    return day, month
