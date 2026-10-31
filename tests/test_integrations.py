from typing import Any

import pytest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot import integrations


def test_memory_storage_without_redis_url() -> None:
    assert isinstance(integrations.create_storage(None), MemoryStorage)
    assert isinstance(integrations.create_storage(""), MemoryStorage)


async def test_redis_storage_from_url_does_not_connect_eagerly() -> None:
    storage = integrations.create_storage("redis://localhost:6379/0")
    assert isinstance(storage, RedisStorage)
    await storage.close()


def test_sentry_disabled_without_dsn() -> None:
    assert integrations.setup_sentry(None) is False


def test_sentry_enabled_with_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentry_sdk

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    assert integrations.setup_sentry("https://key@o0.ingest.sentry.io/1", "staging") is True
    assert calls == [
        {
            "dsn": "https://key@o0.ingest.sentry.io/1",
            "environment": "staging",
            "traces_sample_rate": 0.0,
            "send_default_pii": False,
        }
    ]
