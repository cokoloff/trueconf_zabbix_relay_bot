#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конфигурационный файл для TrueConf Zabbix Relay Bot
Версия 10.0 - Упрощенная версия
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================================================

# Сервер TrueConf
TRUECONF_SERVER = os.getenv("TRUECONF_SERVER", "your-server.trueconf.com")

# Токен авторизации (обязательный параметр)
TRUECONF_TOKEN = os.getenv("TRUECONF_TOKEN", "your-bot-token-here")

# ID чата по умолчанию (можно оставить пустым, установить через команду /default)
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "")


# ============================================================================
# НАСТРОЙКИ АДМИНИСТРИРОВАНИЯ
# ============================================================================

# Режим администрирования: strict, whitelist, open
ADMIN_MODE = os.getenv('ADMIN_MODE', 'strict')

# Список администраторов (через запятую)
# Пример: ADMIN_IDS=user1@domain.com,user2@domain.com,123456789
ADMIN_IDS = os.getenv('ADMIN_IDS', '')


# ============================================================================
# ВЕБ-СЕРВЕР
# ============================================================================

WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", "8080"))


# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
WEBSOCKET_DEBUG = os.getenv('WEBSOCKET_DEBUG', 'False').lower() == 'true'

# ============================================================================
# HEARTBEAT
# ============================================================================

HEARTBEAT_MODE = os.getenv('HEARTBEAT_MODE', 'smart')
HEARTBEAT_INTERVAL = int(os.getenv('HEARTBEAT_INTERVAL', '30'))

# Проверка обязательных параметров
if not TRUECONF_SERVER:
    print("❌ ОШИБКА: TRUECONF_SERVER не указан!")

if not TRUECONF_TOKEN:
    print("❌ ОШИБКА: TRUECONF_TOKEN не указан!")

print(f"✅ Конфигурация загружена")
print(f"   🌐 Сервер: {TRUECONF_SERVER}")
print(f"   🔐 Режим администрирования: {ADMIN_MODE}")