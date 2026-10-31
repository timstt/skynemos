"""Календар списань. Чисті функції: усі дати рахуються в часовому поясі збору (Europe/Kyiv).

Термінологія:
* period — перше число місяця, за який платять (`date(2026, 2, 1)`);
* billing date — реальний день списання в цьому місяці (31 → 28/29 у лютому);
* billing moment — billing date о `hour`:00 за місцевим часом; з цього моменту
  платіж за період «настав».
"""

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

REMINDER_OFFSETS_DAYS: tuple[int, ...] = (2, 5)
MAX_REMINDERS_PER_PERIOD = 3
# Скільки останніх періодів максимум «доганяти» після простою бота
MAX_CATCHUP_PERIODS = 3


def ensure_aware(dt: datetime) -> datetime:
    """SQLite повертає naive datetime; вважаємо такі значення UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def to_period(day: date) -> date:
    return day.replace(day=1)


def add_months(period: date, months: int) -> date:
    index = period.year * 12 + (period.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def billing_date(period: date, billing_day: int) -> date:
    """День списання в місяці `period`; 29–31 у коротших місяцях → останній день."""
    last_day = calendar.monthrange(period.year, period.month)[1]
    return date(period.year, period.month, min(billing_day, last_day))


def billing_moment(period: date, billing_day: int, tz: ZoneInfo, hour: int) -> datetime:
    return datetime.combine(billing_date(period, billing_day), time(hour), tzinfo=tz)


def current_period(now: datetime, tz: ZoneInfo) -> date:
    return to_period(ensure_aware(now).astimezone(tz).date())


def latest_due_period(now: datetime, billing_day: int, tz: ZoneInfo, hour: int) -> date:
    """Останній період, чий момент списання вже настав."""
    now = ensure_aware(now)
    period = current_period(now, tz)
    if now < billing_moment(period, billing_day, tz, hour):
        period = add_months(period, -1)
    return period


def due_periods(
    now: datetime,
    billing_day: int,
    tz: ZoneInfo,
    hour: int,
    *,
    not_before: datetime,
    limit: int = MAX_CATCHUP_PERIODS,
) -> list[date]:
    """Періоди (за зростанням), чий момент списання в проміжку [not_before; now].

    Зазвичай це один період. Більше — лише після простою бота, але не більше `limit`.
    """
    not_before = ensure_aware(not_before)
    periods: list[date] = []
    period = latest_due_period(now, billing_day, tz, hour)
    while len(periods) < limit and billing_moment(period, billing_day, tz, hour) >= not_before:
        periods.append(period)
        period = add_months(period, -1)
    return sorted(periods)


def reminders_due(moment: datetime, now: datetime) -> int:
    """Скільки нагадувань «мало б» бути надіслано на цей момент (за REMINDER_OFFSETS_DAYS)."""
    now = ensure_aware(now)
    count = sum(1 for days in REMINDER_OFFSETS_DAYS if now >= moment + timedelta(days=days))
    return min(count, MAX_REMINDERS_PER_PERIOD)


def should_remind(
    moment: datetime,
    now: datetime,
    reminders_sent: int,
    last_reminded_at: datetime | None,
    tz: ZoneInfo,
) -> bool:
    """Чи треба зараз надіслати нагадування про неоплачений платіж.

    * нагадування настає через 2 і 5 днів після списання;
    * не більше MAX_REMINDERS_PER_PERIOD за період;
    * не частіше одного разу на день (захист від повторних запусків джоби).
    Пропущені під час простою нагадування не «накопичуються»: надсилається одне.
    """
    if reminders_sent >= MAX_REMINDERS_PER_PERIOD:
        return False
    if reminders_sent >= reminders_due(moment, now):
        return False
    if last_reminded_at is not None:
        last_local = ensure_aware(last_reminded_at).astimezone(tz).date()
        if last_local == ensure_aware(now).astimezone(tz).date():
            return False
    return True
