from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from bot.config import DatabaseSettings, Settings

TOKEN = "123456789:AAH-valid_token_value_1234567890"


def make(**env: str) -> Settings:
    return Settings(_env_file=None, **{"bot_token": TOKEN, **env})  # type: ignore[arg-type]


def test_settings_defaults() -> None:
    settings = make()

    assert settings.bot_token.get_secret_value() == TOKEN
    assert settings.tz == ZoneInfo("Europe/Kyiv")
    assert settings.billing_hour == 10
    assert settings.log_level == "INFO"
    # Токен не потрапляє в repr/логи
    assert TOKEN not in repr(settings)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("BILLING_HOUR", "9")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (settings.log_level, settings.billing_hour) == ("DEBUG", 9)


def test_settings_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bot_token", "123:abc"),
        ("bot_token", "not-a-token"),
        ("timezone", "Mars/Olympus"),
        ("log_level", "LOUD"),
        ("billing_hour", "24"),
    ],
)
def test_invalid_settings_fail_fast(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_database_settings_do_not_need_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    assert DatabaseSettings(_env_file=None).database_url.startswith("postgresql+asyncpg")  # type: ignore[call-arg]
