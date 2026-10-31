from zoneinfo import ZoneInfo

import pytest

from bot.config import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.bot_token.get_secret_value() == "123:abc"
    assert settings.tz == ZoneInfo("Europe/Kyiv")
    assert settings.billing_hour == 10
    # Токен не потрапляє в repr/логи
    assert "123:abc" not in repr(settings)


def test_settings_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]
