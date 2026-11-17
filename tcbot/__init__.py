# -*- coding: utf-8 -*-
"""
Внутренний пакет TrueConf Zabbix Relay Bot.

Модули:
    logging_setup — общий лог + отдельные каналы chat/delete/error/webhook
    state         — состояние бота, администраторы, менеджер токена
    runner        — супервизор соединения (переподключение, heartbeat, watchdog)
    webui         — веб-сервер: приём вебхуков, health-эндпоинты и админ-GUI
    frontend      — HTML/JS админ-панели
"""

from .logging_setup import setup_logging, get_channel_logger
from .state import StateManager, AdminManager, TokenManager
from .runner import BotRunner

__all__ = [
    "setup_logging",
    "get_channel_logger",
    "StateManager",
    "AdminManager",
    "TokenManager",
    "BotRunner",
]
