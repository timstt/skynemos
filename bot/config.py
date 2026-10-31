from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфігурація застосунку, читається зі змінних оточення або `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    database_url: str = "postgresql+asyncpg://skynemos:skynemos@localhost:5432/skynemos"
    timezone: str = "Europe/Kyiv"
    log_level: str = "INFO"
    # Година (за `timezone`), о котрій створюються платежі в день списання
    billing_hour: int = Field(default=10, ge=0, le=23)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
