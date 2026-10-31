FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot ./bot
RUN pip install .

COPY migrations ./migrations

RUN useradd --create-home appuser
USER appuser

CMD ["python", "-m", "bot"]
