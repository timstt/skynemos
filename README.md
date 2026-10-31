# Скинемось 💸

[![CI](https://github.com/<your-username>/skynemos/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-username>/skynemos/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)

Telegram-бот, який автоматизує щомісячні збори грошей за спільні регулярні витрати:
YouTube/Spotify Family, Netflix, інтернет у квартирі, комуналка із сусідами.

## Проблема і рішення

Одна людина платить за спільну підписку, а решта мають щомісяця скидати їй свою частку.
Нагадувати незручно, хтось забуває, і вже за кілька місяців ніхто не пам'ятає, хто скинув,
а хто ні. У Монобанку є «Групові витрати», але вони працюють лише між користувачами mono,
а витрату там треба щоразу додавати вручну.

**Скинемось** бере це на себе. Власник один раз створює збір (назва, сума, день списання,
реквізити) і надсилає друзям посилання. Далі бот щомісяця сам рахує частки, у день списання
надсилає кожному суму з реквізитами й кнопкою «Я скинув ✅», нагадує тим, хто забув,
і показує власнику, хто вже заплатив. Банк не має значення: реквізити довільні (картка,
банка mono, IBAN).

Під капотом це асинхронний бот на aiogram 3 з PostgreSQL, тонкими хендлерами й бізнес-логікою
в сервісах, які тестуються без Telegram. Планувальник ідемпотентний: перезапуск, подвійний
запуск чи простій бота не створюють дублів і не гублять повідомлень.

## Можливості

- **Створення збору** покроковим діалогом (`/new`) з валідацією й підтвердженням.
- **Посилання-запрошення** (`t.me/<bot>?start=join_…`): учасник бачить опис і свою частку
  до приєднання. Максимум 10 учасників, власник не може приєднатися до власного збору.
- **Справедливий розподіл:** суми в копійках, порівну або **за вагами** (родина з двох = 2
  частки), залишок у копійках — власнику або першому учаснику. Можна задати частку вручну.
- **Щомісяця, щороку або разово:** YouTube Family, річний Spotify чи подарунок на день народження.
- **Цикл оплати:** у день списання о 10:00 (Europe/Kyiv) кожен учасник отримує суму,
  реквізити (номер картки копіюється дотиком), кнопку «💳 Відкрити банку» та «Я скинув ✅».
  Власник підтверджує або відповідає «Не бачу оплати»; коли скинули всі — «🎉 Усі скинули!».
- **Нагадування** через 2 і 5 днів (не більше 3 за місяць), кнопка «⏰ Нагадай завтра»
  і накопичений борг («ще не оплачено: вересень, жовтень — разом 300 грн»).
- **`/status`** і підсумок власнику на 3-й день: ✅ підтверджено · ⏳ чекає · ❌ не скинуто.
- **Керування збором:** сума, дата, реквізити, частки й ваги, співвласник, видалення учасника,
  пауза, видалення збору, ручна позначка оплати (готівка). Кожна дія, що зачіпає учасника,
  надсилає йому сповіщення; імена клікабельні й відкривають чат з людиною.
- **Співвласник** може підтверджувати оплати й бачити статус, але не керує збором.
- **Для учасника:** історія платежів, борг і вихід зі збору.
- **Граничні випадки:** день 29–31 у коротких місяцях, високосний лютий, учасник заблокував
  бота, зміна складу посеред місяця, пропущені запуски після простою.

## Скріншоти

| Створення збору | Запит «скинь» | Підтвердження власником | `/status` |
|---|---|---|---|
| ![](docs/screenshots/new.png) | ![](docs/screenshots/request.png) | ![](docs/screenshots/confirm.png) | ![](docs/screenshots/status.png) |

> Скріншоти-плейсхолдери: додай свої в `docs/screenshots/`.

## Швидкий старт (Docker)

1. **Отримай токен бота.** Напиши [@BotFather](https://t.me/BotFather) команду `/newbot`,
   вкажи назву й username (має закінчуватися на `bot`). BotFather надішле токен виду
   `123456789:AAH...`.
2. **Налаштуй оточення:**
   ```bash
   cp .env.example .env
   # відкрий .env і встав токен у BOT_TOKEN
   ```
3. **Запусти бота і PostgreSQL:**
   ```bash
   docker compose up --build
   ```
   Міграції застосовуються автоматично при старті контейнера. У логах має з'явитися
   `Бот запускається (polling)`.
4. Напиши своєму боту `/start` у Telegram.

### Змінні оточення

| Змінна | За замовчуванням | Опис |
|---|---|---|
| `BOT_TOKEN` | — | Токен від @BotFather (обов'язково) |
| `DATABASE_URL` | `postgresql+asyncpg://skynemos:skynemos@localhost:5432/skynemos` | Підключення до БД (у Docker перевизначається) |
| `TIMEZONE` | `Europe/Kyiv` | Часовий пояс розкладу |
| `BILLING_HOUR` | `10` | Година, о котрій у день списання створюються платежі |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `REDIS_URL` | — | Опційно: FSM-стан у Redis, діалог переживає перезапуск (у Docker задано) |
| `SENTRY_DSN` | — | Опційно: звіти про помилки в Sentry |

Хибні значення (формат токена, невідомий пояс тощо) зупиняють бота на старті з зрозумілою помилкою.

## Локальна розробка

```bash
uv venv --python 3.12 .venv          # або python -m venv .venv
uv pip install -e ".[dev]"           # або pip install -e ".[dev]"
docker compose up -d db              # лише PostgreSQL
alembic upgrade head
python -m bot
```

Тести й лінтер:

```bash
pytest                               # ~410 тестів, SQLite in-memory, без Telegram і Postgres
pytest --cov                         # з покриттям (~85%)
ruff check . && ruff format --check .
mypy                                 # strict
```

Ті самі тести на справжньому PostgreSQL (так їх запускає CI):

```bash
docker compose up -d db
TEST_DATABASE_URL=postgresql+asyncpg://skynemos:skynemos@localhost:5432/skynemos pytest
```

Міграції після зміни моделей:

```bash
alembic revision --autogenerate -m "опис змін"
alembic upgrade head --sql           # подивитися SQL без підключення до БД
```

## Архітектура

```mermaid
flowchart LR
    TG[Telegram] -->|updates| H[handlers<br/>aiogram routers]
    H --> M[middlewares<br/>сесія БД, користувач]
    H --> S[services<br/>бізнес-логіка]
    J[scheduler<br/>щогодинна джоба] --> S
    S --> R[repositories]
    R --> DB[(PostgreSQL)]
    H --> N[notifier]
    J --> N
    N -->|send_message| TG
```

**Принцип:** хендлери тонкі й лише викликають сервіси. Сервіси не знають про aiogram
і тестуються без Telegram; репозиторії відповідають лише за доступ до даних і не комітять:
одна дія користувача = одна транзакція (її відкриває middleware).

```
bot/
├── __main__.py        # точка входу: бот, диспетчер, планувальник
├── config.py          # pydantic-settings з валідацією
├── texts.py           # усі тексти українською
├── middlewares.py     # сесія БД на апдейт, upsert користувача
├── notifier.py        # надсилання з обробкою блокувань і флуд-контролю
├── db/                # моделі, сесія, репозиторії
├── services/          # розподіл часток, календар, платежі, збори
├── handlers/          # start, create, manage, payments, errors, fallback
├── keyboards/         # inline-клавіатури та CallbackData
├── states/            # FSM-стани
└── scheduler/         # BillingJob + APScheduler
migrations/            # Alembic
tests/                 # pytest + pytest-asyncio
```

### Модель даних

```mermaid
erDiagram
    users ||--o{ pools : owns
    users ||--o{ members : "is"
    pools ||--o{ members : has
    members ||--o{ payments : owes

    users {
        int id PK
        bigint telegram_id UK
        string username
        string first_name
        bool is_reachable
        timestamptz created_at
    }
    pools {
        int id PK
        int owner_id FK
        string title
        int total_amount_kop
        string frequency "monthly | yearly | once"
        smallint billing_day "1-31"
        smallint billing_month "для yearly / once"
        smallint billing_year "для once"
        bool include_owner
        int owner_share_kop
        smallint owner_weight
        text payment_details
        string invite_token UK
        bool is_paused
        timestamptz active_since
        date digest_period
        timestamptz created_at
    }
    members {
        int id PK
        int pool_id FK
        int user_id FK
        int share_kop
        bool share_is_custom
        smallint weight
        bool is_admin
        bool is_active
        timestamptz joined_at
    }
    payments {
        int id PK
        int member_id FK
        date period "перше число місяця"
        int amount_kop
        string status "pending | claimed | paid"
        timestamptz notified_at
        timestamptz snoozed_until
        smallint reminders_sent
        timestamptz last_reminded_at
        timestamptz claimed_at
        timestamptz paid_at
    }
```

Унікальні обмеження: `users.telegram_id`, `pools.invite_token`, `members(pool_id, user_id)`,
`payments(member_id, period)`.

### Статуси платежу

```mermaid
stateDiagram-v2
    [*] --> pending: день списання
    pending --> claimed: учасник «Я скинув ✅»
    claimed --> paid: власник «Підтвердити»
    claimed --> pending: власник «Не бачу оплати»
    pending --> paid: власник вручну / банк (фаза 2)
    paid --> [*]
```

## Інженерні рішення

- **Гроші в копійках (`int`).** Жодних float; сума часток завжди дорівнює загальній сумі
  (перевірено параметризованими тестами).
- **Ідемпотентний планувальник.** Одна джоба щогодини проходить усі збори. Дублі неможливі
  завдяки унікальному індексу `(member_id, period)`; створення платежу й надсилання
  повідомлення розділені (`notified_at`), тому падіння посеред циклу нічого не губить.
- **Пропущені запуски.** Після простою бот при старті створює платежі, що мали з'явитися
  (не більше ніж за 3 останні місяці), і не шле запит і нагадування одне за одним.
- **Час.** Усі дати рахуються в `Europe/Kyiv`, у БД — `timestamptz` в UTC. Окремий тип
  колонки нормалізує час, щоб SQLite у тестах поводився як Postgres.
- **Заблокований бот.** `TelegramForbiddenError` → користувач позначається недоступним,
  власник отримує одне попередження; коли учасник повертається, пропущений запит
  надсилається автоматично.

Повний список рішень і їхніх причин — у [DECISIONS.md](DECISIONS.md).

## Roadmap

- **Фаза 2: автопідтвердження через monobank Personal API.** Власник один раз вводить
  персональний токен, бот реєструє вебхук на нові транзакції й за сумою та іменем
  відправника сам переводить платіж у `paid`. Точка входу вже є:
  `PaymentService.mark_paid_automatically(..., via=PaidVia.BANK)`. Токени зберігатимуться
  лише зашифрованими; перед реалізацією треба звірити актуальну документацію API.
- **Інші валюти** (USD/EUR для закордонних підписок).
- **Вебпанель** для власника: історія, статистика, експорт.
- **Деплой 24/7** на сервер і **webhook замість polling**.
- **Демо-GIF** у README.

## Стек

Python 3.12 · aiogram 3 · PostgreSQL 16 · SQLAlchemy 2.0 (async) + asyncpg · Alembic ·
APScheduler · pydantic-settings · pytest + pytest-asyncio · ruff · Docker Compose
