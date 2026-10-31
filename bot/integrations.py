"""Опційні інтеграції: Redis для FSM-стану та Sentry для звітів про помилки.

Обидві вмикаються змінними оточення й потребують додаткових пакетів:
`pip install ".[redis]"` / `pip install ".[sentry]"`.
"""

import logging

from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

logger = logging.getLogger(__name__)


def create_storage(redis_url: str | None) -> BaseStorage:
    """FSM-сховище: Redis, якщо задано REDIS_URL (діалоги переживають перезапуск).

    Інакше — пам'ять процесу.
    """
    if not redis_url:
        return MemoryStorage()
    try:
        from aiogram.fsm.storage.redis import RedisStorage
    except ImportError as exc:  # pragma: no cover - залежить від встановлених extras
        raise RuntimeError(
            'REDIS_URL задано, але пакет redis не встановлено: pip install ".[redis]"'
        ) from exc
    logger.info("FSM storage: Redis")
    return RedisStorage.from_url(redis_url)


def setup_sentry(dsn: str | None, environment: str = "production") -> bool:
    """Вмикає Sentry, якщо задано SENTRY_DSN. Помилки з logger.error/exception стають подіями."""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError as exc:  # pragma: no cover - залежить від встановлених extras
        raise RuntimeError(
            'SENTRY_DSN задано, але пакет sentry-sdk не встановлено: pip install ".[sentry]"'
        ) from exc
    # Без трасування продуктивності й без персональних даних користувачів
    sentry_sdk.init(
        dsn=dsn, environment=environment, traces_sample_rate=0.0, send_default_pii=False
    )
    logger.info("Sentry enabled")
    return True
