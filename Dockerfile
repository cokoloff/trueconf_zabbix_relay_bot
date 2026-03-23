FROM python:3.11-slim

LABEL maintainer="your-email@domain.ru"
LABEL description="TrueConf Zabbix Relay Bot"
LABEL version="10.1"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Moscow

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование только requirements для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование всего кода
COPY bot.py .
COPY config.py .

# Создание директорий
RUN mkdir -p /app/data /app/logs

# Создание непривилегированного пользователя
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app

USER botuser

EXPOSE 8080

CMD ["python", "bot.py"]