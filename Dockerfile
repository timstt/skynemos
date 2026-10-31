FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot ./bot
RUN pip install ".[redis,sentry]"

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home appuser
USER appuser

# Спершу міграції, потім бот
CMD ["sh", "-c", "alembic upgrade head && python -m bot"]
