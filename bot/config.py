import re
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class DatabaseSettings(BaseSettings):
    """Лише підключення до БД: потрібне Alembic, якому токен бота ні до чого."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://skynemos:skynemos@localhost:5432/skynemos"


class Settings(DatabaseSettings):
    """Конфігурація застосунку, читається зі змінних оточення або `.env`.

    Хибні значення зупиняють бота на старті з зрозумілою помилкою.
    """

    bot_token: SecretStr
    timezone: str = "Europe/Kyiv"
    log_level: str = "INFO"
    # Година (за `timezone`), о котрій створюються платежі в день списання
    billing_hour: int = Field(default=10, ge=0, le=23)

    @field_validator("bot_token")
    @classmethod
    def _check_token(cls, value: SecretStr) -> SecretStr:
        if not _TOKEN_RE.fullmatch(value.get_secret_value()):
            raise ValueError("BOT_TOKEN має формат 123456789:AA... (отримай його в @BotFather)")
        return value

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Невідомий часовий пояс: {value!r}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL має бути одним із {sorted(_LOG_LEVELS)}")
        return level

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
