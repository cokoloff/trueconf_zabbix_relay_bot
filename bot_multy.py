#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRUECONF ZABBIX RELAY BOT

Версия 12.0 — переход на python-trueconf-bot 1.5.x.

Что изменилось по сравнению с v11.0:
    * новый контракт SDK: методы возвращают dataclass-ответы, текст сообщения
      берётся из message.text, chat_id — из message.chat.chat_id;
    * Bot держит соединение под супервизором (tcbot.runner.BotRunner):
      автоматическое переподключение, heartbeat, watchdog;
    * вебхуки получили таймауты/повторы и корректный HTTP-код при недоставке;
    * health-эндпоинты отражают реальное состояние соединения;
    * появился веб-GUI с мониторингом и админкой (/);
    * восстановлена раздельная схема логирования (chat/delete/error/webhook).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import socket
import time
from datetime import datetime, timedelta
from functools import lru_cache, partial, wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import web

from trueconf import Bot, Dispatcher, Message, ParseMode, Router
from trueconf.exceptions import ApiErrorException, TextMessageTooLongError, TrueConfChatBotError
from trueconf.utils import safe_split_text

import config
from tcbot.auth import AuthManager
from tcbot.localadmin import LocalAdminStore
from tcbot.logging_setup import get_channel_logger, setup_logging
from tcbot.markup import MessageBuilder, plain_text, safe_text
from tcbot.metrics import MetricsStore
from tcbot.outbox import Outbox
from tcbot.runner import BotRunner
from tcbot.sdkinfo import SdkInspector
from tcbot.sso import KeycloakSSO
from tcbot.state import AdminManager, StateManager, TokenManager
from tcbot.appjs import APP_JS
from tcbot.frontend import FAVICON_SVG, LOGO_SVG, render_index
from tcbot.pages import PAGES, render_page
from tcbot.theme import STYLE_CSS

VERSION = "12.0"

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

def cfg(name: str, default: Any) -> Any:
    return getattr(config, name, default)


LOG_DIR = cfg("LOG_DIR", "logs")
LOG_LEVEL = cfg("LOG_LEVEL", "INFO")
WEBSOCKET_DEBUG = bool(cfg("WEBSOCKET_DEBUG", False))

TOKEN_CONFIG = {
    "token_url": cfg("TRUECONF_TOKEN_URL", "https://trueconf.example.com/bridge/api/client/v1/oauth/token"),
    "client_id": cfg("TRUECONF_CLIENT_ID", "chat_bot"),
    "username": cfg("TRUECONF_USERNAME", "trueconf-bot"),
    "password": cfg("TRUECONF_PASSWORD", ""),
    "server": cfg("TRUECONF_SERVER", "trueconf.example.com"),
    "token_file": cfg("TOKEN_FILE", "bot_token.json"),
}

server_host = cfg("TRUECONF_SERVER", "trueconf.example.com")

# Поведение соединения (реализовано в tcbot.runner.BotRunner)
HEARTBEAT_MODE = str(cfg("HEARTBEAT_MODE", "smart")).lower()
HEARTBEAT_INTERVAL = int(cfg("HEARTBEAT_INTERVAL", 30))
WATCHDOG_INTERVAL = int(cfg("WATCHDOG_INTERVAL", 15))
IDLE_THRESHOLD = int(cfg("IDLE_THRESHOLD", 300))
MAX_RECONNECT_ATTEMPTS = int(cfg("MAX_RECONNECT_ATTEMPTS", 10))
RECONNECT_DELAY = float(cfg("RECONNECT_DELAY", 5))
RECONNECT_BACKOFF = float(cfg("RECONNECT_BACKOFF", 2.0))
RECONNECT_MAX_DELAY = float(cfg("RECONNECT_MAX_DELAY", 1800))
RECONNECT_FAST_WINDOW = float(cfg("RECONNECT_FAST_WINDOW", 600))
QUIET_AFTER = float(cfg("QUIET_AFTER", 600))
PING_TIMEOUT = float(cfg("PING_TIMEOUT", 10))
WS_MAX_RETRIES = int(cfg("WS_MAX_RETRIES", 5))
WS_MAX_DELAY = int(cfg("WS_MAX_DELAY", 60))
SDK_TIMEOUT = float(cfg("SDK_TIMEOUT", 15))
VERIFY_SSL = bool(cfg("VERIFY_SSL", True))
RECEIVE_UNREAD = bool(cfg("RECEIVE_UNREAD_MESSAGES", False))

# История метрик для графиков и календаря активности в панели
METRICS_ENABLED = bool(cfg("METRICS_ENABLED", True))
METRICS_FILE = cfg("METRICS_FILE", "bot_metrics.json")
METRICS_INTERVAL = int(cfg("METRICS_INTERVAL", 60))
METRICS_SAVE_INTERVAL = int(cfg("METRICS_SAVE_INTERVAL", 300))

# Очередь недоставленных уведомлений (переживает недоступность сервера и перезапуск)
OUTBOX_ENABLED = bool(cfg("OUTBOX_ENABLED", True))
OUTBOX_FILE = cfg("OUTBOX_FILE", "bot_outbox.json")
OUTBOX_MAX_SIZE = int(cfg("OUTBOX_MAX_SIZE", 5000))
OUTBOX_TTL_HOURS = float(cfg("OUTBOX_TTL_HOURS", 48))
OUTBOX_DEDUP_WINDOW = float(cfg("OUTBOX_DEDUP_WINDOW", 120))
OUTBOX_FLUSH_INTERVAL = float(cfg("OUTBOX_FLUSH_INTERVAL", 5))
OUTBOX_COLLAPSE = bool(cfg("OUTBOX_COLLAPSE", True))

# Доставка уведомлений
SEND_TIMEOUT = float(cfg("SEND_TIMEOUT", 20))
MAX_RETRIES = int(cfg("MAX_RETRIES", 3))
RETRY_DELAY = float(cfg("RETRY_DELAY", 1.0))
WEBHOOK_WAIT_TIMEOUT = float(cfg("WEBHOOK_WAIT_TIMEOUT", 20))

# Веб-сервер
WEB_SERVER_HOST = cfg("WEB_SERVER_HOST", "0.0.0.0")
WEB_SERVER_PORT = int(cfg("WEB_SERVER_PORT", 8080))
WEBUI_TOKEN = cfg("WEBUI_TOKEN", "") or os.getenv("WEBUI_TOKEN", "")

# Авторизация панели: keycloak | local | both | token | none
WEBUI_AUTH = str(cfg("WEBUI_AUTH", "token" if WEBUI_TOKEN else "none")).lower()

# Локальный администратор (резервный вход, работает без Keycloak)
LOCAL_ADMIN_ENABLED = bool(cfg("LOCAL_ADMIN_ENABLED", True))
LOCAL_ADMIN_USERNAME = cfg("LOCAL_ADMIN_USERNAME", "local-admin")
LOCAL_ADMIN_PASSWORD = cfg("LOCAL_ADMIN_PASSWORD", "")
LOCAL_ADMIN_PASSWORD_HASH = cfg("LOCAL_ADMIN_PASSWORD_HASH", "")
LOCAL_ADMIN_PASSWORD_FILE = cfg("LOCAL_ADMIN_PASSWORD_FILE", "local-admin-initial-password.txt")
WEBUI_PUBLIC_URL = cfg("WEBUI_PUBLIC_URL", "") or f"http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}"

SSO_CONFIG = {
    "server_url": cfg("SSO_SERVER_URL", "https://auth.example.com"),
    "realm": cfg("SSO_REALM", "aquarius"),
    "client_id": cfg("SSO_CLIENT_ID", "tcbot-admin"),
    "client_secret": cfg("SSO_CLIENT_SECRET", ""),
    "redirect_uri": cfg("SSO_REDIRECT_URI", ""),
    "admin_roles": [r.strip() for r in str(cfg("SSO_ADMIN_ROLES", "tcbot-admin")).split(",") if r.strip()],
    "viewer_roles": [r.strip() for r in str(cfg("SSO_VIEWER_ROLES", "tcbot-viewer")).split(",") if r.strip()],
    "session_ttl": int(cfg("SSO_SESSION_TTL", 8 * 3600)),
    "cookie_secure": bool(cfg("SSO_COOKIE_SECURE", False)),
    "session_secret": cfg("SSO_SESSION_SECRET", ""),
    "scope": cfg("SSO_SCOPE", "openid profile email"),
}

auth_manager: Optional[AuthManager] = None
sdk_inspector: Optional[SdkInspector] = None
metrics: Optional[MetricsStore] = None
_metrics_task: Optional[asyncio.Task] = None

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logger = setup_logging(
    log_dir=LOG_DIR,
    level=LOG_LEVEL,
    sdk_debug=WEBSOCKET_DEBUG,
)
chat_log = get_channel_logger("chat")
delete_log = get_channel_logger("delete")
error_log = get_channel_logger("error")
history_log = get_channel_logger("error_history")
webhook_log = get_channel_logger("webhook")

# ============================================================================
# ГЛОБАЛЬНЫЕ ОБЪЕКТЫ
# ============================================================================

router = Router()
dp = Dispatcher()
dp.include_router(router)

bot: Optional[Bot] = None
state_manager: Optional[StateManager] = None
admin_manager: Optional[AdminManager] = None
token_manager: Optional[TokenManager] = None
runner: Optional[BotRunner] = None
outbox: Optional[Outbox] = None
_flush_task: Optional[asyncio.Task] = None

start_time: Optional[datetime] = None
web_runner: Optional[web.AppRunner] = None
web_port_actual: Optional[int] = None

_processed_commands: "List[str]" = []
_PROCESSED_LIMIT = 200


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

@lru_cache(maxsize=32)
def get_channel_icon(channel: str) -> str:
    if not channel:
        return ""
    icons = {
        "default": "📌", "critical": "🚨", "warning": "⚠️",
        "info": "ℹ️", "database": "🗄️", "network": "🌐",
        "1c": "📦", "cpu": "⚡", "memory": "💾",
        "disk": "💿", "security": "🔒", "app": "📱",
        "monitoring": "📊", "alerts": "🔔", "zabbix": "📈",
        "service": "🎯", "sla": "📊",
    }
    return icons.get(channel.lower(), "📢")


def shorten(value: Optional[str], size: int = 8) -> str:
    if not value:
        return "—"
    return value if len(value) <= size else value[:size] + "…"


def is_duplicate(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    if message_id in _processed_commands:
        return True
    _processed_commands.append(message_id)
    if len(_processed_commands) > _PROCESSED_LIMIT:
        del _processed_commands[:-_PROCESSED_LIMIT]
    return False


def message_max_length() -> int:
    default = 4000
    if state_manager is None:
        return default
    return int(state_manager.settings.get("max_message_length", default) or default)


# ============================================================================
# ДОСТАВКА СООБЩЕНИЙ
# ============================================================================

async def wait_until_ready(timeout: Optional[float] = None) -> bool:
    """Ожидает авторизации бота, чтобы не терять уведомления во время обрыва."""
    if timeout is None:
        timeout = WEBHOOK_WAIT_TIMEOUT
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if runner is not None and runner.is_ready:
            return True
        await asyncio.sleep(0.5)
    return runner is not None and runner.is_ready


async def deliver_message(
    chat_id: str,
    text: str,
    channel: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Отправляет текст в чат: ожидание готовности, разбиение длинных сообщений,
    повторы, таймаут. Возвращает (успех, ошибка).
    """
    if not await wait_until_ready():
        return False, "бот не авторизован на сервере"

    if bot is None:
        return False, "SDK-бот ещё не создан"

    retries = int(state_manager.settings.get("max_retries", MAX_RETRIES) or 0)
    attempts = max(1, retries)
    limit = message_max_length()
    chunks = safe_split_text(text, limit=limit) or [text]
    last_error: Optional[str] = None

    for index, chunk in enumerate(chunks, start=1):
        delivered = False
        for attempt in range(1, attempts + 1):
            try:
                await send_html(chat_id, chunk)
                delivered = True
                break
            except TextMessageTooLongError as exc:
                error_log.error(f"❌ Сообщение слишком длинное: {exc}")
                last_error = str(exc)
                try:
                    shorter = safe_split_text(chunk, limit=max(500, limit // 2))
                    for part in shorter:
                        await send_html(chat_id, part)
                    delivered = True
                    break
                except Exception as inner:
                    last_error = str(inner)
                    break
            except ApiErrorException as exc:
                # Невалидная разметка или иная ошибка API: пробуем обычным текстом
                logger.warning(f"⚠️ API-ошибка отправки ({exc}); повтор без разметки")
                try:
                    await asyncio.wait_for(
                        bot.send_message(
                            chat_id=chat_id, text=plain_text(chunk), parse_mode=ParseMode.TEXT
                        ),
                        timeout=SEND_TIMEOUT,
                    )
                    delivered = True
                    break
                except Exception as inner:
                    last_error = f"{type(inner).__name__}: {inner}"
            except (asyncio.TimeoutError, TimeoutError, TrueConfChatBotError, ConnectionError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                error_log.warning(
                    f"⚠️ Не удалось отправить в {shorten(chat_id)} "
                    f"(часть {index}/{len(chunks)}, попытка {attempt}/{attempts}): {last_error}"
                )
                if runner is not None and not runner.is_ready:
                    await wait_until_ready()
            except Exception as exc:  # непредвиденное
                last_error = f"{type(exc).__name__}: {exc}"
                error_log.error("❌ Ошибка отправки", exc_info=exc)
                break

            if attempt < attempts:
                await asyncio.sleep(RETRY_DELAY * attempt)

        if not delivered:
            if state_manager is not None:
                await state_manager.increment("messages_failed")
            return False, last_error or "неизвестная ошибка отправки"



    if state_manager is not None:
        await state_manager.increment("messages_sent")
    return True, None


async def send_html(chat_id: str, text: str) -> None:
    """
    Отправляет сообщение с HTML-разметкой (поддерживается TrueConf полностью).

    Если сервер отклонит разметку, повторяем обычным текстом — уведомление
    важнее оформления.
    """
    try:
        await asyncio.wait_for(
            bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML),
            timeout=SEND_TIMEOUT,
        )
    except ApiErrorException as exc:
        logger.warning(f"⚠️ HTML отклонён сервером ({exc}); отправка обычным текстом")
        await asyncio.wait_for(
            bot.send_message(chat_id=chat_id, text=plain_text(text), parse_mode=ParseMode.TEXT),
            timeout=SEND_TIMEOUT,
        )


async def _send_once(chat_id: str, chunk: str) -> None:
    """Одна попытка отправки без повторов (повторы делает вызывающий код)."""
    await send_html(chat_id, chunk)


async def flush_outbox() -> int:
    """
    Выгружает накопленные сообщения, пока связь есть.
    Возвращает количество доставленных.
    """
    if outbox is None or len(outbox) == 0 or not (runner is not None and runner.is_ready):
        return 0

    delivered = 0
    while True:
        if runner is None or not runner.is_ready:
            break
        item = await outbox.pop()
        if item is None:
            break

        limit = message_max_length()
        chunks = safe_split_text(item.text, limit=limit) or [item.text]
        try:
            for chunk in chunks:
                await _send_once(item.chat_id, chunk)
        except Exception as exc:
            error_log.warning(
                f"⚠️ Не удалось выгрузить из очереди ({item.channel or item.chat_id}): "
                f"{type(exc).__name__}: {exc} — возвращаю в очередь"
            )
            await outbox.requeue_front(item)
            break

        await outbox.mark_sent(item)
        delivered += 1
        age_hours = item.age_hours()
        webhook_log.info(
            f"📤 Из очереди доставлено: канал '{item.channel or '—'}' "
            f"(ожидало {age_hours * 60:.0f} мин)"
        )

    if delivered:
        logger.info(f"📤 Очередь: доставлено {delivered}, осталось {len(outbox)}")
    return delivered


async def outbox_flusher(interval: float = 5.0) -> None:
    """Фоновая выгрузка очереди после восстановления связи."""
    was_ready = False
    while True:
        try:
            await asyncio.sleep(interval)
            ready = runner is not None and runner.is_ready
            pending = len(outbox) if outbox is not None else 0
            if ready and pending > 0:
                if not was_ready:
                    logger.info(f"🔌 Связь восстановлена — выгружаю {len(outbox)} сообщений из очереди")
                await flush_outbox()
            was_ready = ready
        except asyncio.CancelledError:
            break
        except Exception as exc:
            error_log.error(f"❌ Ошибка выгрузки очереди: {exc}", exc_info=exc)


# ============================================================================
# АДМИНИСТРИРОВАНИЕ
# ============================================================================

def admin_required(func):
    @wraps(func)
    async def wrapper(msg: Message, args: List[str]):
        author_id = getattr(msg.author, "id", None)
        command = args[0] if args else ""

        if not author_id:
            await msg.answer("❌ Не удалось определить пользователя")
            return

        allowed, reason = admin_manager.can_execute_command(author_id, command)
        if not allowed:
            logger.warning(f"🚫 Несанкционированная команда {command} от {author_id}")
            build = MessageBuilder()
            build.line("🚫 Доступ запрещен")
            build.line(reason)
            await msg.answer(build.build(), parse_mode=ParseMode.HTML)
            return

        return await func(msg, args)

    return wrapper


async def cmd_help(msg: Message, args: List[str]) -> None:
    author_id = getattr(msg.author, "id", "unknown")
    is_admin = admin_manager.is_admin(author_id)

    build = MessageBuilder()
    build.title(f"👋 TrueConf Zabbix Bot v{VERSION}")
    build.line("Ваш ID: ", author_id)
    build.line("Статус: ", "👑 Администратор" if is_admin else "👤 Пользователь")
    build.blank()

    build.heading("📋 Публичные команды:")
    build.bullet("/help", "— эта справка")
    build.bullet("/info", "— информация о боте")
    build.bullet("/health", "— состояние бота")
    build.bullet("/ping", "— проверка связи")
    build.bullet("/whoami", "— информация о себе")

    if is_admin:
        build.blank()
        build.heading("🔐 Команды администратора:")
        build.bullet("/register <имя>", "— создать канал")
        build.bullet("/unregister <имя>", "— удалить канал")
        build.bullet("/channels [стр]", "— список каналов")
        build.bullet("/channel_edit <имя> chat_id <id>", "— изменить канал")
        build.bullet("/default", "— текущий чат как чат по умолчанию")
        build.bullet("/admins", "— список администраторов")
        build.bullet("/admin_add <id>", "— добавить администратора")
        build.bullet("/admin_remove <id>", "— удалить администратора")
        build.bullet("/token_info", "— информация о токене")

    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


async def cmd_whoami(msg: Message, args: List[str]) -> None:
    author_id = getattr(msg.author, "id", "unknown")
    build = MessageBuilder()
    build.title("👤 Информация о пользователе")
    build.line("ID пользователя: ", author_id)
    build.line("ID чата: ", msg.chat.chat_id)
    build.line("Чат: ", msg.chat.chat_title or "—")
    build.line("Статус: ", "👑 Администратор" if admin_manager.is_admin(author_id) else "👤 Пользователь")
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


async def cmd_info(msg: Message, args: List[str]) -> None:
    uptime = datetime.now() - start_time if start_time else timedelta(0)
    metadata = state_manager.metadata

    remaining = token_manager.remaining_seconds() if token_manager else None
    if remaining is None:
        token_status = "❌ Не получен"
    elif remaining > 0:
        token_status = f"✅ Действителен {remaining / 86400:.0f} дн."
    else:
        token_status = "⚠️ Истек"

    health = runner.health() if runner else {}

    build = MessageBuilder()
    build.title(f"🤖 TrueConf Zabbix Bot v{VERSION}")
    build.line("Статус: ", "✅ Активен" if health.get("ready") else "⚠️ Нет связи")
    build.line("⏱️ Uptime: ", str(uptime).split(".")[0])
    build.line("🌐 Сервер: ", TOKEN_CONFIG["server"])
    build.line("🔗 WebSocket: ", "✅" if health.get("ws_connected") else "❌",
               "   Авторизация: ", "✅" if health.get("authorized") else "❌")
    build.line("♻️ Перезапусков связи: ", health.get("restarts", 0))
    build.line("🔑 Токен: ", token_status)
    if token_manager and token_manager.expires_at:
        build.line("📅 Истекает: ", token_manager.expires_at.strftime("%Y-%m-%d %H:%M:%S"))
    build.line("📊 Статистика: каналов ", len(state_manager.notification_channels),
               ", отправлено ", metadata.get("messages_sent", 0),
               ", ошибок ", metadata.get("messages_failed", 0))
    build.line("🔐 Режим доступа: ", admin_manager.mode,
               ", администраторов ", len(admin_manager.admin_ids))
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


async def cmd_health(msg: Message, args: List[str]) -> None:
    health = runner.health() if runner else {}
    build = MessageBuilder()
    build.title("🩺 Health Check")
    build.line("Бот: ", "✅ авторизован" if health.get("ready") else "❌ не авторизован")
    build.line("WebSocket: ", "✅" if health.get("ws_connected") else "❌")
    build.line("Состояние: ", health.get("state", "—"))
    build.line("Heartbeat: ", health.get("heartbeat_mode"), " / ",
               health.get("heartbeat_interval"), " с")
    build.line("Перезапусков связи: ", health.get("restarts", 0))
    if health.get("last_error"):
        build.line("Последняя ошибка: ", health["last_error"])
    build.line("Версия: ", VERSION)
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


async def cmd_ping(msg: Message, args: List[str]) -> None:
    await msg.answer("🏓 Pong!", parse_mode=ParseMode.HTML)


async def cmd_token_info(msg: Message, args: List[str]) -> None:
    if not admin_manager.is_admin(getattr(msg.author, "id", None)):
        await msg.answer("🚫 Доступ запрещен", parse_mode=ParseMode.HTML)
        return

    build = MessageBuilder()
    if token_manager and token_manager.token:
        remaining = token_manager.remaining_seconds() or 0
        build.title("🔑 Информация о токене")
        build.line("Статус: ✅ Активен")
        if token_manager.expires_at:
            build.line("Истекает: ", token_manager.expires_at.strftime("%Y-%m-%d %H:%M:%S"))
        build.line("Осталось: ", f"{remaining / 86400:.1f} дн. ({remaining / 3600:.1f} ч)")
        build.line("Токен: ", token_manager.token[:16] + "…" + token_manager.token[-8:])
        build.line("Автообновление: ✅ активно")
    else:
        build.line("❌ Токен не получен")
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


@admin_required
async def cmd_register(msg: Message, args: List[str]) -> None:
    if len(args) < 2:
        build = MessageBuilder()
        build.line("❌ Укажите имя канала")
        build.line("Пример: /register alerts")
        await msg.answer(build.build(), parse_mode=ParseMode.HTML)
        return

    channel_name = args[1].lower()
    if channel_name in state_manager.notification_channels:
        await msg.answer(f"❌ Канал {channel_name} уже существует", parse_mode=ParseMode.HTML)
        return

    await state_manager.add_channel(
        channel_name,
        msg.chat.chat_id,
        created_by=getattr(msg.author, "id", None),
        chat_title=msg.chat.chat_title,
    )
    await state_manager.save()

    build = MessageBuilder()
    build.bold(f"✅ Канал {channel_name} зарегистрирован")
    build.line("Теперь в вебхуках можно указывать: channel=", channel_name)
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


@admin_required
async def cmd_unregister(msg: Message, args: List[str]) -> None:
    if len(args) < 2:
        await msg.answer("❌ Укажите имя канала", parse_mode=ParseMode.HTML)
        return
    channel_name = args[1].lower()
    if await state_manager.remove_channel(channel_name):
        await state_manager.save()
        await msg.answer(f"✅ Канал {channel_name} удален", parse_mode=ParseMode.HTML)
    else:
        await msg.answer(f"❌ Канал {channel_name} не найден", parse_mode=ParseMode.HTML)


CHANNELS_PAGE_SIZE = 15

# Пробельные и невидимые символы, которые клиенты вставляют в текст.
# Заменяем на обычный пробел: если их просто удалить, «/channels 2»
# превратится в «/channels2» и команда перестанет распознаваться.
_SPACE_LIKE = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00a0\u202f\u2007\u2009\u2002\u2003\u3000"),
    " ",
)
_INVISIBLE = _SPACE_LIKE


def _clean_arg(value: str) -> str:
    """
    Очищает аргумент команды от невидимых символов и лишних пробелов.

    TrueConf и некоторые клиенты вставляют zero-width и неразрывные пробелы:
    из-за них «2» перестаёт быть числом, а имя канала не находится в словаре.
    """
    if not value:
        return ""
    cleaned = str(value).translate(_INVISIBLE)
    return cleaned.strip().strip("/").strip()


# HTML-сущности, которые могут встретиться в тексте команды
_ENTITIES = {
    "&nbsp;": " ",
    "&#160;": " ",
    "&#xa0;": " ",
    "&thinsp;": " ",
    "&ensp;": " ",
    "&emsp;": " ",
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&quot;": '"',
    "&#39;": "'",
}


def normalize_command_text(value: str) -> str:
    """
    Приводит текст команды к предсказуемому виду.

    Убирает HTML-сущности и невидимые символы, схлопывает пробелы.
    Нужно потому, что клиенты TrueConf могут прислать «/channels&nbsp;2»
    или вставить zero-width пробел — без нормализации команда не находится.
    """
    if not value:
        return ""
    text = str(value)
    for entity, replacement in _ENTITIES.items():
        if entity in text:
            text = text.replace(entity, replacement)
    text = text.translate(_INVISIBLE)
    return " ".join(text.split())


def _as_page_number(value: str) -> Optional[int]:
    """Возвращает номер страницы, если аргумент — число, иначе None."""
    if not value:
        return None
    if value.isdigit():
        return int(value)
    # на случай пробелов внутри: «1 2» не число, но « 2 » уже очищено выше
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits and digits == value.replace(" ", ""):
        return int(digits)
    return None


@admin_required
async def cmd_channels(msg: Message, args: List[str]) -> None:
    """
    Компактный список каналов.

    Формат: одна строка на канал — имя, chat_id и метка. Подробности
    (кто и когда создал) показываются только для одного канала по /channels <имя>,
    иначе при двух десятках каналов сообщение превращается в полотно.
    """
    channels = state_manager.notification_channels
    if not channels:
        build = MessageBuilder()
        build.line("❌ Нет зарегистрированных каналов")
        build.line("Используйте /register <имя>")
        await msg.answer(build.build(), parse_mode=ParseMode.HTML)
        return

    # Аргумент может прийти с невидимыми символами (zero-width, nbsp),
    # поэтому сначала очищаем его, затем решаем: страница это или имя канала.
    arg = _clean_arg(args[1]) if len(args) > 1 else ""
    page_requested = _as_page_number(arg)

    # /channels <имя> — карточка одного канала
    if arg and page_requested is None:
        name = arg.lower()
        info = channels.get(name)
        if info is None:
            await msg.answer(f"❌ Канал {name} не найден", parse_mode=ParseMode.HTML)
            return
        build = MessageBuilder()
        build.title(f"{get_channel_icon(name)} {name}")
        build.line("Chat ID: ", info.get("chat_id", ""))
        if info.get("chat_title"):
            build.line("Название чата: ", info["chat_title"])
        if info.get("created_by"):
            build.line("Создал: ", info["created_by"])
        build.line("Создан: ", str(info.get("created_at", ""))[:19].replace("T", " "))
        if info.get("updated_at"):
            build.line("Изменён: ", str(info["updated_at"])[:19].replace("T", " "))
        build.blank()
        build.line("Изменить: /channel_edit ", name, " chat_id <id>")
        build.line("Переименовать: /channel_edit ", name, " name <новое>")
        build.line("Удалить: /unregister ", name)
        await msg.answer(build.build(), parse_mode=ParseMode.HTML)
        return

    # /channels [страница] — компактный список
    total = len(channels)
    pages = max(1, (total + CHANNELS_PAGE_SIZE - 1) // CHANNELS_PAGE_SIZE)
    page = 1
    if page_requested is not None:
        page = max(1, min(page_requested, pages))

    start = (page - 1) * CHANNELS_PAGE_SIZE
    subset = list(channels.items())[start:start + CHANNELS_PAGE_SIZE]

    build = MessageBuilder()
    head = f"📢 Каналы ({total})"
    if pages > 1:
        head += f" · стр. {page}/{pages}"
    build.title(head)
    build.blank()
    for name, info in subset:
        chat_id = str(info.get("chat_id", ""))
        build.line(get_channel_icon(name), " ", name, " — ", shorten(chat_id, 8))

    build.blank()
    if pages > 1:
        nav = []
        if page > 1:
            nav.append(f"/channels {page - 1}")
        if page < pages:
            nav.append(f"/channels {page + 1}")
        if nav:
            build.line("Страницы: ", " · ".join(nav))
    build.line("Подробнее о канале: /channels <имя>")
    build.line("Редактирование: /channel_edit <имя> chat_id <id>")
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


@admin_required
async def cmd_channel_edit(msg: Message, args: List[str]) -> None:
    """
    Изменение канала из чата.

        /channel_edit <имя> chat_id <новый id>
        /channel_edit <имя> title <название чата>
        /channel_edit <имя> name <новое имя>
    """
    if len(args) < 4:
        build = MessageBuilder()
        build.line("❌ Формат: /channel_edit <имя> <поле> <значение>")
        build.blank()
        build.bullet("chat_id <id>", "— сменить чат")
        build.bullet("title <текст>", "— название чата")
        build.bullet("name <новое>", "— переименовать канал")
        await msg.answer(build.build(), parse_mode=ParseMode.HTML)
        return

    name = args[1].lower()
    field = args[2].lower()
    value = " ".join(args[3:]).strip()

    if name not in state_manager.notification_channels:
        await msg.answer(f"❌ Канал {name} не найден", parse_mode=ParseMode.HTML)
        return

    if field == "chat_id":
        ok = await state_manager.update_channel(name, chat_id=value)
    elif field in ("title", "chat_title"):
        ok = await state_manager.update_channel(name, chat_title=value)
    elif field in ("name", "rename"):
        new_name = value.lower()
        if not _valid_channel_name(new_name):
            await msg.answer(
                "❌ Имя канала: только буквы, цифры, дефис и подчёркивание",
                parse_mode=ParseMode.HTML,
            )
            return
        if new_name in state_manager.notification_channels:
            await msg.answer(f"❌ Канал {new_name} уже существует", parse_mode=ParseMode.HTML)
            return
        ok = await state_manager.update_channel(name, new_name=new_name)
    else:
        await msg.answer(
            f"❌ Неизвестное поле {field}. Допустимо: chat_id, title, name",
            parse_mode=ParseMode.HTML,
        )
        return

    if not ok:
        await msg.answer("❌ Не удалось изменить канал", parse_mode=ParseMode.HTML)
        return

    await state_manager.save()
    build = MessageBuilder()
    build.bold("✅ Канал обновлён")
    build.line("Канал: ", value if field in ("name", "rename") else name)
    build.line("Поле: ", field)
    build.line("Значение: ", value)
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


@admin_required
async def cmd_default(msg: Message, args: List[str]) -> None:
    state_manager.default_chat = msg.chat.chat_id
    await state_manager.save()
    build = MessageBuilder()
    build.bold("📌 Текущий чат установлен как чат по умолчанию")
    build.line("Вебхуки без указания канала будут приходить сюда")
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


@admin_required
async def cmd_admins(msg: Message, args: List[str]) -> None:
    admins = admin_manager.get_admins()
    build = MessageBuilder()
    build.title("👑 Список администраторов")
    if admins:
        for index, admin_id in enumerate(admins, 1):
            mark = "" if admin_manager.is_static(admin_id) else " (динамический)"
            build.line(f"{index}. ", admin_id, mark)
    else:
        build.line("Нет администраторов")
    build.blank()
    build.line("Режим доступа: ", admin_manager.mode)
    await msg.answer(build.build(), parse_mode=ParseMode.HTML)


@admin_required
async def cmd_admin_add(msg: Message, args: List[str]) -> None:
    if len(args) < 2:
        build = MessageBuilder()
        build.line("❌ Укажите ID пользователя")
        build.line("Пример: /admin_add user@domain")
        await msg.answer(build.build(), parse_mode=ParseMode.HTML)
        return
    user_id = args[1]
    if admin_manager.add_admin(user_id):
        await state_manager.save()
        await msg.answer(f"✅ Пользователь {user_id} добавлен в администраторы",
                         parse_mode=ParseMode.HTML)
    else:
        await msg.answer(f"❌ Пользователь {user_id} уже является администратором",
                         parse_mode=ParseMode.HTML)


@admin_required
async def cmd_admin_remove(msg: Message, args: List[str]) -> None:
    if len(args) < 2:
        await msg.answer("❌ Укажите ID пользователя", parse_mode=ParseMode.HTML)
        return
    user_id = args[1]
    author_id = getattr(msg.author, "id", None)
    if user_id == author_id:
        await msg.answer("❌ Нельзя удалить самого себя из администраторов",
                         parse_mode=ParseMode.HTML)
        return
    if user_id in admin_manager._static_ids:  # статические задаются в config.py
        await msg.answer(f"❌ {user_id} задан в config.py и не может быть удалён из бота",
                         parse_mode=ParseMode.HTML)
        return
    if admin_manager.remove_admin(user_id):
        await state_manager.save()
        await msg.answer(f"✅ Пользователь {user_id} удален из администраторов",
                         parse_mode=ParseMode.HTML)
    else:
        await msg.answer(f"❌ Пользователь {user_id} не является администратором",
                         parse_mode=ParseMode.HTML)


_COMMAND_HANDLERS = {
    "/help": cmd_help,
    "/start": cmd_help,
    "/info": cmd_info,
    "/health": cmd_health,
    "/ping": cmd_ping,
    "/whoami": cmd_whoami,
    "/token_info": cmd_token_info,
    "/register": cmd_register,
    "/unregister": cmd_unregister,
    "/channels": cmd_channels,
    "/channel_edit": cmd_channel_edit,
    "/default": cmd_default,
    "/admins": cmd_admins,
    "/admin_add": cmd_admin_add,
    "/admin_remove": cmd_admin_remove,
}


@router.message()
async def handle_messages(msg: Message) -> None:
    """Обработка входящих сообщений."""
    if is_duplicate(getattr(msg, "message_id", None)):
        return

    chat_id = msg.chat.chat_id
    author_id = getattr(msg.author, "id", "unknown")
    raw_text = msg.text or ""

    chat_log.info(f"📨 Сообщение от {author_id}")
    chat_log.info(f"   Чат: {shorten(chat_id)} ({msg.chat.chat_title or '—'})")
    chat_log.info(f"   Текст: {raw_text[:200]}")

    # Текст может прийти с невидимыми символами или HTML-сущностями:
    # «/channels&nbsp;2» иначе не распознаётся как команда вообще.
    text = normalize_command_text(raw_text)

    if not text.startswith("/"):
        return

    args = text.split()
    command = args[0].lower()

    handler = _COMMAND_HANDLERS.get(command)
    if handler is None:
        return

    logger.info(f"🎯 Команда: {command} от {author_id}")
    try:
        await handler(msg, args)
    except Exception as exc:
        error_log.error(f"❌ Ошибка команды {command}: {exc}", exc_info=exc)
        try:
            await msg.answer(f"❌ Ошибка: {str(exc)[:200]}", parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ============================================================================
# ВЕБХУК
# ============================================================================

def _first(data: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return None


def parse_alert(data: Dict[str, Any], query_channel: Optional[str]) -> Dict[str, Any]:
    """Извлекает из тела вебхука канал, статус, ключ инцидента и текст."""
    subject = _first(data, "subject", "Subject", "SUBJECT", "trigger", "Trigger", "title", "Title") or ""
    message = _first(data, "message", "Message", "MESSAGE", "text", "Text")

    alerts = data.get("alerts")
    if not message and isinstance(alerts, list) and alerts:
        first_alert = alerts[0] if isinstance(alerts[0], dict) else {}
        message = first_alert.get("annotations", {}).get("summary") or first_alert.get("annotations", {}).get("description")
        if not subject:
            subject = first_alert.get("labels", {}).get("alertname") or ""

    status = (_first(data, "status", "Status", "state") or "").upper()
    when = datetime.now().strftime("%H:%M:%S")

    if subject:
        final_message = f"{subject}\n{message}" if message else subject
    else:
        final_message = message or ""

    channel = query_channel or _first(data, "channel", "Channel", "CHANNEL")
    host = _first(data, "host", "Host", "hostname") or ""
    key_source = f"{host}|{subject}|{message or ''}"
    incident_key = hashlib.sha1(key_source.encode("utf-8", "ignore")).hexdigest()[:24]

    return {
        "channel": channel,
        "subject": subject,
        "message": message,
        "status": status,
        "final_message": final_message,
        "incident_key": incident_key,
        "host": host,
        "received_at": when,
        "payload": data,
    }


async def handle_webhook(request: web.Request) -> web.Response:
    started = time.perf_counter()
    webhook_log.info(f"📩 Получен вебхук от {request.remote or '—'}")

    try:
        if request.content_type == "application/json":
            data = await request.json()
        else:
            data = dict(await request.post())

        if not isinstance(data, dict):
            raise ValueError("тело запроса должно быть объектом JSON")

        query_channel = request.query.get("channel") or request.query.get("Channel")
        alert = parse_alert(data, query_channel)

        if not alert["final_message"]:
            webhook_log.warning("⚠️ Отклонён: отсутствует поле message")
            return web.json_response({"error": "Missing required field: message"}, status=400)

        channel = alert["channel"]
        target_chat_id: Optional[str]
        if channel:
            target_chat_id = state_manager.get_channel_chat_id(channel)
            if not target_chat_id:
                webhook_log.warning(f"⚠️ Канал '{channel}' не найден")
                return web.json_response({"error": f"Channel '{channel}' not found"}, status=404)
        elif state_manager.default_chat:
            target_chat_id = state_manager.default_chat
            channel = "default"
        else:
            webhook_log.warning("⚠️ Отклонён: не задан ни канал, ни чат по умолчанию")
            return web.json_response({"error": "No target channel"}, status=400)

        # Текст уведомления приходит извне (Zabbix, Grafana, Alertmanager):
        # угловые скобки и амперсанды обязаны быть экранированы, иначе сервер
        # примет их за HTML-теги. Переводы строк даём через <br>.
        icon = get_channel_icon(channel) if channel else ""
        body_lines = [line for line in str(alert["final_message"]).split("\n")]
        body_html = "<br>".join(safe_text(line) for line in body_lines)
        text = f"{icon} {body_html}" if icon else body_html

        webhook_log.info(f"   Статус: {alert['status'] or '—'}")
        webhook_log.info(f"   Триггер: {(alert['subject'] or alert['final_message'])[:120]}")
        webhook_log.info(f"   📢 Канал: '{channel}'")

        ok, error = await deliver_message(target_chat_id, text, channel)
        elapsed = time.perf_counter() - started

        if not ok:
            # Relay не должен терять уведомления из-за недоступности TrueConf:
            # складываем в durable-очередь и подтверждаем приём, чтобы отправитель
            # не считал уведомление потерянным.
            queued = await outbox.put(
                chat_id=target_chat_id,
                text=text,
                channel=channel,
                incident_key=alert["incident_key"],
                status=alert["status"],
                collapse=OUTBOX_COLLAPSE,
            )
            if queued is not None:
                webhook_log.warning(
                    f"   📦 Не доставлено за {elapsed:.3f}с ({error}); "
                    f"поставлено в очередь ({len(outbox)} в ожидании)"
                )
                await state_manager.increment("webhooks_queued")
                return web.json_response(
                    {
                        "status": "queued",
                        "channel": channel,
                        "queue_size": len(outbox),
                        "elapsed_ms": round(elapsed * 1000),
                    },
                    status=202,
                )

            webhook_log.error(f"   ❌ Не доставлено и не поставлено в очередь: {error}")
            return web.json_response(
                {"status": "error", "error": error, "retry": True},
                status=503,
            )

        await state_manager.increment("webhooks_received")
        if metrics is not None:
            metrics.record_channel_event(channel)
        webhook_log.info(f"   ✅ Уведомление отправлено за {elapsed:.3f}с")

        await _track_incident(alert, target_chat_id, channel)

        # Связь есть — заодно подтолкнём очередь, не дожидаясь фонового таймера
        if outbox is not None and len(outbox) > 0:
            asyncio.create_task(flush_outbox())

        return web.json_response({"status": "ok", "channel": channel, "elapsed_ms": round(elapsed * 1000)})

    except Exception as exc:
        error_log.error(f"❌ Ошибка обработки вебхука: {exc}", exc_info=exc)
        return web.json_response({"error": str(exc)}, status=500)


async def _track_incident(alert: Dict[str, Any], chat_id: str, channel: Optional[str]) -> None:
    """История инцидентов: запоминаем проблему, при решении — удаляем сообщение."""
    status = alert.get("status") or ""
    key = alert["incident_key"]

    is_resolved = status in {"RESOLVED", "OK", "RECOVERY", "RESOLVE"}
    is_problem = status in {"PROBLEM", "FIRING", "ALERT"}

    if not (is_resolved or is_problem):
        return

    if is_problem:
        history_log.info(f"🆘 Ошибка сохранена: {key}")
        await state_manager.remember_error(key, "", channel)
        return

    record = await state_manager.pop_error(key)
    if not record:
        history_log.info(f"✅ Ошибка отмечена как решенная: {key}")
        return

    message_id = record.get("message_id")
    settings = state_manager.settings
    if not settings.get("delete_messages_enabled") or not message_id:
        history_log.info(f"✅ Ошибка отмечена как решенная: {key}")
        return

    try:
        opened = datetime.fromisoformat(record.get("opened_at", ""))
        age_hours = (datetime.now() - opened).total_seconds() / 3600
    except Exception:
        age_hours = 0.0

    threshold = float(settings.get("error_delete_threshold_hours", 24) or 24)
    if age_hours > threshold:
        history_log.info(f"🕒 Ошибка {key}: возраст {age_hours:.1f}ч > порога {threshold}ч — сообщение оставляем")
        return

    if bot is None:
        history_log.warning(f"⚠️ Ошибка {key}: SDK-бот недоступен, сообщение не удалено")
        return

    delete_log.info(f"🗑️ Запрос на удаление {shorten(message_id)} (ключ: {key[:32]})")
    try:
        await asyncio.wait_for(bot.remove_message(message_id, for_all=True), timeout=SEND_TIMEOUT)
        delete_log.info(f"✅ Сообщение {shorten(message_id)} удалено")
    except Exception as exc:
        delete_log.warning(f"⚠️ Не удалось удалить {shorten(message_id)}: {type(exc).__name__}: {exc}")


# ============================================================================
# ВЕБ-СЕРВЕР И АДМИН-ПАНЕЛЬ
# ============================================================================

async def api_status(request: web.Request) -> web.Response:
    health = runner.health() if runner else {}
    metadata = state_manager.metadata if state_manager else {}
    remaining = token_manager.remaining_seconds() if token_manager else None

    return web.json_response({
        "version": VERSION,
        "health": health,
        "stats": {
            "version": VERSION,
            "channels": len(state_manager.notification_channels) if state_manager else 0,
            "messages_sent": metadata.get("messages_sent", 0),
            "messages_failed": metadata.get("messages_failed", 0),
            "webhooks_received": metadata.get("webhooks_received", 0),
            "webhooks_queued": metadata.get("webhooks_queued", 0),
            "process_started": start_time.isoformat(timespec="seconds") if start_time else None,
        },
        "outbox": outbox.stats() if outbox is not None else {},
        "outbox_preview": outbox.preview(15) if outbox is not None else [],
        "token": {
            "valid": bool(token_manager and token_manager.is_token_valid()),
            "expires_at": token_manager.expires_at.isoformat() if token_manager and token_manager.expires_at else None,
            "remaining_hours": (remaining / 3600) if remaining else None,
        },
        "events": runner.recent_events(30) if runner else [],
    })


async def api_channels(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response({
            "channels": state_manager.notification_channels,
            "default_chat": state_manager.default_chat,
        })

    if request.method == "POST":
        payload = await request.json()
        name = str(payload.get("name", "")).strip().lower()
        chat_id = str(payload.get("chat_id", "")).strip()
        chat_title = str(payload.get("chat_title", "") or state_manager.default_chat or "").strip() or None
        if not name or not chat_id:
            return web.json_response({"error": "name и chat_id обязательны"}, status=400)
        if not name.replace("-", "").replace("_", "").isalnum():
            return web.json_response(
                {"error": "имя канала: только буквы, цифры, дефис и подчёркивание"}, status=400
            )
        await state_manager.add_channel(name, chat_id, created_by="webui", chat_title=chat_title)
        await state_manager.save()
        return web.json_response({"status": "ok", "name": name})

    return web.json_response({"error": "method not allowed"}, status=405)


def _valid_channel_name(name: str) -> bool:
    """Имя канала: буквы, цифры, дефис, подчёркивание."""
    return bool(name) and name.replace("-", "").replace("_", "").isalnum()


async def api_channel_item(request: web.Request) -> web.Response:
    """
    Операции над конкретным каналом.

        PUT    — изменить chat_id, название чата или имя канала
        DELETE — удалить канал
    """
    name = request.match_info["name"]

    if request.method == "PUT":
        payload = await request.json()
        if name not in state_manager.notification_channels:
            return web.json_response({"error": "канал не найден"}, status=404)

        new_name = str(payload.get("new_name", "") or "").strip().lower()
        chat_id = payload.get("chat_id")
        chat_title = payload.get("chat_title")

        if new_name and not _valid_channel_name(new_name):
            return web.json_response(
                {"error": "имя канала: только буквы, цифры, дефис и подчёркивание"}, status=400
            )
        if chat_id is not None and not str(chat_id).strip():
            return web.json_response({"error": "chat_id не может быть пустым"}, status=400)

        ok = await state_manager.update_channel(
            name,
            chat_id=str(chat_id) if chat_id is not None else None,
            chat_title=str(chat_title) if chat_title is not None else None,
            new_name=new_name or None,
        )
        if not ok:
            return web.json_response({"error": f"имя '{new_name}' уже занято"}, status=409)

        await state_manager.save()
        return web.json_response({"status": "ok", "name": new_name or name})

    if request.method == "DELETE":
        if await state_manager.remove_channel(name):
            await state_manager.save()
            return web.json_response({"status": "ok"})
        return web.json_response({"error": "канал не найден"}, status=404)

    return web.json_response({"error": "method not allowed"}, status=405)


async def api_admins(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response({
            "admins": [{"id": item, "static": admin_manager.is_static(item)} for item in admin_manager.get_admins()],
            "mode": admin_manager.mode,
        })

    if request.method == "POST":
        payload = await request.json()
        user_id = str(payload.get("user_id", "")).strip()
        if not user_id:
            return web.json_response({"error": "user_id обязателен"}, status=400)
        if not admin_manager.add_admin(user_id):
            return web.json_response({"error": "уже является администратором"}, status=400)
        await state_manager.save()
        return web.json_response({"status": "ok"})

    return web.json_response({"error": "method not allowed"}, status=405)


async def api_admin_delete(request: web.Request) -> web.Response:
    user_id = request.match_info["user_id"]
    if admin_manager.is_static(user_id):
        return web.json_response({"error": "администратор задан в config.py"}, status=400)
    if admin_manager.remove_admin(user_id):
        await state_manager.save()
        return web.json_response({"status": "ok"})
    return web.json_response({"error": "не найден"}, status=404)


async def api_settings(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.json_response({"settings": state_manager.settings})

    payload = await request.json()
    allowed = {
        "delete_messages_enabled": bool,
        "error_delete_threshold_hours": int,
        "error_history_retention_days": int,
        "max_message_length": int,
        "max_retries": int,
    }
    for key, caster in allowed.items():
        if key in payload:
            try:
                state_manager.settings[key] = caster(payload[key])
            except (TypeError, ValueError):
                return web.json_response({"error": f"некорректное значение {key}"}, status=400)
    state_manager.touch()
    await state_manager.save()
    return web.json_response({"status": "ok", "settings": state_manager.settings})


async def api_send(request: web.Request) -> web.Response:
    payload = await request.json()
    text = str(payload.get("text", "")).strip()
    channel = payload.get("channel") or None
    if not text:
        return web.json_response({"error": "text обязателен"}, status=400)

    if channel:
        chat_id = state_manager.get_channel_chat_id(channel)
        if not chat_id:
            return web.json_response({"error": f"канал '{channel}' не найден"}, status=404)
    else:
        chat_id = state_manager.default_chat
        if not chat_id:
            return web.json_response({"error": "чат по умолчанию не задан"}, status=400)

    started = time.perf_counter()
    ok, error = await deliver_message(chat_id, text, channel)
    latency = round((time.perf_counter() - started) * 1000)
    if not ok:
        return web.json_response({"error": error, "latency_ms": latency}, status=503)
    return web.json_response({"status": "ok", "latency_ms": latency})


async def api_outbox(request: web.Request) -> web.Response:
    if request.method == "GET":
        if outbox is None:
            return web.json_response({"error": "очередь не инициализирована"}, status=503)
        return web.json_response({
            "stats": outbox.stats(),
            "items": outbox.preview(int(request.query.get("limit", 50))),
        })

    if request.method == "POST":
        if outbox is None:
            return web.json_response({"error": "очередь не инициализирована"}, status=503)
        action = request.query.get("action", "flush")
        if action == "clear":
            removed = await outbox.clear()
            return web.json_response({"status": "ok", "cleared": removed})
        delivered = await flush_outbox()
        return web.json_response({"status": "ok", "delivered": delivered, "left": len(outbox)})

    return web.json_response({"error": "method not allowed"}, status=405)


async def api_reconnect(request: web.Request) -> web.Response:
    if runner is None:
        return web.json_response({"error": "бот не запущен"}, status=503)
    await runner.force_restart("webui")
    return web.json_response({"status": "ok"})


ALLOWED_LOG_FILES = {"bot.log", "chat.log", "delete.log", "error.log", "error_history.log", "webhook.log"}


async def handle_local_login(request: web.Request) -> web.Response:
    """POST /auth/local — вход по логину и паролю локального администратора."""
    if request.method == "GET":
        return web.HTTPFound("/login")
    return await auth_manager.handle_local_login(request)


async def api_local_admin(request: web.Request) -> web.Response:
    """
    Управление локальной учётной записью администратора.

    GET  — состояние (без хэша пароля)
    POST — смена пароля: {"current_password": "...", "new_password": "..."}
    """
    if auth_manager is None or auth_manager.local is None:
        return web.json_response({"error": "локальный вход не настроен"}, status=503)

    store = auth_manager.local

    if request.method == "GET":
        user = auth_manager.current_user(request)
        return web.json_response({
            "local_admin": store.stats(),
            "can_manage": bool(user and user.is_admin),
        })

    if request.method == "POST":
        payload = await request.json()
        current = str(payload.get("current_password", ""))
        new = str(payload.get("new_password", ""))
        if not current or not new:
            return web.json_response(
                {"error": "нужны current_password и new_password"}, status=400
            )
        ip = auth_manager._client_ip(request)
        ok, reason = store.change_password(current, new, ip)
        if not ok:
            return web.json_response({"error": reason}, status=400)
        await state_manager.save()
        return web.json_response({"status": "ok", "local_admin": store.stats()})

    return web.json_response({"error": "method not allowed"}, status=405)


async def api_diagnostics(request: web.Request) -> web.Response:
    """
    Данные из SDK для диагностики.

        GET /api/diagnostics?part=identity|chats|channels|limits|history
    """
    if sdk_inspector is None:
        return web.json_response({"error": "бот не запущен"}, status=503)

    part = request.query.get("part", "identity")

    if part == "identity":
        data = await sdk_inspector.identity()
    elif part == "chats":
        data = await sdk_inspector.chats(
            count=int(request.query.get("count", 50)),
            page=int(request.query.get("page", 1)),
        )
    elif part == "channels":
        data = await sdk_inspector.channel_health(
            state_manager.notification_channels,
            inspect_limit=int(request.query.get("limit", 12)),
        )
    elif part == "limits":
        data = await sdk_inspector.limits()
    elif part == "history":
        chat_id = request.query.get("chat_id") or state_manager.default_chat
        data = await sdk_inspector.history(chat_id, count=int(request.query.get("count", 5)))
    else:
        return web.json_response({"error": f"неизвестный раздел: {part}"}, status=400)

    return web.json_response({"part": part, "data": data})


async def metrics_collector(interval: float = 60.0, save_interval: float = 300.0) -> None:
    """
    Раз в interval секунд снимает состояние бота в историю метрик.

    На работу бота не влияет: только чтение счётчиков и запись в отдельный файл.
    """
    last_save = 0.0
    while True:
        try:
            await asyncio.sleep(interval)
            if metrics is None:
                continue

            health = runner.health() if runner else {}
            metadata = state_manager.metadata if state_manager else {}

            metrics.record_snapshot({
                "sent": metadata.get("messages_sent", 0),
                "queued": len(outbox) if outbox is not None else 0,
                "connected": bool(health.get("ws_connected")),
                "restarts": health.get("restarts", 0),
            })

            now = time.monotonic()
            if now - last_save >= save_interval:
                metrics.save()
                last_save = now
        except asyncio.CancelledError:
            if metrics is not None:
                metrics.save()
            break
        except Exception as exc:
            error_log.error(f"❌ Ошибка сбора метрик: {exc}", exc_info=exc)


async def api_metrics(request: web.Request) -> web.Response:
    """
    История метрик для графиков.

        GET /api/metrics?kind=history&hours=24
        GET /api/metrics?kind=days&limit=365
        GET /api/metrics?kind=summary
    """
    if metrics is None:
        return web.json_response({"error": "метрики не инициализированы"}, status=503)

    kind = request.query.get("kind", "history")
    if kind == "history":
        try:
            hours = int(request.query.get("hours", 24))
        except ValueError:
            hours = 24
        return web.json_response(metrics.history(hours))

    if kind == "days":
        try:
            limit = int(request.query.get("limit", 365))
        except ValueError:
            limit = 365
        return web.json_response(metrics.days(limit))

    if kind == "summary":
        return web.json_response(metrics.summary())

    return web.json_response({"error": f"неизвестный вид: {kind}"}, status=400)


async def api_logs(request: web.Request) -> web.Response:
    name = request.query.get("file", "bot.log")
    if name not in ALLOWED_LOG_FILES:
        return web.json_response({"error": "файл не разрешён"}, status=400)
    try:
        lines = max(10, min(int(request.query.get("lines", 200)), 2000))
    except ValueError:
        lines = 200

    path = Path(LOG_DIR) / name
    if not path.exists():
        return web.json_response({"content": "", "file": name})

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            tail = handle.readlines()[-lines:]
        return web.json_response({"file": name, "content": "".join(tail)})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_index(request: web.Request) -> web.Response:
    """Главная страница панели."""
    return web.Response(
        text=render_index(),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def handle_page(request: web.Request, page_key: str = "") -> web.Response:
    """Страница раздела (каналы, очередь, настройки и т.д.)."""
    key = page_key or request.match_info.get("page", "")
    if key not in PAGES:
        raise web.HTTPNotFound(text="Раздел не найден")
    return web.Response(
        text=render_page(key),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def handle_style(request: web.Request) -> web.Response:
    return web.Response(
        text=STYLE_CSS,
        content_type="text/css",
        charset="utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


async def handle_appjs(request: web.Request) -> web.Response:
    return web.Response(
        text=APP_JS,
        content_type="application/javascript",
        charset="utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


async def handle_logo(request: web.Request) -> web.Response:
    return web.Response(text=LOGO_SVG, content_type="image/svg+xml", charset="utf-8")


async def handle_favicon(request: web.Request) -> web.Response:
    return web.Response(text=FAVICON_SVG, content_type="image/svg+xml", charset="utf-8")


async def handle_health(request: web.Request) -> web.Response:
    """Liveness: процесс жив (для systemd/docker)."""
    return web.json_response({"status": "ok", "version": VERSION})


async def handle_ready(request: web.Request) -> web.Response:
    """Readiness: бот авторизован на сервере и может отправлять сообщения."""
    health = runner.health() if runner else {}
    ready = bool(health.get("ready"))
    return web.json_response(
        {"status": "ready" if ready else "not-ready", **health},
        status=200 if ready else 503,
    )


@web.middleware
async def webui_auth_middleware(request: web.Request, handler):
    """Авторизация панели: Keycloak SSO или статический токен."""
    if auth_manager is None:
        return await handler(request)

    denial = auth_manager.authorize(request)
    if denial is not None:
        return denial

    return await handler(request)


async def handle_me(request: web.Request) -> web.Response:
    """Текущий пользователь панели (для отрисовки шапки и прав)."""
    if auth_manager is None:
        return web.json_response({"authenticated": True, "auth_mode": "none"})

    mode = auth_manager.mode
    user = auth_manager.current_user(request)

    # режимы без пользовательской сессии: доступ уже подтверждён middleware
    if user is None:
        if mode == "none" or mode == "token":
            return web.json_response({
                "authenticated": True,
                "auth_mode": mode,
                "user": {
                    "name": "Сервисный доступ" if mode == "token" else "Без авторизации",
                    "username": "service-token" if mode == "token" else "anonymous",
                    "email": "",
                    "roles": ["admin"],
                    "is_admin": True,
                    "is_viewer": True,
                    "via": mode,
                },
            })
        return web.json_response({"authenticated": False, "auth_mode": mode})

    return web.json_response({
        "authenticated": True,
        "auth_mode": mode,
        "user": {
            "name": user.display,
            "username": user.username,
            "email": user.email,
            "roles": user.roles,
            "is_admin": user.is_admin,
            "is_viewer": user.is_viewer,
            "via": user.via,
        },
    })


async def build_web_app() -> web.Application:
    """Собирает aiohttp-приложение (используется и в тестах)."""
    app = web.Application(
        client_max_size=8 * 1024 * 1024,
        middlewares=[webui_auth_middleware],
    )

    app.router.add_get("/login", lambda r: auth_manager.handle_login_page(r))
    app.router.add_get("/auth/login", lambda r: auth_manager.handle_login(r))
    app.router.add_get("/auth/callback", lambda r: auth_manager.handle_callback(r))
    app.router.add_route("*", "/auth/local", handle_local_login)
    app.router.add_get("/auth/logout", lambda r: auth_manager.handle_logout(r))
    app.router.add_get("/api/me", handle_me)

    app.router.add_post("/webhook", handle_webhook)
    app.router.add_post("/zabbix-webhook", handle_webhook)
    app.router.add_post("/api/webhook", handle_webhook)

    app.router.add_get("/health", handle_health)
    app.router.add_get("/live", handle_health)
    app.router.add_get("/ready", handle_ready)

    app.router.add_get("/", handle_index)
    app.router.add_get("/admin", handle_index)

    # разделы панели (вынесены с главной страницы): свой маршрут на страницу,
    # ключ передаём через замыкание — match_info тут не нужен
    for page_key in PAGES:
        app.router.add_get(
            f"/{page_key}",
            partial(handle_page, page_key=page_key),
        )

    # статика панели (не требует входа: стили и скрипты нужны на странице логина)
    app.router.add_get("/static/style.css", handle_style)
    app.router.add_get("/static/app.js", handle_appjs)
    app.router.add_get("/static/logo.svg", handle_logo)
    app.router.add_get("/static/favicon.svg", handle_favicon)

    app.router.add_get("/api/status", api_status)
    app.router.add_route("*", "/api/channels", api_channels)
    app.router.add_route("*", "/api/channels/{name}", api_channel_item)
    app.router.add_route("*", "/api/admins", api_admins)
    app.router.add_delete("/api/admins/{user_id}", api_admin_delete)
    app.router.add_route("*", "/api/settings", api_settings)
    app.router.add_post("/api/send", api_send)
    app.router.add_post("/api/reconnect", api_reconnect)
    app.router.add_route("*", "/api/outbox", api_outbox)
    app.router.add_get("/api/logs", api_logs)
    app.router.add_route("*", "/api/local-admin", api_local_admin)
    app.router.add_get("/api/diagnostics", api_diagnostics)
    app.router.add_get("/api/metrics", api_metrics)
    return app


async def start_web_server() -> web.AppRunner:
    global web_port_actual

    app = await build_web_app()
    runner_app = web.AppRunner(app)
    await runner_app.setup()
    site = web.TCPSite(runner_app, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()
    web_port_actual = WEB_SERVER_PORT

    logger.info(f"🌐 Веб-сервер запущен на http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
    logger.info(f"   🩺 Health: /health (liveness), /ready (readiness)")
    logger.info(f"   🖥️  Панель управления: http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}/")
    return runner_app


# ============================================================================
# ЖИЗНЕННЫЙ ЦИКЛ
# ============================================================================

async def init_runtime_for_tests() -> None:
    """Инициализация менеджеров без обращения к сети (для test_smoke.py)."""
    global token_manager, state_manager, admin_manager, runner, start_time

    global outbox

    start_time = datetime.now()
    token_manager = TokenManager(TOKEN_CONFIG)
    token_manager.token = "test-token"
    token_manager.expires_at = datetime.now() + timedelta(days=1)

    state_manager = StateManager(cfg("STATE_FILE", "bot_state.json"), version=VERSION)
    outbox = Outbox(
        file_path=OUTBOX_FILE,
        max_size=OUTBOX_MAX_SIZE,
        ttl_hours=OUTBOX_TTL_HOURS,
        dedup_window=OUTBOX_DEDUP_WINDOW,
        enabled=OUTBOX_ENABLED,
    )
    global metrics
    metrics = MetricsStore(file_path=METRICS_FILE, enabled=METRICS_ENABLED)
    admin_manager = AdminManager(
        admin_ids=[item.strip() for item in str(cfg("ADMIN_IDS", "")).split(",") if item.strip()],
        mode=cfg("ADMIN_MODE", "strict"),
        state=state_manager,
    )
    global auth_manager
    local_store = LocalAdminStore(
        state_getter=lambda: state_manager.raw,
        state_setter=lambda data: state_manager.set_local_admin(data.get("local_admin", {})),
        username=LOCAL_ADMIN_USERNAME,
        password=LOCAL_ADMIN_PASSWORD or "test-local-password-123",
        enabled=LOCAL_ADMIN_ENABLED,
        initial_password_file=LOCAL_ADMIN_PASSWORD_FILE,
    )
    global sdk_inspector
    sdk_inspector = SdkInspector(lambda: bot)

    # В тестах режим задаётся явно, независимо от .env
    auth_manager = AuthManager(
        mode="none",
        sso=None,
        local=local_store,
        token=WEBUI_TOKEN,
        session_secret="test-session-secret",
    )
    runner = BotRunner(
        dispatcher=dp,
        token_manager=token_manager,
        server=TOKEN_CONFIG["server"],
        verify_ssl=VERIFY_SSL,
        sdk_timeout=SDK_TIMEOUT,
        ws_max_retries=WS_MAX_RETRIES,
        ws_max_delay=WS_MAX_DELAY,
        heartbeat_mode=HEARTBEAT_MODE,
        heartbeat_interval=max(2, min(HEARTBEAT_INTERVAL, 5)),
        watchdog_interval=1,
        idle_threshold=max(3, min(IDLE_THRESHOLD, 10)),
        probe_timeout=2,
        max_reconnect_attempts=MAX_RECONNECT_ATTEMPTS,
        reconnect_delay=1,
        max_reconnect_delay=5,
        on_bot_created=_publish_bot,
    )


async def check_tls(server: str, port: int, verify_ssl) -> Optional[str]:
    """
    Проверяет TLS-соединение с сервером до старта бота.

    Возвращает текст проблемы или None, если всё в порядке. Нужна потому, что
    токен часто берётся из кэша (bot_token.json), и первый реальный TLS-хендшейк
    происходит уже внутри SDK — ошибка выглядела бы как «connect-task завершилась».
    """
    import ssl as _ssl

    from trueconf.utils._ssl import _build_ssl_context

    try:
        context = _build_ssl_context(verify_ssl)
    except Exception as exc:
        return f"некорректная настройка VERIFY_SSL: {exc}"

    def _probe() -> Optional[str]:
        try:
            with socket.create_connection((server, port), timeout=10) as raw:
                with context.wrap_socket(raw, server_hostname=server):
                    return None
        except _ssl.SSLCertVerificationError as exc:
            reason = getattr(exc, "verify_message", None) or str(exc)
            return f"сертификат не прошёл проверку: {reason}"
        except _ssl.SSLError as exc:
            return f"ошибка TLS: {exc}"
        except OSError as exc:
            return f"нет соединения с {server}:{port}: {exc}"

    return await asyncio.get_running_loop().run_in_executor(None, _probe)


def _describe_verify_ssl(value) -> str:
    """Человекочитаемое описание режима проверки TLS."""
    if value is True:
        return "по системному хранилищу (truststore)"
    if value is False:
        return "⚠️ ОТКЛЮЧЕНА (VERIFY_SSL=false)"
    return f"по CA-бандлу {value}"


def _publish_bot(instance: Bot) -> None:
    """Актуализирует глобальную ссылку на SDK-бота после пересоздания соединения."""
    global bot
    bot = instance
    logger.debug("🔗 Ссылка на SDK-бота обновлена")


async def shutdown(reason: str = "manual") -> None:
    logger.info(f"🛑 Остановка бота ({reason})…")

    global web_runner, _flush_task, _metrics_task
    if _metrics_task is not None and not _metrics_task.done():
        _metrics_task.cancel()
        try:
            await _metrics_task
        except (asyncio.CancelledError, Exception):
            pass
        _metrics_task = None

    if metrics is not None:
        metrics.save()

    if _flush_task is not None and not _flush_task.done():
        _flush_task.cancel()
        try:
            await _flush_task
        except (asyncio.CancelledError, Exception):
            pass
        _flush_task = None

    if web_runner is not None:
        try:
            await web_runner.cleanup()
        except Exception as exc:
            logger.warning(f"⚠️ Ошибка остановки веб-сервера: {exc}")
        web_runner = None

    if runner is not None:
        try:
            await runner.stop()
        except Exception as exc:
            logger.warning(f"⚠️ Ошибка остановки соединения: {exc}")

    if token_manager is not None:
        await token_manager.stop()

    if state_manager is not None:
        await state_manager.save()

    logger.info("👋 Завершение работы")


async def main() -> None:
    global bot, state_manager, admin_manager, token_manager, runner, start_time, web_runner
    global outbox, _flush_task, metrics, _metrics_task

    start_time = datetime.now()

    metrics = MetricsStore(file_path=METRICS_FILE, enabled=METRICS_ENABLED)

    token_manager = TokenManager(TOKEN_CONFIG)
    state_manager = StateManager(cfg("STATE_FILE", "bot_state.json"), version=VERSION)
    state_manager._start_auto_save()
    outbox = Outbox(
        file_path=OUTBOX_FILE,
        max_size=OUTBOX_MAX_SIZE,
        ttl_hours=OUTBOX_TTL_HOURS,
        dedup_window=OUTBOX_DEDUP_WINDOW,
        enabled=OUTBOX_ENABLED,
    )
    admin_manager = AdminManager(
        admin_ids=[item.strip() for item in str(cfg("ADMIN_IDS", "")).split(",") if item.strip()],
        mode=cfg("ADMIN_MODE", "strict"),
        state=state_manager,
    )

    global auth_manager
    sso = None
    if WEBUI_AUTH in ("keycloak", "both"):
        sso = KeycloakSSO(
            server_url=SSO_CONFIG["server_url"],
            realm=SSO_CONFIG["realm"],
            client_id=SSO_CONFIG["client_id"],
            client_secret=SSO_CONFIG["client_secret"],
            redirect_uri=SSO_CONFIG["redirect_uri"]
            or f"{WEBUI_PUBLIC_URL.rstrip('/')}/auth/callback",
            admin_roles=SSO_CONFIG["admin_roles"],
            viewer_roles=SSO_CONFIG["viewer_roles"],
            local_admins=[item.strip() for item in str(cfg("ADMIN_IDS", "")).split(",") if item.strip()],
            session_ttl=SSO_CONFIG["session_ttl"],
            cookie_secure=SSO_CONFIG["cookie_secure"],
            session_secret=SSO_CONFIG["session_secret"],
            verify_ssl=VERIFY_SSL,
            scope=SSO_CONFIG["scope"],
        )
    local_store = LocalAdminStore(
        state_getter=lambda: state_manager.raw,
        state_setter=lambda data: state_manager.set_local_admin(data.get("local_admin", {})),
        username=LOCAL_ADMIN_USERNAME,
        password=LOCAL_ADMIN_PASSWORD,
        password_hash=LOCAL_ADMIN_PASSWORD_HASH,
        enabled=LOCAL_ADMIN_ENABLED,
        initial_password_file=LOCAL_ADMIN_PASSWORD_FILE,
    )
    auth_manager = AuthManager(
        mode=WEBUI_AUTH,
        sso=sso,
        local=local_store,
        token=WEBUI_TOKEN,
        session_ttl_seconds=SSO_CONFIG["session_ttl"],
        session_secret=SSO_CONFIG["session_secret"],
    )

    global sdk_inspector
    sdk_inspector = SdkInspector(lambda: bot)

    logger.info("=" * 64)
    logger.info(f"🚀 TrueConf Zabbix Relay Bot v{VERSION}")
    logger.info("=" * 64)
    logger.info(f"   🌐 Сервер: {TOKEN_CONFIG['server']} (порт {cfg('TRUECONF_PORT', 443)})")
    logger.info(f"   🔒 Проверка TLS: {_describe_verify_ssl(VERIFY_SSL)}")
    logger.info(f"   👤 Пользователь: {TOKEN_CONFIG['username']}")
    logger.info(f"   🔐 ADMIN_MODE: {admin_manager.mode}, администраторов: {len(admin_manager.admin_ids)}")
    logger.info(f"   💓 Heartbeat: {HEARTBEAT_MODE} (интервал {HEARTBEAT_INTERVAL}с, idle {IDLE_THRESHOLD}с)")
    logger.info(f"   🐕 Watchdog: каждые {WATCHDOG_INTERVAL}с, переподключений до сброса токена: {MAX_RECONNECT_ATTEMPTS}")
    logger.info(
        f"   ⏳ Переподключение: {RECONNECT_DELAY:.0f}с ×{RECONNECT_BACKOFF:g}, "
        f"потолок {RECONNECT_MAX_DELAY / 60:.0f} мин (с {RECONNECT_FAST_WINDOW / 60:.0f} мин простоя), "
        f"тихий режим через {QUIET_AFTER / 60:.0f} мин"
    )
    logger.info(f"   🔁 Retry отправки: {MAX_RETRIES} x {RETRY_DELAY}с, таймаут {SEND_TIMEOUT}с")
    logger.info(
        f"   📦 Очередь недоставленных: {'вкл' if OUTBOX_ENABLED else 'выкл'}, "
        f"файл {OUTBOX_FILE}, лимит {OUTBOX_MAX_SIZE}, TTL {OUTBOX_TTL_HOURS:.0f} ч"
    )
    logger.info(f"   🖥️  Вход в панель: {WEBUI_AUTH}"
                f"{', SSO' if auth_manager.sso_enabled else ''}"
                f"{', local-admin' if auth_manager.local_enabled else ''}")
    logger.info(f"   🗂️  Логи: {Path(LOG_DIR).resolve()}")
    logger.info("=" * 64)

    runner = BotRunner(
        dispatcher=dp,
        token_manager=token_manager,
        server=TOKEN_CONFIG["server"],
        verify_ssl=VERIFY_SSL,
        web_port=cfg("TRUECONF_PORT", None),
        sdk_timeout=SDK_TIMEOUT,
        ws_max_retries=WS_MAX_RETRIES,
        ws_max_delay=WS_MAX_DELAY,
        receive_unread=RECEIVE_UNREAD,
        skip_self=True,
        heartbeat_mode=HEARTBEAT_MODE,
        heartbeat_interval=HEARTBEAT_INTERVAL,
        watchdog_interval=WATCHDOG_INTERVAL,
        idle_threshold=IDLE_THRESHOLD,
        probe_timeout=PING_TIMEOUT,
        max_reconnect_attempts=MAX_RECONNECT_ATTEMPTS,
        reconnect_delay=RECONNECT_DELAY,
        max_reconnect_delay=RECONNECT_MAX_DELAY,
        reconnect_backoff=RECONNECT_BACKOFF,
        fast_window=RECONNECT_FAST_WINDOW,
        quiet_after=QUIET_AFTER,
        on_bot_created=_publish_bot,
    )

    # Веб-сервер поднимаем до попыток связи: панель и /health должны быть
    # доступны даже если сервер TrueConf сейчас на профилактике.
    web_runner = await start_web_server()

    tls_problem = await check_tls(
        TOKEN_CONFIG["server"], int(cfg("TRUECONF_PORT", 443) or 443), VERIFY_SSL
    )
    if tls_problem:
        error_log.error(
            f"🔒 TLS до {TOKEN_CONFIG['server']}: {tls_problem}\n"
            f"   Решение: VERIFY_SSL=/path/to/ca.pem либо VERIFY_SSL=false в .env"
        )
    else:
        logger.info("   🔒 TLS-соединение с сервером проверено")

    token = await token_manager.get_token()
    if not token:
        error_log.warning(
            "⚠️ Токен не получен — сервер, возможно, недоступен. "
            "Бот продолжит попытки в фоне (панель уже доступна)."
        )
    token_manager.start_auto_refresh()

    await runner.start()
    _flush_task = asyncio.create_task(
        outbox_flusher(OUTBOX_FLUSH_INTERVAL), name="outbox-flusher"
    )
    if metrics is not None and metrics.enabled:
        _metrics_task = asyncio.create_task(
            metrics_collector(METRICS_INTERVAL, METRICS_SAVE_INTERVAL),
            name="metrics-collector",
        )
    try:
        ready = await runner.wait_ready(timeout=60)
        if ready:
            logger.info("✅ Бот авторизован на сервере")
        else:
            logger.warning(
                "⚠️ Авторизация не завершена за 60 с — продолжаем попытки в фоне"
            )
    except Exception as exc:  # pragma: no cover - защита от неожиданностей
        logger.warning(f"⚠️ Бот ещё не авторизован: {exc}")
    bot = runner.bot

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_graceful_stop(s.name)))
        except (NotImplementedError, AttributeError, RuntimeError):
            signal.signal(sig, lambda s, f: asyncio.create_task(_graceful_stop("signal")))

    if runner.is_ready:
        logger.info("✅ Бот готов к работе")
    else:
        logger.info("⏳ Бот запущен, ожидает связи с сервером (см. /ready и панель)")
    logger.info("=" * 64)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown("finally")


async def _graceful_stop(reason: str) -> None:
    await shutdown(reason)
    task = asyncio.current_task()
    for pending in asyncio.all_tasks():
        if pending is not task:
            pending.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Программа завершена пользователем")
    except Exception as exc:
        error_log.critical(f"💥 Необработанная ошибка: {exc}", exc_info=exc)
