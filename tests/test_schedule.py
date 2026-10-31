from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bot.db.models import Frequency
from bot.services.billing import Schedule

KYIV = ZoneInfo("Europe/Kyiv")
H = 10


def kyiv(*args: int) -> datetime:
    return datetime(*args, tzinfo=KYIV)  # type: ignore[misc]


MONTHLY = Schedule(5)
YEARLY = Schedule(5, Frequency.YEARLY, billing_month=3)
ONCE = Schedule(20, Frequency.ONCE, billing_month=12, billing_year=2026)


def test_monthly_matches_legacy_behaviour() -> None:
    assert MONTHLY.latest_due_period(kyiv(2026, 11, 5, 10), KYIV, H) == date(2026, 11, 1)
    assert MONTHLY.next_period(date(2026, 12, 1)) == date(2027, 1, 1)
    assert MONTHLY.due_periods(kyiv(2026, 11, 6), KYIV, H, not_before=kyiv(2026, 9, 1)) == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]


def test_yearly_latest_and_next() -> None:
    assert YEARLY.latest_due_period(kyiv(2026, 3, 5, 9), KYIV, H) == date(2025, 3, 1)
    assert YEARLY.latest_due_period(kyiv(2026, 3, 5, 10), KYIV, H) == date(2026, 3, 1)
    assert YEARLY.latest_due_period(kyiv(2026, 11, 1), KYIV, H) == date(2026, 3, 1)
    assert YEARLY.next_period(date(2026, 3, 1)) == date(2027, 3, 1)
    assert YEARLY.upcoming_period(kyiv(2026, 11, 1), KYIV, H) == date(2027, 3, 1)


def test_yearly_catch_up_steps_by_year() -> None:
    periods = YEARLY.due_periods(kyiv(2026, 4, 1), KYIV, H, not_before=kyiv(2024, 1, 1))
    assert periods == [date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)]
    # Створено після березневого списання — до наступного березня нічого
    assert YEARLY.due_periods(kyiv(2026, 11, 1), KYIV, H, not_before=kyiv(2026, 4, 1)) == []


def test_yearly_feb_29_in_non_leap_year() -> None:
    leap_day = Schedule(29, Frequency.YEARLY, billing_month=2)
    assert leap_day.moment(date(2027, 2, 1), KYIV, H) == kyiv(2027, 2, 28, 10)
    assert leap_day.moment(date(2028, 2, 1), KYIV, H) == kyiv(2028, 2, 29, 10)


def test_once_is_due_exactly_once() -> None:
    before = kyiv(2026, 12, 20, 9)
    after = kyiv(2026, 12, 20, 10)
    assert ONCE.latest_due_period(before, KYIV, H) is None
    assert ONCE.upcoming_period(before, KYIV, H) == date(2026, 12, 1)
    assert ONCE.latest_due_period(after, KYIV, H) == date(2026, 12, 1)
    assert ONCE.upcoming_period(after + timedelta(days=400), KYIV, H) is None
    assert ONCE.next_period(date(2026, 12, 1)) is None
    # Скільки б не минуло часу — лише один період
    much_later = after + timedelta(days=1000)
    assert ONCE.due_periods(much_later, KYIV, H, not_before=kyiv(2026, 1, 1)) == [date(2026, 12, 1)]
    assert ONCE.due_periods(before, KYIV, H, not_before=kyiv(2026, 1, 1)) == []
