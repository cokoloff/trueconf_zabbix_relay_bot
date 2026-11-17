# -*- coding: utf-8 -*-
"""
Настройка логирования.

Схема (совместима с прежней, до v11.1):

    logs/bot.log          — общий поток (root, DEBUG), ротация 50 МБ
    logs/chat.log         — входящие сообщения и события чатов
    logs/delete.log       — удаление сообщений / история инцидентов
    logs/error.log        — ошибки отправки, исключения, сбои соединения
    logs/error_history.log— работа с историей ошибок (сохранение/решение)
    logs/webhook.log      — приём вебхуков от Zabbix/Grafana/Alertmanager

Каналы пишут и в свой файл, и в общий bot.log (propagate=True), как было раньше.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional

LOG_FORMAT = "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Часовой пояс меток в логах.
# В контейнере время обычно UTC, поэтому записи «съезжают» на 3 часа
# относительно московского. По умолчанию приводим к Москве (UTC+3);
# переопределяется через LOG_TZ (+3, -5, 0, ...) или LOG_TZ_NAME=UTC.
LOG_TZ_OFFSET = float(os.getenv("LOG_TZ", "3"))
_TZ_NAME = os.getenv("LOG_TZ_NAME", "").strip()


def _log_timezone() -> timezone:
    """Часовой пояс для меток времени в логах."""
    if _TZ_NAME.upper() in {"UTC", "Z", "GMT"}:
        return timezone.utc
    return timezone(timedelta(hours=LOG_TZ_OFFSET))


class LocalTimeFormatter(logging.Formatter):
    """
    Форматтер с метками в нужном часовом поясе.

    Стандартный logging использует время процесса (time.localtime), а в
    контейнере это UTC — поэтому в логах было на 3 часа меньше, чем на
    самом деле. Здесь время считается явно от LOG_TZ.
    """

    def formatTime(self, record, datefmt: Optional[str] = None) -> str:
        moment = datetime.fromtimestamp(record.created, _log_timezone())
        if datefmt:
            return moment.strftime(datefmt)
        return moment.isoformat(timespec="seconds")

# канал -> имя файла в logs/
CHANNEL_FILES = {
    "chat": "chat.log",
    "delete": "delete.log",
    "error": "error.log",
    "error_history": "error_history.log",
    "webhook": "webhook.log",
}

# Приглушаем шумные библиотеки
QUIET_LOGGERS = {
    "websockets.client": logging.WARNING,
    "websockets.server": logging.WARNING,
    "aiohttp.access": logging.WARNING,
    "asyncio": logging.WARNING,
    "chat_bot": logging.WARNING,       # внутренний логгер SDK (methods/*)
    "httpx2": logging.INFO,           # HTTP-клиент SDK
    "httpcore2": logging.WARNING,     # низкоуровневые трейсы соединений
    "httpcore2.connection": logging.WARNING,
    "httpcore2.http11": logging.WARNING,
    "truststore": logging.WARNING,
}

_channels: Dict[str, logging.Logger] = {}


def _build_formatter() -> logging.Formatter:
    return LocalTimeFormatter(LOG_FORMAT, DATE_FORMAT)


def setup_logging(
    log_dir: str = "logs",
    level: str = "INFO",
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 10,
    sdk_debug: bool = False,
) -> logging.Logger:
    """Инициализирует корневой логгер и каналы. Возвращает логгер приложения."""

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    formatter = _build_formatter()

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    console.setFormatter(formatter)
    root.addHandler(console)

    main_handler = RotatingFileHandler(
        filename=directory / "bot.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    main_handler.setLevel(logging.DEBUG)
    main_handler.setFormatter(formatter)
    root.addHandler(main_handler)

    for name, filename in CHANNEL_FILES.items():
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = True  # дублируем в bot.log, как в прежней схеме

        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        channel_handler = RotatingFileHandler(
            filename=directory / filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        channel_handler.setLevel(logging.DEBUG)
        channel_handler.setFormatter(formatter)
        logger.addHandler(channel_handler)
        _channels[name] = logger

    for name, quiet_level in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(quiet_level)

    _detach_sdk_handlers()

    logging.getLogger("trueconf.client.chatbot").setLevel(
        logging.DEBUG if sdk_debug else logging.INFO
    )
    logging.getLogger("trueconf.dispatcher").setLevel(logging.WARNING)

    return logging.getLogger("bot")


def _detach_sdk_handlers() -> None:
    """
    Убирает собственные StreamHandler-ы библиотеки trueconf.

    trueconf/loggers.py при импорте вешает StreamHandler на логгеры
    trueconf.client.chatbot и trueconf.dispatcher. Вместе с propagate это даёт
    по две строки на каждое сообщение SDK: в формате библиотеки и в нашем.
    """
    for name in ("trueconf.client.chatbot", "trueconf.dispatcher"):
        sdk_logger = logging.getLogger(name)
        for handler in list(sdk_logger.handlers):
            sdk_logger.removeHandler(handler)
            if isinstance(handler, logging.StreamHandler):
                try:
                    handler.close()
                except Exception:
                    pass
        sdk_logger.propagate = True


def get_channel_logger(name: str) -> logging.Logger:
    """Возвращает логгер канала (chat/delete/error/error_history/webhook)."""
    logger = _channels.get(name)
    if logger is None:
        logger = logging.getLogger(name)
        _channels[name] = logger
    return logger


def log_dir_path(log_dir: str = "logs") -> Path:
    return Path(log_dir)
