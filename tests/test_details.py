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
