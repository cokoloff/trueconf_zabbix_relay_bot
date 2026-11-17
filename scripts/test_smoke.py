#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальная проверка без сети и без установленного SDK.

Подменяет модуль trueconf заглушками, поднимает приложение и прогоняет:
    * импорт bot_multy (контракты SDK 1.5.x);
    * создание/удаление каналов, администраторов;
    * приём вебхуков Zabbix и Alertmanager (успех, отсутствие канала, 503 при обрыве);
    * health/ready эндпоинты и админ-API;
    * отсутствие утечек ссылки на SDK-бота после переподключения.

Запуск:  python test_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path

# запуск из любой папки: корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
from typing import Any, Dict, List

os.environ.setdefault("WEB_SERVER_PORT", "18080")
os.environ.setdefault("LOG_DIR", "logs_test")
os.environ.setdefault("STATE_FILE", "bot_state_test.json")
os.environ.setdefault("OUTBOX_FILE", "bot_outbox_test.json")
os.environ["DELIVERED_FILE"] = "dl_test.json"
os.environ.setdefault("TOKEN_FILE", "bot_token_test.json")
os.environ.setdefault("HEARTBEAT_MODE", "smart")

# Принудительно: тест не должен зависеть от .env родительского проекта,
# иначе ADMIN_IDS оттуда ломает проверки команд администратора
os.environ["ADMIN_IDS"] = "admin@example.com"
os.environ["ADMIN_MODE"] = "strict"

# Адрес администратора, который используют заглушки и ADMIN_IDS.
# Держим их согласованными: иначе команды отклоняются по правам.
TEST_ADMIN = "admin@example.com"

FAILED: List[str] = []


def check(condition: bool, title: str, detail: str = "") -> None:
    if condition:
        print(f"  ✅ {title}")
    else:
        print(f"  ❌ {title} {detail}")
        FAILED.append(title)


# ============================================================================
# ЗАГЛУШКИ SDK
# ============================================================================

class StubParseMode:
    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"


class StubAuthor:
    def __init__(self, author_id: str = "admin@example.com"):
        self.id = author_id


class StubChat:
    def __init__(self, chat_id: str = "chat-1", title: str = "Тестовый чат"):
        self.chat_id = chat_id
        self.chat_title = title


class StubMessage:
    def __init__(self, text: str, chat_id: str = "chat-1", author_id: str = "admin@example.com"):
        self.text = text
        self.chat = StubChat(chat_id)
        self.author = StubAuthor(author_id)
        self.message_id = f"msg-{abs(hash(text)) % 100000}"
        self.answers: List[tuple] = []

    async def answer(self, text: str, parse_mode: str = "markdown", **kwargs) -> Any:
        self.answers.append((text, parse_mode))
        return types.SimpleNamespace(message_id="sent-1")


class StubBot:
    instances: List["StubBot"] = []

    def __init__(self, server: str, token: str, **kwargs: Any):
        self.server = server
        self.token = token
        self.kwargs = kwargs
        self.connected_event = asyncio.Event()
        self.authorized_event = asyncio.Event()
        self.stopped_event = asyncio.Event()
        self.sent: List[Dict[str, Any]] = []
        # Удалённые сообщения: нужно для проверок истории инцидентов
        self.removed: List[str] = []
        self.fail_send = False
        self._stop = False
        self._connect_task = None
        StubBot.instances.append(self)

    async def run(self, handle_signals: bool = True) -> None:
        await asyncio.sleep(0.1)
        self.connected_event.set()
        self.authorized_event.set()
        while not self._stop:
            await asyncio.sleep(0.05)

    async def shutdown(self, timeout=None) -> None:
        self._stop = True
        self.connected_event.clear()
        self.authorized_event.clear()
        self.stopped_event.set()

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "authorized" if self.authorized_event.is_set() else "disconnected",
            "websocket_connected": self.connected_event.is_set(),
            "authorized": self.authorized_event.is_set(),
        }

    async def get_chats(self, count: int = 1, page: int = 1):
        if not self.authorized_event.is_set():
            raise ConnectionError("нет соединения")
        return types.SimpleNamespace(chats=[])

    async def send_message(self, chat_id: str, text: str, parse_mode: str = "text", **kwargs):
        if self.fail_send:
            raise ConnectionError("WS is not attached")
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return types.SimpleNamespace(chat_id=chat_id, message_id=f"srv-{len(self.sent)}", timestamp=0)

    async def remove_message(self, message_id: str, for_all: bool = False):
        self.removed.append(message_id)
        return types.SimpleNamespace()

    async def start(self) -> None:
        self._connect_task = asyncio.create_task(self.run())
        await asyncio.sleep(0.1)

    async def __call__(self, method, timeout: float = 10.0):
        return None


class StubDispatcher:
    def __init__(self, **kwargs: Any):
        self.handlers: List[Any] = []

    def include_router(self, r) -> None:
        pass

    def outer_middleware(self, m) -> None:
        pass


class StubRouter:
    def __init__(self, *args, **kwargs):
        self.handlers: List[Any] = []

    def message(self, *filters):
        def decorator(func):
            self.handlers.append(func)
            return func

        return decorator

    def include_router(self, r) -> None:
        pass


def install_stub_sdk() -> None:
    trueconf = types.ModuleType("trueconf")
    trueconf.Bot = StubBot
    trueconf.Dispatcher = StubDispatcher
    trueconf.Router = StubRouter
    trueconf.Message = StubMessage
    trueconf.ParseMode = StubParseMode
    trueconf.__version__ = "1.5.5-stub"

    exceptions = types.ModuleType("trueconf.exceptions")

    class TrueConfChatBotError(Exception):
        pass

    class WSConnectionError(TrueConfChatBotError, ConnectionError):
        pass

    class ApiErrorException(TrueConfChatBotError):
        def __init__(self, code: int = 0, detail: str = "api error", payload=None):
            super().__init__(f"[{code}] {detail}")

    class TextMessageTooLongError(TrueConfChatBotError):
        pass

    exceptions.TrueConfChatBotError = TrueConfChatBotError
    exceptions.WSConnectionError = WSConnectionError
    exceptions.ApiErrorException = ApiErrorException
    exceptions.TextMessageTooLongError = TextMessageTooLongError

    utils = types.ModuleType("trueconf.utils")

    def safe_split_text(text: str, limit: int = 4096) -> List[str]:
        if len(text) <= limit:
            return [text]
        return [text[i: i + limit] for i in range(0, len(text), limit)]

    utils.safe_split_text = safe_split_text

    sys.modules["trueconf"] = trueconf
    sys.modules["trueconf.exceptions"] = exceptions
    sys.modules["trueconf.utils"] = utils
    trueconf.exceptions = exceptions
    trueconf.utils = utils


# ============================================================================
# ТЕСТЫ
# ============================================================================

async def main() -> int:
    install_stub_sdk()

    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    print("\n1) Импорт приложения")
    check(app.VERSION.startswith("12"), "bot_multy импортируется, версия 12.x", app.VERSION)

    print("\n2) Инициализация")
    # Чистые файлы состояния: иначе данные прошлых прогонов
    # (очередь, реестр доставленного) ломают проверки
    for stale in ("dl_test.json", "bot_state_test.json",
                  "bot_outbox_test.json", "bot_token_test.json"):
        Path(stale).unlink(missing_ok=True)
    await app.init_runtime_for_tests()
    app._delivered_recent = {}
    app._delivered_dirty = False
    check(app.state_manager is not None, "StateManager создан")
    check(app.runner is not None, "BotRunner создан")

    await app.runner.start()
    ready = await app.runner.wait_ready(timeout=5)
    check(ready, "BotRunner сообщает готовность (авторизован)")
    check(app.bot is not None, "Глобальная ссылка на бота установлена")

    print("\n3) Веб-сервер и API")
    aioapp = await app.build_web_app()
    client = TestClient(TestServer(aioapp))
    await client.start_server()
    try:
        resp = await client.get("/health")
        check(resp.status == 200, "GET /health → 200", str(resp.status))

        resp = await client.get("/ready")
        check(resp.status == 200, "GET /ready → 200 при авторизации", str(resp.status))

        resp = await client.get("/")
        html = await resp.text()
        check(resp.status == 200 and "Панель" in html or "панель" in html.lower(), "GET / отдаёт админ-панель")

        resp = await client.get("/api/status")
        status = await resp.json()
        check(status["health"]["ready"] is True, "GET /api/status → ready=true")
        check(status["version"] == app.VERSION, "GET /api/status отдаёт версию")

        print("\n4) Каналы")
        resp = await client.post("/api/channels", json={"name": "unittest", "chat_id": "chat-unittest"})
        check(resp.status == 200, "POST /api/channels создаёт канал", str(resp.status))

        resp = await client.get("/api/channels")
        channels = await resp.json()
        check("unittest" in channels["channels"], "канал виден в списке")

        print("\n5) Администраторы")
        resp = await client.post("/api/admins", json={"user_id": "tester@example.com"})
        check(resp.status == 200, "POST /api/admins добавляет администратора", str(resp.status))
        check(app.admin_manager.is_admin("tester@example.com"), "AdminManager видит нового администратора")

        resp = await client.delete("/api/admins/tester@example.com")
        check(resp.status == 200, "DELETE /api/admins удаляет администратора", str(resp.status))

        print("\n6) Вебхуки")
        bot = app.bot
        bot.sent.clear()
        zabbix_payload = {
            "subject": "PROBLEM: CPU high on m1-cp-p-log",
            "message": "CPU Used 95",
            "status": "PROBLEM",
            "host": "m1-cp-p-log",
        }
        resp = await client.post("/webhook?channel=unittest", json=zabbix_payload)
        body = await resp.json()
        check(resp.status == 200 and body.get("status") == "ok", "Zabbix-вебхук доставлен", str(body))
        check(len(bot.sent) == 1 and "CPU Used 95" in bot.sent[0]["text"], "текст уведомления сформирован")
        check(bot.sent[0]["chat_id"] == "chat-unittest", "уведомление ушло в нужный чат")

        grafana_payload = {
            "status": "firing",
            "alerts": [
                {
                    "labels": {"alertname": "ESB PROXY"},
                    "annotations": {"summary": "proxy degraded"},
                }
            ],
        }
        resp = await client.post("/zabbix-webhook?channel=unittest", json=grafana_payload)
        check(resp.status == 200, "Alertmanager-вебхук доставлен", str(resp.status))

        resp = await client.post("/webhook?channel=unknown", json=zabbix_payload)
        check(resp.status == 404, "неизвестный канал → 404", str(resp.status))

        resp = await client.post("/webhook", json={"status": "PROBLEM"})
        check(resp.status == 400, "пустое сообщение → 400", str(resp.status))

        print("\n7) Недоставка при обрыве связи")
        # Реестр доставленного должен быть пуст: иначе сообщение считается
        # уже отправленным и в очередь не попадёт
        app._delivered_recent = {}
        app._delivered_dirty = False
        bot.authorized_event.clear()
        app.WEBHOOK_WAIT_TIMEOUT = 0.5
        resp = await client.post("/webhook?channel=unittest", json=zabbix_payload)
        check(resp.status == 202, "во время обрыва → 202 (принято в durable-очередь)", str(resp.status))
        body = await resp.json()
        check(body.get("status") == "queued", "ответ содержит status=queued", str(body))
        check(len(app.outbox) >= 1, "сообщение сохранено в очередь")
        bot.authorized_event.set()

        queued = await app.flush_outbox()
        check(queued >= 1, "после восстановления связи очередь выгружена", str(queued))

        print("\n8) Отправка сообщения из панели")
        bot.sent.clear()
        resp = await client.post("/api/send", json={"channel": "unittest", "text": "проверка из GUI"})
        check(resp.status == 200 and bot.sent, "POST /api/send отправляет сообщение", str(resp.status))

        print("\n9) Настройки")
        resp = await client.post("/api/settings", json={"max_message_length": 2500, "max_retries": 2})
        check(resp.status == 200, "POST /api/settings сохраняет настройки", str(resp.status))
        check(app.state_manager.settings["max_message_length"] == 2500, "настройка применена")

        print("\n10) Логи")
        resp = await client.get("/api/logs?file=bot.log&lines=5")
        check(resp.status == 200, "GET /api/logs читает bot.log", str(resp.status))
        resp = await client.get("/api/logs?file=../../etc/passwd")
        check(resp.status == 400, "чтение чужих файлов запрещено", str(resp.status))

        print("\n11) Перезапуск связи")
        old_bot = app.bot
        resp = await client.post("/api/reconnect")
        check(resp.status == 200, "POST /api/reconnect принят", str(resp.status))
        await asyncio.sleep(6)
        check(app.bot is not old_bot, "ссылка на бота обновлена после пересоздания")
        check(app.runner.is_ready, "соединение восстановлено после перезапуска")
    finally:
        await client.close()

    print("\n12) Команды бота")
    msg = StubMessage("/help", chat_id="chat-unittest")
    await app.handle_messages(msg)
    check(bool(msg.answers), "команда /help отвечает")

    msg_register = StubMessage("/register cmdtest", chat_id="chat-cmd")
    await app.handle_messages(msg_register)
    check("cmdtest" in app.state_manager.notification_channels, "команда /register создаёт канал")

    msg_default = StubMessage("/default", chat_id="chat-cmd-default")
    await app.handle_messages(msg_default)
    check(app.state_manager.default_chat == "chat-cmd-default", "команда /default меняет чат по умолчанию")

    msg_info = StubMessage("/info")
    await app.handle_messages(msg_info)
    check(bool(msg_info.answers) and "Uptime" in msg_info.answers[0][0], "команда /info отвечает")

    msg_denied = StubMessage("/register hack", chat_id="chat-x", author_id="stranger@example.com")
    await app.handle_messages(msg_denied)
    check(bool(msg_denied.answers) and "Доступ" in msg_denied.answers[0][0], "неадмин получает отказ")

    print("\n13) Длинные сообщения и разбиение")
    bot = app.bot
    bot.sent.clear()
    await app.deliver_message("chat-unittest", "я" * 9000)
    check(len(bot.sent) >= 3, "длинное сообщение разбито на части", str(len(bot.sent)))

    print("\n14) Остановка")
    await app.runner.stop()
    check(not app.runner.is_ready, "BotRunner остановлен")

    print()
    if FAILED:
        print(f"❌ Провалено проверок: {len(FAILED)}")
        for item in FAILED:
            print(f"   • {item}")
        return 1
    print("✅ Все проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))