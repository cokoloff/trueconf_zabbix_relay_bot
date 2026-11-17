#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка модуля диагностики через SDK (на заглушках)."""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ["LOG_DIR"] = "logs_dg"
os.environ["STATE_FILE"] = "bs_dg.json"
os.environ["OUTBOX_FILE"] = "ob_dg.json"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_dg.txt"
os.environ["ADMIN_MODE"] = "strict"
os.environ["ADMIN_IDS"] = "admin@example.com"
os.environ.setdefault("WEBUI_AUTH", "none")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


class FakeChat:
    def __init__(self, chat_id, title, chat_type=6, unread=0):
        self.chat_id = chat_id
        self.title = title
        self.chat_type = chat_type
        self.unread_messages = unread
        self.last_message = None


class FakeParticipant:
    def __init__(self, user_id, role="ADMIN"):
        self.user_id = user_id
        self.role = role


class FakeBot:
    """Минимальная замена SDK-бота."""

    def __init__(self, me_id="bot@example.com", chats=None):
        self.me_id = me_id
        self.server_name = "server.example.com"
        self.server_version = "5.5.8"
        self._chats = chats or {}

    def health_check(self):
        return {"status": "authorized", "websocket_connected": True, "port": 443}

    async def get_chats(self, count=50, page=1):
        return type("R", (), {"chats": list(self._chats.values())})()

    async def get_chat_by_id(self, chat_id):
        if chat_id not in self._chats:
            raise ValueError("chat not found")
        return self._chats[chat_id]

    async def get_chat_participants(self, chat_id, page_size, page_number):
        if chat_id not in self._chats:
            raise ValueError("not found")
        return type("R", (), {"participants": [
            FakeParticipant(self.me_id, "ADMIN"),
            FakeParticipant("user@example.com", "OWNER"),
        ]})()

    async def get_file_info_upload_limits(self):
        ext = type("E", (), {"mode": "block", "list": ["brd"]})()
        return type("R", (), {"max_size": 1000000000, "extensions": ext})()

    async def get_chat_history(self, chat_id, count=5):
        if chat_id not in self._chats:
            raise ValueError("chat not found")
        msg = type("M", (), {
            "message_id": "m-1", "timestamp": 1700000000000,
            "author": type("A", (), {"id": self.me_id})(),
            "type": "TEXT",
        })()
        return type("R", (), {"messages": [msg]})()


async def main() -> int:
    from tcbot.sdkinfo import SdkInspector, _chat_type_name, _role_name

    print("1) Типы чатов и роли")
    check(_chat_type_name(6) == "групповой", "тип 6 — групповой", _chat_type_name(6))
    check(_chat_type_name("6") == "групповой", "строка тоже распознаётся")
    check(_chat_type_name(None) == "—", "None даёт прочерк")
    check(_role_name("OWNER") == "владелец", "роль OWNER переведена")
    check(_role_name(None) == "—", "пустая роль — прочерк")

    print("\n2) Нет бота")
    empty = SdkInspector(lambda: None)
    check((await empty.identity())["available"] is False, "identity без бота")
    check((await empty.chats())["chats"] == [], "chats без бота")
    check((await empty.limits())["available"] is False, "limits без бота")

    print("\n3) Идентификация")
    bot = FakeBot()
    inspector = SdkInspector(lambda: bot)
    ident = await inspector.identity()
    check(ident["available"] is True, "identify доступен")
    check(ident["me_id"] == "bot@example.com", "me_id получен")
    check(ident["server_version"] == "5.5.8", "версия сервера получена")
    check(ident["health"]["status"] == "authorized", "health получен")

    print("\n4) Список чатов")
    result = await inspector.chats()
    check(result["available"] is True, "chats доступен")
    check(isinstance(result["chats"], list), "список чатов — массив")

    print("\n5) Ограничения")
    limits = await inspector.limits()
    check(limits["max_size_mb"] == 953.7, "размер в МБ", str(limits.get("max_size_mb")))
    check(limits["extensions"] == ["brd"], "расширения получены")
    check(limits["extensions_mode"] == "block", "режим расширений")

    print("\n6) Проверка каналов")
    chats = {"chat-1": FakeChat("chat-1", "Рабочий чат")}
    bot2 = FakeBot(chats=chats)
    inspector2 = SdkInspector(lambda: bot2)
    channels = {
        "good": {"chat_id": "chat-1"},
        "broken": {"chat_id": "chat-missing"},
        "nochat": {"chat_id": ""},
    }
    health = await inspector2.channel_health(channels, inspect_limit=10)
    check(health["total"] == 3, "всего каналов 3", str(health.get("total")))
    check(health["problems"] == 2, "найдено 2 проблемы", str(health.get("problems")))

    items = {i["name"]: i for i in health["items"]}
    check(items["good"]["ok"] is True, "рабочий канал в порядке")
    check(items["good"]["title"] == "Рабочий чат", "название чата получено")
    check(items["good"]["participants"] == 2, "участники посчитаны")
    check(items["good"]["bot_is_member"] is True, "бот найден в чате")
    check(items["good"]["bot_role"] == "администратор", "роль бота определена")
    check(items["broken"]["ok"] is False, "несуществующий чат помечен")
    check("не найден" in items["broken"]["reason"], "причина указана", items["broken"]["reason"])
    check(items["nochat"]["ok"] is False, "пустой chat_id помечен")

    print("\n7) Лимит проверки")
    health2 = await inspector2.channel_health(channels, inspect_limit=1)
    limited = [i for i in health2["items"] if i["reason"] == "не проверялся (лимит)"]
    # Канал с пустым chat_id отсеивается раньше и в лимит не попадает
    check(len(limited) == 1, "каналы сверх лимита не проверяются", str(len(limited)))
    check(health2["inspected"] == 1, "счётчик проверенных учитывает лимит",
          str(health2.get("inspected")))
    # Непроверенные по лимиту не считаются проблемой: остаётся только
    # канал с пустым chat_id (он отсеивается до проверки лимита)
    check(health2["problems"] == 1,
          "непроверенные по лимиту не считаются проблемой",
          str(health2.get("problems")))

    print("\n8) История чата")
    history = await inspector2.history("chat-1", count=5)
    check(history["available"] is True, "история доступна")
    check(history["count"] == 1, "сообщения получены")
    check(history["messages"][0]["author"] == "bot@example.com", "автор указан")

    hist_bad = await inspector2.history("chat-missing")
    check(hist_bad["available"] is False, "ошибка истории обработана")

    print("\n9) API панели")
    from test_smoke import install_stub_sdk

    install_stub_sdk()
    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    await app.init_runtime_for_tests()
    app.sdk_inspector = SdkInspector(lambda: None)

    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/diagnostics")
        html = await resp.text()
        check(resp.status == 200, "страница диагностики отдаётся")
        for marker in ("diag-channels", "diag-chats", "diag-limits", "diag-identity"):
            check(marker in html, f"элемент {marker} присутствует")

        for part in ("identity", "chats", "channels", "limits"):
            resp = await client.get(f"/api/diagnostics?part={part}")
            check(resp.status == 200, f"API {part} отвечает", str(resp.status))

        resp = await client.get("/api/diagnostics?part=bogus")
        check(resp.status == 400, "неизвестный раздел → 400", str(resp.status))
    finally:
        await client.close()

    import shutil

    for name in ("logs_dg", "bs_dg.json", "ob_dg.json", "la_dg.txt"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    print()
    if FAILED:
        print(f"❌ Провалено: {len(FAILED)}")
        for item in FAILED:
            print(f"   • {item}")
        return 1
    print("✅ Проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
