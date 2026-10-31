"""Розбір реквізитів для оплати: номери карток і посилання. Чисті функції, без aiogram."""

import re
from html import escape
from urllib.parse import urlsplit

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# Що копіюється одним дотиком (обгортається в <code>):
# * український IBAN: UA + 27 цифр (разом 29 символів), можливо з пробілами — цілком;
# * номер картки: 13–19 цифр, можливо через пробіли чи дефіси.
# Межі не дають обгорнути лише ЧАСТИНУ довшого ряду цифр (напр. середину IBAN без «UA»):
# перед і після збігу не може бути ні літери/цифри, ні «пробіл/дефіс + цифра».
_CARD_RE = re.compile(
    r"(?<!\w)(?<!\d[ -])"  # не продовження попереднього ряду цифр
    r"(?:UA\d{2}(?: ?\d){25}"  # IBAN
    r"|\d(?:[ -]?\d){12,18})"  # картка
    r"(?![ -]?\d)(?!\w)",  # і не обрізаний початок довшого ряду
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?)»"
MONOBANK_JAR_HOST = "send.monobank.ua"


def _split_urls(text: str) -> list[tuple[str, bool]]:
    """Ділить текст на шматки (фрагмент, це_посилання)."""
    parts: list[tuple[str, bool]] = []
    pos = 0
    for match in _URL_RE.finditer(text):
        url = match.group().rstrip(_TRAILING_PUNCT)
        start, end = match.start(), match.start() + len(url)
        if start > pos:
            parts.append((text[pos:start], False))
        parts.append((url, True))
        pos = end
    if pos < len(text):
        parts.append((text[pos:], False))
    return parts


def format_details_html(details: str) -> str:
    """Реквізити для HTML-повідомлення: усе екрановано, номери карток у <code>.

    `<code>` у Telegram копіюється одним дотиком. Цифри всередині посилань не чіпаємо.
    """
    out: list[str] = []
    for chunk, is_url in _split_urls(details):
        escaped = escape(chunk)
        if not is_url:
            escaped = _CARD_RE.sub(lambda m: f"<code>{m.group()}</code>", escaped)
        out.append(escaped)
    return "".join(out)


def payment_url(details: str) -> str | None:
    """Перше коректне http(s)-посилання з реквізитів (для кнопки «Відкрити»), або None.

    Некоректний URL у кнопці змусив би Telegram відхилити все повідомлення.
    """
    for chunk, is_url in _split_urls(details):
        if not is_url:
            continue
        parts = urlsplit(chunk)
        if parts.scheme in {"http", "https"} and parts.netloc and "." in parts.netloc:
            return chunk
    return None


def is_monobank_jar(url: str) -> bool:
    return urlsplit(url).netloc.lower() == MONOBANK_JAR_HOST
