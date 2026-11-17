#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конфигурация TrueConf Zabbix Relay Bot.

Версия 12.0 — все параметры читаются из окружения (.env), значения по умолчанию
подобраны для python-trueconf-bot >= 1.5.5.
"""

import os

from dotenv import load_dotenv

load_dotenv()

VERSION = "12.0"

# ============================================================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================================================

TRUECONF_SERVER = os.getenv("TRUECONF_SERVER", "trueconf.example.com")
TRUECONF_PORT = int(os.getenv("TRUECONF_PORT", "443")) or None  # None → 443 для https

TRUECONF_TOKEN_URL = os.getenv(
    "TRUECONF_TOKEN_URL", "https://trueconf.example.com/bridge/api/client/v1/oauth/token"
)
TRUECONF_CLIENT_ID = os.getenv("TRUECONF_CLIENT_ID", "chat_bot")
TRUECONF_USERNAME = os.getenv("TRUECONF_USERNAME", "trueconf-bot")
TRUECONF_PASSWORD = os.getenv("TRUECONF_PASSWORD", "")
TOKEN_FILE = os.getenv("TOKEN_FILE", "bot_token.json")

def _parse_verify_ssl(value: str):
    """
    Проверка TLS-сертификата сервера.

        VERIFY_SSL=true        — проверять по системному хранилищу (truststore)
        VERIFY_SSL=false       — не проверять (самоподписанный сертификат)
        VERIFY_SSL=/path/ca.pem — проверять по указанному CA-бандлу
    """
    raw = (value or "").strip()
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off", ""):
        return False
    return raw  # путь к файлу с CA


VERIFY_SSL = _parse_verify_ssl(os.getenv("VERIFY_SSL", "false"))

# ID чата по умолчанию (можно оставить пустым, установить через команду /default)
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "0000000000000000000000000000000000000000")

STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

# ============================================================================
# АДМИНИСТРИРОВАНИЕ
# ============================================================================

# Режим администрирования: strict, whitelist, open
ADMIN_MODE = os.getenv("ADMIN_MODE", "strict")

# Список администраторов (через запятую). Эти записи нельзя удалить из бота.
ADMIN_IDS = os.getenv("ADMIN_IDS", "admin@example.com")

# ============================================================================
# ВЕБ-СЕРВЕР И ПАНЕЛЬ УПРАВЛЕНИЯ
# ============================================================================

WEB_SERVER_HOST = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", "8080"))

# Если задан — API панели требует заголовок X-WebUI-Token или ?token=
WEBUI_TOKEN = os.getenv("WEBUI_TOKEN", "")

# Внешний адрес панели (для redirect_uri в Keycloak), например https://tcbot.example.com
WEBUI_PUBLIC_URL = os.getenv("WEBUI_PUBLIC_URL", "")

# ============================================================================
# SSO (Keycloak)
# ============================================================================
# Режим авторизации панели:
#   both     — SSO Keycloak + локальный администратор (рекомендуется)
#   keycloak — только Keycloak
#   local    — только локальный администратор
#   token    — статический токен WEBUI_TOKEN
#   none     — без авторизации (только закрытый контур)
WEBUI_AUTH = os.getenv("WEBUI_AUTH", "token" if WEBUI_TOKEN else "none")

# ============================================================================
# ЛОКАЛЬНЫЙ АДМИНИСТРАТОР (резервный вход без Keycloak)
# ============================================================================
LOCAL_ADMIN_ENABLED = os.getenv("LOCAL_ADMIN_ENABLED", "true").lower() in ("1", "true", "yes", "on")
LOCAL_ADMIN_USERNAME = os.getenv("LOCAL_ADMIN_USERNAME", "local-admin")

# Пароль в открытом виде — только для первого запуска (сразу сохраняется как хэш)
LOCAL_ADMIN_PASSWORD = os.getenv("LOCAL_ADMIN_PASSWORD", "")

# Готовый хэш пароля (приоритетнее открытого пароля). Получить:
#   python -c "from tcbot.localadmin import hash_password; print(hash_password('пароль'))"
LOCAL_ADMIN_PASSWORD_HASH = os.getenv("LOCAL_ADMIN_PASSWORD_HASH", "")

# Файл, куда однократно записывается автоматически сгенерированный пароль
LOCAL_ADMIN_PASSWORD_FILE = os.getenv("LOCAL_ADMIN_PASSWORD_FILE", "local-admin-initial-password.txt")

SSO_SERVER_URL = os.getenv("SSO_SERVER_URL", "https://auth.example.com")
SSO_REALM = os.getenv("SSO_REALM", "aquarius")
SSO_CLIENT_ID = os.getenv("SSO_CLIENT_ID", "tcbot-admin")
# Для public-клиента с PKCE секрет не нужен; если клиент confidential — задайте
SSO_CLIENT_SECRET = os.getenv("SSO_CLIENT_SECRET", "")
# Переопределение redirect_uri (иначе WEBUI_PUBLIC_URL + /auth/callback)
SSO_REDIRECT_URI = os.getenv("SSO_REDIRECT_URI", "")

# Роли Keycloak (realm или клиента), дающие доступ
SSO_ADMIN_ROLES = os.getenv("SSO_ADMIN_ROLES", "tcbot-admin")
SSO_VIEWER_ROLES = os.getenv("SSO_VIEWER_ROLES", "tcbot-viewer")
# ВАЖНО: scope 'roles' и 'groups' нужны, чтобы Keycloak положил роли и группы
# в токен. Без них пользователь войдёт, но ролей не будет.
SSO_SCOPE = os.getenv("SSO_SCOPE", "openid profile email roles groups")

# Время жизни сессии панели (сек)
SSO_SESSION_TTL = int(os.getenv("SSO_SESSION_TTL", str(8 * 3600)))
# Флаг Secure для cookie (включайте, если панель работает по HTTPS)
SSO_COOKIE_SECURE = os.getenv("SSO_COOKIE_SECURE", "false").lower() in ("1", "true", "yes", "on")
# Секрет подписи cookie; если пусто — генерируется при старте (сессии сбросятся при рестарте)
SSO_SESSION_SECRET = os.getenv("SSO_SESSION_SECRET", "")

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
WEBSOCKET_DEBUG = os.getenv("WEBSOCKET_DEBUG", "False").lower() == "true"

# ============================================================================
# СВЯЗЬ С СЕРВЕРОМ: HEARTBEAT, WATCHDOG, ПЕРЕПОДКЛЮЧЕНИЕ
# ============================================================================

# Режим heartbeat: off, smart, strict
#   off    — только события SDK (переподключение по обрыву)
#   smart  — плюс активная проверка связи; перезапуск после 3 подряд неудач (рекомендуется)
#   strict — перезапуск немедленно после первой неудачной проверки
HEARTBEAT_MODE = os.getenv("HEARTBEAT_MODE", "smart")

# Как часто проверять соединение активным запросом (сек)
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))

# Как часто проверять состояние событий SDK (сек)
WATCHDOG_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "15"))

# Порог бездействия: сколько секунд без авторизации считаются сбоем (сек)
IDLE_THRESHOLD = int(os.getenv("IDLE_THRESHOLD", "300"))

# Попыток подряд до принудительного обновления токена
MAX_RECONNECT_ATTEMPTS = int(os.getenv("MAX_RECONNECT_ATTEMPTS", "10"))

# Начальная задержка перед переподключением (сек)
RECONNECT_DELAY = float(os.getenv("RECONNECT_DELAY", "5"))

# Во сколько раз растёт пауза после каждой неудачной попытки
RECONNECT_BACKOFF = float(os.getenv("RECONNECT_BACKOFF", "2.0"))

# Потолок паузы (сек). 1800 = 30 минут: при плановых работах сервер может быть
# недоступен часами, поэтому после нескольких попыток темп снижается до 1 раза в полчаса.
RECONNECT_MAX_DELAY = float(os.getenv("RECONNECT_MAX_DELAY", "1800"))

# Окно «частых» попыток (сек): пока простой меньше — пауза растёт экспоненциально,
# после — сразу RECONNECT_MAX_DELAY. 600 = 10 минут.
RECONNECT_FAST_WINDOW = float(os.getenv("RECONNECT_FAST_WINDOW", "600"))

# Через сколько секунд непрерывного простоя перейти в «тихий» режим:
# в error.log пишется только первая ошибка, остальное — в GUI и bot.log.
QUIET_AFTER = float(os.getenv("QUIET_AFTER", "600"))

# Таймаут активной проверки соединения (сек)
PING_TIMEOUT = float(os.getenv("PING_TIMEOUT", "10"))

# Переподключение внутри SDK: число попыток и максимальная пауза (сек)
WS_MAX_RETRIES = int(os.getenv("WS_MAX_RETRIES", "5"))
WS_MAX_DELAY = int(os.getenv("WS_MAX_DELAY", "60"))

# Таймаут ожидания ответа сервера на API-запрос (сек)
SDK_TIMEOUT = float(os.getenv("SDK_TIMEOUT", "15"))

# Получать непрочитанные сообщения при подключении
RECEIVE_UNREAD_MESSAGES = os.getenv("RECEIVE_UNREAD_MESSAGES", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# ============================================================================
# ОЧЕРЕДЬ НЕДОСТАВЛЕННЫХ УВЕДОМЛЕНИЙ
# ============================================================================
# Пока TrueConf недоступен, уведомления складываются на диск и выгружаются
# после восстановления связи. Очередь переживает перезапуск процесса.
OUTBOX_ENABLED = os.getenv("OUTBOX_ENABLED", "true").lower() in ("1", "true", "yes", "on")
OUTBOX_FILE = os.getenv("OUTBOX_FILE", "bot_outbox.json")

# Максимум сообщений в очереди (старейшие вытесняются)
OUTBOX_MAX_SIZE = int(os.getenv("OUTBOX_MAX_SIZE", "5000"))

# Сколько часов хранить недоставленное (старше — удаляется)
OUTBOX_TTL_HOURS = float(os.getenv("OUTBOX_TTL_HOURS", "48"))

# Окно дедупликации идентичных уведомлений (сек), 0 — выключено
OUTBOX_DEDUP_WINDOW = float(os.getenv("OUTBOX_DEDUP_WINDOW", "120"))

# Период фоновой выгрузки очереди (сек)
OUTBOX_FLUSH_INTERVAL = float(os.getenv("OUTBOX_FLUSH_INTERVAL", "5"))

# Схлопывать несколько обновлений по одному триггеру в одно (останется последнее)
OUTBOX_COLLAPSE = os.getenv("OUTBOX_COLLAPSE", "true").lower() in ("1", "true", "yes", "on")

# ============================================================================
# ИСТОРИЯ МЕТРИК ДЛЯ ГРАФИКОВ И КАЛЕНДАРЯ
# ============================================================================
# Бот раз в METRICS_INTERVAL секунд снимает состояние: отправленные сообщения,
# размер очереди, связь, перезапуски. Из этих точек строятся графики,
# из дневной сводки — календарь активности в панели.
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
METRICS_FILE = os.getenv("METRICS_FILE", "bot_metrics.json")

# Период снятия точки (сек)
METRICS_INTERVAL = int(os.getenv("METRICS_INTERVAL", "60"))

# Период сохранения истории на диск (сек)
METRICS_SAVE_INTERVAL = int(os.getenv("METRICS_SAVE_INTERVAL", "300"))

# ============================================================================
# ДОСТАВКА УВЕДОМЛЕНИЙ
# ============================================================================

# Таймаут одной отправки сообщения (сек)
SEND_TIMEOUT = float(os.getenv("SEND_TIMEOUT", "20"))

# Количество попыток отправки и базовая пауза между ними (сек)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))

# Сколько секунд вебхук ждёт восстановления связи, прежде чем вернуть 503
WEBHOOK_WAIT_TIMEOUT = float(os.getenv("WEBHOOK_WAIT_TIMEOUT", "20"))

# ============================================================================
# КОМАНДЫ
# ============================================================================

COMMAND_TIMEOUT = float(os.getenv("COMMAND_TIMEOUT", "15"))

# ============================================================================
# УДАЛЕНИЕ СООБЩЕНИЙ ОБ ОШИБКАХ
# ============================================================================

DELETE_MESSAGES_ENABLED = os.getenv("DELETE_MESSAGES_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
ERROR_DELETE_THRESHOLD_HOURS = float(os.getenv("ERROR_DELETE_THRESHOLD_HOURS", "24"))
ERROR_HISTORY_RETENTION_DAYS = int(os.getenv("ERROR_HISTORY_RETENTION_DAYS", "7"))
ERROR_CLEANUP_SCHEDULE_HOUR = int(os.getenv("ERROR_CLEANUP_SCHEDULE_HOUR", "3"))

# ============================================================================
# ПРОВЕРКА
# ============================================================================

if not TRUECONF_SERVER:
    print("❌ ОШИБКА: TRUECONF_SERVER не указан!")

if not TRUECONF_PASSWORD:
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: TRUECONF_PASSWORD не задан — токен не будет получен")

print("✅ Конфигурация загружена")
print(f"   🌐 Сервер: {TRUECONF_SERVER}")
print(f"   🔐 Режим администрирования: {ADMIN_MODE}")
print(f"   💓 Heartbeat: {HEARTBEAT_MODE} / {HEARTBEAT_INTERVAL} с")
