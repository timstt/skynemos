"""Гроші зберігаємо в копійках (int). Тут парсинг вводу користувача та форматування."""

import re
from decimal import Decimal, InvalidOperation

from bot.services.errors import DomainError, ErrorCode

MAX_AMOUNT_KOP = 100_000 * 100  # 100 000 грн

_AMOUNT_RE = re.compile(r"^\d+(\.\d{1,2})?$")
_CURRENCY_SUFFIX_RE = re.compile(r"(грн\.?|uah|₴)$", re.IGNORECASE)


def parse_amount(raw: str, *, allow_zero: bool = False) -> int:
    """Перетворює «300», «60,50», «1 200 грн» на копійки.

    Кидає DomainError(INVALID_AMOUNT), якщо формат хибний або сума поза межами (0; 100 000].
    """
    text = raw.strip().replace(" ", "").replace(" ", "")
    text = _CURRENCY_SUFFIX_RE.sub("", text).replace(",", ".")
    if not _AMOUNT_RE.fullmatch(text):
        raise DomainError(ErrorCode.INVALID_AMOUNT)
    try:
        kop = int(Decimal(text) * 100)
    except InvalidOperation as exc:  # pragma: no cover - regex вже відсіяв
        raise DomainError(ErrorCode.INVALID_AMOUNT) from exc

    if kop > MAX_AMOUNT_KOP or kop < 0 or (kop == 0 and not allow_zero):
        raise DomainError(ErrorCode.INVALID_AMOUNT)
    return kop


def format_money(kop: int) -> str:
    """6000 → «60 грн», 6050 → «60,50 грн», 120000 → «1 200 грн»."""
    sign = "-" if kop < 0 else ""
    hryvnias, kopecks = divmod(abs(kop), 100)
    whole = f"{hryvnias:,}".replace(",", " ")
    if kopecks:
        return f"{sign}{whole},{kopecks:02d} грн"
    return f"{sign}{whole} грн"
