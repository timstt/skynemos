from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot.services.billing import (
    MAX_REMINDERS_PER_PERIOD,
    add_months,
    billing_date,
    billing_moment,
    current_period,
    due_periods,
    ensure_aware,
    latest_due_period,
    reminders_due,
    should_remind,
)

KYIV = ZoneInfo("Europe/Kyiv")
HOUR = 10


def kyiv(*args: int) -> datetime:
    return datetime(*args, tzinfo=KYIV)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("period", "day", "expected"),
    [
        (date(2026, 1, 1), 31, date(2026, 1, 31)),
        (date(2026, 2, 1), 31, date(2026, 2, 28)),
        (date(2026, 2, 1), 30, date(2026, 2, 28)),
        (date(2026, 2, 1), 29, date(2026, 2, 28)),
        (date(2028, 2, 1), 31, date(2028, 2, 29)),  # високосний
        (date(2028, 2, 1), 29, date(2028, 2, 29)),
        (date(2100, 2, 1), 29, date(2100, 2, 28)),  # кратний 100, не високосний
        (date(2000, 2, 1), 30, date(2000, 2, 29)),  # кратний 400, високосний
        (date(2026, 4, 1), 31, date(2026, 4, 30)),
        (date(2026, 4, 1), 30, date(2026, 4, 30)),
        (date(2026, 6, 1), 31, date(2026, 6, 30)),
        (date(2026, 2, 1), 5, date(2026, 2, 5)),
        (date(2026, 12, 1), 1, date(2026, 12, 1)),
    ],
)
def test_billing_date(period: date, day: int, expected: date) -> None:
    assert billing_date(period, day) == expected


@pytest.mark.parametrize(
    ("period", "months", "expected"),
    [
        (date(2026, 12, 1), 1, date(2027, 1, 1)),
        (date(2026, 1, 1), -1, date(2025, 12, 1)),
        (date(2026, 3, 1), -14, date(2025, 1, 1)),
        (date(2026, 3, 1), 0, date(2026, 3, 1)),
    ],
)
def test_add_months(period: date, months: int, expected: date) -> None:
    assert add_months(period, months) == expected


def test_billing_moment_respects_kyiv_dst() -> None:
    winter = billing_moment(date(2026, 1, 1), 5, KYIV, HOUR)
    summer = billing_moment(date(2026, 7, 1), 5, KYIV, HOUR)
    assert winter.astimezone(UTC).hour == 8  # UTC+2
    assert summer.astimezone(UTC).hour == 7  # UTC+3


def test_latest_due_period_switches_at_billing_moment() -> None:
    moment = kyiv(2026, 11, 5, 10)
    assert latest_due_period(moment - timedelta(seconds=1), 5, KYIV, HOUR) == date(2026, 10, 1)
    assert latest_due_period(moment, 5, KYIV, HOUR) == date(2026, 11, 1)
    # Те саме в UTC: 08:00 UTC = 10:00 за Києвом (листопад, UTC+2)
    assert latest_due_period(datetime(2026, 11, 5, 8, tzinfo=UTC), 5, KYIV, HOUR) == date(
        2026, 11, 1
    )


def test_latest_due_period_uses_kyiv_date_not_utc() -> None:
    # 30 листопада 23:30 UTC — це вже 1 грудня 01:30 у Києві, але до 10:00 ще далеко
    now = datetime(2026, 11, 30, 23, 30, tzinfo=UTC)
    assert current_period(now, KYIV) == date(2026, 12, 1)
    assert latest_due_period(now, 1, KYIV, HOUR) == date(2026, 11, 1)


def test_day_31_in_february_is_due_on_28th() -> None:
    assert latest_due_period(kyiv(2026, 2, 28, 10), 31, KYIV, HOUR) == date(2026, 2, 1)
    assert latest_due_period(kyiv(2026, 2, 28, 9), 31, KYIV, HOUR) == date(2026, 1, 1)


def test_due_periods_normal_day() -> None:
    now = kyiv(2026, 11, 5, 10, 30)
    assert due_periods(now, 5, KYIV, HOUR, not_before=kyiv(2026, 1, 1)) == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]  # обмежено MAX_CATCHUP_PERIODS
    assert due_periods(now, 5, KYIV, HOUR, not_before=kyiv(2026, 10, 20)) == [date(2026, 11, 1)]


def test_due_periods_respects_not_before() -> None:
    # Збір створено 10-го, списання 5-го: цього місяця платежу немає
    assert due_periods(kyiv(2026, 11, 20), 5, KYIV, HOUR, not_before=kyiv(2026, 11, 10)) == []
    # Створено рівно в момент списання — період рахується
    assert due_periods(kyiv(2026, 11, 20), 5, KYIV, HOUR, not_before=kyiv(2026, 11, 5, 10)) == [
        date(2026, 11, 1)
    ]


def test_ensure_aware_treats_naive_as_utc() -> None:
    assert ensure_aware(datetime(2026, 1, 1, 12)).tzinfo is UTC


# --- нагадування -------------------------------------------------------------

MOMENT = kyiv(2026, 11, 5, 10)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(0), 0),
        (timedelta(days=2) - timedelta(seconds=1), 0),
        (timedelta(days=2), 1),
        (timedelta(days=4), 1),
        (timedelta(days=5), 2),
        (timedelta(days=30), 2),
    ],
)
def test_reminders_due(offset: timedelta, expected: int) -> None:
    assert reminders_due(MOMENT, MOMENT + offset) == expected


def test_should_remind_schedule() -> None:
    def check(days: float, sent: int, last: datetime | None = None) -> bool:
        return should_remind(MOMENT, MOMENT + timedelta(days=days), sent, last, KYIV)

    assert check(1, 0) is False  # ще рано
    assert check(2, 0) is True  # перше нагадування
    assert check(3, 1) is False  # друге ще не настало
    assert check(5, 1) is True  # друге нагадування
    assert check(10, 2) is False  # більше за розкладом немає
    # Простій: обидва нагадування пропущено, але надсилаємо одне, а не два
    assert check(6, 0) is True


def test_should_remind_not_twice_a_day() -> None:
    now = MOMENT + timedelta(days=5, hours=1)
    earlier_today = MOMENT + timedelta(days=5)
    yesterday = MOMENT + timedelta(days=4)
    assert should_remind(MOMENT, now, 1, earlier_today, KYIV) is False
    assert should_remind(MOMENT, now, 1, yesterday, KYIV) is True


def test_should_remind_caps_per_period() -> None:
    now = MOMENT + timedelta(days=30)
    assert should_remind(MOMENT, now, MAX_REMINDERS_PER_PERIOD, None, KYIV) is False
