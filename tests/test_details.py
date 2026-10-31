import pytest

from bot.services.details import format_details_html, is_monobank_jar, payment_url


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        ("4441 1111 2222 3333", "<code>4441 1111 2222 3333</code>"),
        ("4441111122223333", "<code>4441111122223333</code>"),
        ("Карта: 5375-4141-0000-1234, Андрій", "Карта: <code>5375-4141-0000-1234</code>, Андрій"),
        ("телефон 0671234567", "телефон 0671234567"),  # 10 цифр — не картка
        ("<b>4441111122223333</b>", "&lt;b&gt;<code>4441111122223333</code>&lt;/b&gt;"),
    ],
)
def test_card_numbers_become_copyable(details: str, expected: str) -> None:
    assert format_details_html(details) == expected


def test_digits_inside_urls_are_not_wrapped() -> None:
    details = "https://send.monobank.ua/jar/4441111122223333 або 4441 1111 2222 3333"
    html = format_details_html(details)
    assert html.startswith("https://send.monobank.ua/jar/4441111122223333 ")
    assert html.endswith("<code>4441 1111 2222 3333</code>")


def test_url_html_is_escaped() -> None:
    assert format_details_html('https://x.ua/?a=1&b="2"') == "https://x.ua/?a=1&amp;b=&quot;2&quot;"


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        ("Банка: https://send.monobank.ua/jar/AbC123.", "https://send.monobank.ua/jar/AbC123"),
        ("(https://pay.example.com/x)", "https://pay.example.com/x"),
        ("картка 4441 1111 2222 3333", None),
        ("javascript:alert(1)", None),
        ("http://localhost", None),
        ("перша http://a.ua/1 друга https://b.ua/2", "http://a.ua/1"),
    ],
)
def test_payment_url(details: str, expected: str | None) -> None:
    assert payment_url(details) == expected


def test_is_monobank_jar() -> None:
    assert is_monobank_jar("https://send.monobank.ua/jar/AbC123")
    assert not is_monobank_jar("https://example.com/send.monobank.ua")


UA_IBAN_SPACED = "UA21 3223 1300 0002 6007 2335 6600 1"
UA_IBAN = "UA213223130000026007233566001"


@pytest.mark.parametrize("iban", [UA_IBAN_SPACED, UA_IBAN])
def test_ukrainian_iban_is_copied_whole(iban: str) -> None:
    assert (
        format_details_html(f"IBAN: {iban}, ФОП Андрій") == f"IBAN: <code>{iban}</code>, ФОП Андрій"
    )


@pytest.mark.parametrize(
    "details",
    [
        "3223 1300 0002 6007 2335 6600 1",  # 23 цифри без UA — не картка й не IBAN
        "12345678901234567890123",
        "acc 1234 5678 9012 3456 7",  # 17 цифр із хвостом: не обрізати частину
    ],
)
def test_long_digit_runs_are_not_partially_wrapped(details: str) -> None:
    html = format_details_html(details)
    assert "<code>" not in html or (html.count("<code>") == 1 and "</code>" in html)
    # Головне: ніколи не обгортати лише частину суцільного ряду цифр
    if "<code>" in html:
        inner = html.split("<code>")[1].split("</code>")[0]
        assert inner.replace(" ", "") == "".join(ch for ch in details if ch.isdigit())
