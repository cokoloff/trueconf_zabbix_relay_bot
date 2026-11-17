# syntax=docker/dockerfile:1
# ============================================================================
# TrueConf Zabbix Relay Bot
# ============================================================================
FROM python:3.12-slim AS base

# Не создавать .pyc, не буферизовать stdout — логи уходят сразу
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libmagic нужен библиотеке python-magic (определение типа файлов в SDK),
# tzdata — для корректного местного времени в логах
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 tzdata \
 && rm -rf /var/lib/apt/lists/*

# Зависимости отдельным слоем: пересобираются только при изменении requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY config.py bot_multy.py check_stack.py healthcheck.py ./
COPY tcbot ./tcbot

# Непривилегированный пользователь
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin tcbot \
 && mkdir -p /app/logs /app/data \
 && chown -R tcbot:tcbot /app

USER tcbot

# Состояние, токен и очередь живут в томе
VOLUME ["/app/data"]

ENV LOG_DIR=/app/logs \
    STATE_FILE=/app/data/bot_state.json \
    TOKEN_FILE=/app/data/bot_token.json \
    OUTBOX_FILE=/app/data/bot_outbox.json \
    LOCAL_ADMIN_PASSWORD_FILE=/app/data/local-admin-initial-password.txt \
    WEB_SERVER_HOST=0.0.0.0 \
    WEB_SERVER_PORT=8080 \
    TZ=Europe/Moscow

EXPOSE 8080

# Живость процесса (готовность бота проверяется через /ready)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "bot_multy.py"]
