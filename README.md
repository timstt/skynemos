# Скинемось 💸

Telegram-бот, який автоматизує щомісячні збори грошей за спільні регулярні витрати:
YouTube/Spotify Family, Netflix, інтернет у квартирі, комуналка із сусідами.

> 🚧 Проєкт у розробці. Повний опис, скріншоти й архітектура з'являться на фінальному етапі.

## Швидкий старт

1. Отримай токен бота в [@BotFather](https://t.me/BotFather): `/newbot` → назва → username.
2. Скопіюй конфіг і встав токен:
   ```bash
   cp .env.example .env
   ```
3. Запусти бота й PostgreSQL:
   ```bash
   docker compose up --build
   ```

## Локальна розробка

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/Scripts/python -m bot      # Windows
# .venv/bin/python -m bot        # Linux/macOS
```

Міграції (потрібен запущений postgres, напр. `docker compose up -d db`):

```bash
alembic upgrade head                              # застосувати
alembic revision --autogenerate -m "опис змін"    # нова міграція після зміни моделей
alembic upgrade head --sql                        # подивитися SQL без підключення
```

Тести та лінтер:

```bash
pytest
ruff check . && ruff format --check .
```
