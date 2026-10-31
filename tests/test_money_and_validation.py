import pytest

from bot.services.errors import DomainError, ErrorCode
from bot.services.money import format_money, parse_amount
from bot.services.validation import (
    validate_billing_day,
    validate_payment_details,
    validate_title,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("300", 30_000),
        ("60,50", 6_050),
        ("60.5", 6_050),
        ("0,01", 1),
        (" 1 200 грн ", 120_000),
        ("1 200", 120_000),
        ("250₴", 25_000),
        ("100000", 10_000_000),
    ],
)
def test_parse_amount_valid(raw: str, expected: int) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "abc", "0", "0,00", "-5", "10,555", "100000,01", "1e3", "12,", ",5"]
)
def test_parse_amount_invalid(raw: str) -> None:
    with pytest.raises(DomainError) as exc:
        parse_amount(raw)
    assert exc.value.code is ErrorCode.INVALID_AMOUNT


def test_parse_amount_allow_zero() -> None:
    assert parse_amount("0", allow_zero=True) == 0


@pytest.mark.parametrize(
    ("kop", "expected"),
    [
        (6_000, "60 грн"),
        (6_050, "60,50 грн"),
        (5, "0,05 грн"),
        (0, "0 грн"),
        (120_000, "1 200 грн"),
        (10_000_000, "100 000 грн"),
    ],
)
def test_format_money(kop: int, expected: str) -> None:
    assert format_money(kop) == expected


def test_validate_title() -> None:
    assert validate_title("  YouTube   Family ") == "YouTube Family"
    assert validate_title("x" * 64) == "x" * 64
    for bad in ("", "   ", "x" * 65):
        with pytest.raises(DomainError):
            validate_title(bad)


@pytest.mark.parametrize("raw", ["1", " 31 ", 15])
def test_validate_billing_day_valid(raw: str | int) -> None:
    assert 1 <= validate_billing_day(raw) <= 31


@pytest.mark.parametrize("raw", ["0", "32", "-1", "п'яте", "5.5", ""])
def test_validate_billing_day_invalid(raw: str) -> None:
    with pytest.raises(DomainError) as exc:
        validate_billing_day(raw)
    assert exc.value.code is ErrorCode.INVALID_BILLING_DAY


def test_validate_payment_details() -> None:
    assert validate_payment_details("  4441 1111  ") == "4441 1111"
    for bad in ("", "  ", "x" * 501):
        with pytest.raises(DomainError):
            validate_payment_details(bad)
