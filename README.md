# Skynemos 💸

[![CI](https://github.com/timstt/skynemos/actions/workflows/ci.yml/badge.svg)](https://github.com/timstt/skynemos/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A Telegram bot that automates recurring money collection for shared expenses:
YouTube/Spotify Family, Netflix, home internet, utilities with flatmates.
*«Скинемось»* is Ukrainian for "let's chip in"; the bot's interface is in Ukrainian.

## Problem and solution

One person pays for a shared subscription, and everyone else has to send them their part
every month. Reminding friends is awkward, someone always forgets, and after a few months
nobody remembers who has paid. Monobank's "Group expenses" only works between monobank users,
and the expense has to be added by hand every time.

**Skynemos** takes this over. The owner creates a collection once (title, amount, billing day,
payment details) and shares an invite link. From then on the bot splits the amount, sends every
member their share with payment details and an "I sent it ✅" button on the billing day, reminds
those who forgot and shows the owner who has paid. It works with any bank: payment details are
free text (card number, IBAN, monobank jar link).

Under the hood it is an async bot on aiogram 3 and PostgreSQL with thin handlers and business
logic in services that are tested without Telegram. The scheduler is idempotent: restarts,
double runs or downtime never create duplicates or lose messages.

## Features

- **Create a collection** with a step-by-step dialog (`/new`), validation and a confirmation screen.
- **Invite links** (`t.me/<bot>?start=join_…`): members see the description and their future share
  before joining. Up to 10 members; the owner can't join their own collection.
- **Fair split:** amounts are stored in kopecks; equal or **weighted** shares (a family of two
  pays 2 shares), leftover kopecks go to the owner or the first member. Custom shares are supported.
- **Monthly, yearly or one-time:** YouTube Family, a yearly Spotify plan or a birthday gift.
- **Payment cycle:** at 10:00 (Europe/Kyiv) on the billing day every member gets the amount, payment
  details (card numbers and IBANs copy with one tap), an "Open jar" button and "I sent it ✅".
  The owner confirms or answers "I don't see the payment"; once everyone has paid — "🎉 Everyone paid!".
- **Reminders** 2 and 5 days after billing (max 3 per period), a "⏰ Remind me tomorrow" button and
  accumulated debt ("unpaid: September, October — 300 UAH in total").
- **`/status`** and a day-3 digest for the owner: ✅ confirmed · ⏳ waiting · ❌ not paid.
- **Collection management:** title, amount, date, payment details, shares and weights, co-owner,
  removing members, pause, deletion, marking a payment as paid manually (cash). Every action that
  affects a member notifies them; names are clickable and open a chat with the person.
- **Co-owner** can confirm payments and see the status, but can't manage the collection.
- **For members:** payment history, outstanding debt and leaving a collection.
- **Edge cases:** billing days 29–31 in short months, leap years, a member blocking the bot,
  membership changes mid-month, missed runs after downtime.

## Quick start (Docker)

1. **Get a bot token.** Send `/newbot` to [@BotFather](https://t.me/BotFather), choose a name and
   a username ending in `bot`. BotFather replies with a token like `123456789:AAH...`.
2. **Configure the environment:**
   ```bash
   cp .env.example .env
   # open .env and paste the token into BOT_TOKEN
   ```
3. **Start the bot, PostgreSQL and Redis:**
   ```bash
   docker compose up --build
   ```
   Migrations run automatically when the container starts. The log should show
   `Бот запускається (polling)` ("bot is starting").
4. Send `/start` to your bot in Telegram.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | Token from @BotFather (required) |
| `DATABASE_URL` | `postgresql+asyncpg://skynemos:skynemos@localhost:5432/skynemos` | Database connection (overridden in Docker) |
| `TIMEZONE` | `Europe/Kyiv` | Time zone of the schedule |
| `BILLING_HOUR` | `10` | Hour at which payments are created on the billing day |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `REDIS_URL` | — | Optional: keep dialog state in Redis so it survives restarts (set in Docker) |
| `SENTRY_DSN` | — | Optional: report errors to Sentry |

Invalid values (token format, unknown time zone, etc.) stop the bot at startup with a clear error.

## Local development

```bash
uv venv --python 3.12 .venv          # or: python -m venv .venv
uv pip install -e ".[dev]"           # or: pip install -e ".[dev]"
docker compose up -d db              # PostgreSQL only
alembic upgrade head
python -m bot
```

For a quick try without Docker, SQLite works too: `DATABASE_URL=sqlite+aiosqlite:///skynemos.db`.

Tests, linters and type checks:

```bash
pytest                               # ~420 tests, in-memory SQLite, no Telegram or Postgres needed
pytest --cov                         # with coverage (~85%)
ruff check . && ruff format --check .
mypy                                 # strict mode
```

The same tests against a real PostgreSQL (this is how CI runs them):

```bash
docker compose up -d db
TEST_DATABASE_URL=postgresql+asyncpg://skynemos:skynemos@localhost:5432/skynemos pytest
```

Migrations after changing the models:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head --sql           # preview the SQL without a database connection
```

## Architecture

```mermaid
flowchart LR
    TG[Telegram] -->|updates| H[handlers<br/>aiogram routers]
    H --> M[middlewares<br/>DB session, user]
    H --> S[services<br/>business logic]
    J[scheduler<br/>hourly job] --> S
    S --> R[repositories]
    R --> DB[(PostgreSQL)]
    H --> N[notifier]
    J --> N
    N -->|send_message| TG
```

**Principle:** handlers are thin and only call services. Services know nothing about aiogram and
are tested without Telegram; repositories only access data and never commit: one user action is
one transaction, opened by a middleware.

```
bot/
├── __main__.py        # entry point: bot, dispatcher, scheduler
├── config.py          # pydantic-settings with validation
├── texts.py           # all bot texts (Ukrainian)
├── middlewares.py     # DB session per update, user upsert
├── notifier.py        # sending with handling of blocked users and flood control
├── integrations.py    # optional Redis FSM storage and Sentry
├── db/                # models, session, repositories
├── services/          # share split, billing calendar, payments, collections
├── handlers/          # start, create, manage, payments, errors, fallback
├── keyboards/         # inline keyboards and CallbackData
├── states/            # FSM states
└── scheduler/         # BillingJob + APScheduler
migrations/            # Alembic
tests/                 # pytest + pytest-asyncio
```

### Data model

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
        smallint billing_month "yearly / once"
        smallint billing_year "once"
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
        date period "first day of the month"
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

Unique constraints: `users.telegram_id`, `pools.invite_token`, `members(pool_id, user_id)`,
`payments(member_id, period)`.

### Payment statuses

```mermaid
stateDiagram-v2
    [*] --> pending: billing day
    pending --> claimed: member "I sent it ✅"
    claimed --> paid: owner "Confirm"
    claimed --> pending: owner "I don't see it"
    pending --> paid: owner manually / bank (phase 2)
    paid --> [*]
```

## Engineering decisions

- **Money in kopecks (`int`).** No floats; the sum of shares always equals the total
  (checked by parametrized tests, including weighted shares).
- **Idempotent scheduler.** One hourly job walks all collections. Duplicates are impossible thanks
  to the unique index `(member_id, period)`; creating a payment and sending the message are
  separate steps (`notified_at`), so a crash mid-run loses nothing.
- **Missed runs.** After downtime the bot creates the payments that should have appeared
  (for at most the last 3 periods) and never sends a request and a reminder back to back.
- **Time.** All dates are computed in `Europe/Kyiv` and stored as UTC `timestamptz`. A custom column
  type normalises time so SQLite in tests behaves like PostgreSQL.
- **Blocked bot.** `TelegramForbiddenError` marks the user as unreachable and the owner gets a single
  warning; when the member comes back, the missed request is delivered automatically.
- **Tested on both databases.** CI runs the suite on SQLite and on PostgreSQL 16, plus a check that
  the migration chain matches the models.

All decisions and their reasons are documented (in Ukrainian) in [DECISIONS.md](DECISIONS.md).

## Roadmap

- **Phase 2: automatic confirmation via the monobank Personal API.** The owner enters a personal
  token once, the bot registers a webhook for new transactions and marks a payment as `paid` by
  matching the amount and the sender's name. The entry point already exists:
  `PaymentService.mark_paid_automatically(..., via=PaidVia.BANK)`. Tokens will be stored encrypted
  only; the current API documentation must be checked before implementing it.
- **Other currencies** (USD/EUR for subscriptions paid abroad).
- **Web dashboard** for owners: history, statistics, export.
- **24/7 deployment** on a server and **webhooks instead of polling**.

## Tech stack

Python 3.12 · aiogram 3 · PostgreSQL 16 · SQLAlchemy 2.0 (async) + asyncpg · Alembic ·
APScheduler · pydantic-settings · Redis (optional) · Sentry (optional) ·
pytest + pytest-asyncio · mypy · ruff · Docker Compose · GitHub Actions

## License

[MIT](LICENSE) © 2026 timstt
