#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка редактирования каналов: state, API, команды бота."""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ.setdefault("LOG_DIR", "logs_cht")
os.environ.setdefault("STATE_FILE", "bs_cht.json")
os.environ.setdefault("OUTBOX_FILE", "ob_cht.json")
os.environ["DELIVERED_FILE"] = "dl_test.json"
os.environ.setdefault("LOCAL_ADMIN_PASSWORD_FILE", "la_cht.txt")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


class FakeMessage:
    def __init__(self, author_id="admin@x"):
        self.out = []
        self.author = type("A", (), {"id": author_id})()
        self.chat = type("C", (), {"chat_id": "chat-1", "chat_title": "Чат"})()

    async def answer(self, text, parse_mode=None):
        self.out.append(text)

    @property
    def last(self):
        return self.out[-1] if self.out else ""


async def main() -> int:
    from test_smoke import install_stub_sdk

    install_stub_sdk()

    import bot_multy as app
    from tcbot.markup import plain_text

    await app.init_runtime_for_tests()
    app.admin_manager.add_admin("admin@x")

    print("1) Изменение chat_id")
    await app.state_manager.add_channel("testch", "old-chat-id", created_by="tester")
    ok = await app.state_manager.update_channel("testch", chat_id="new-chat-id")
    check(ok, "update_channel вернул True")
    check(app.state_manager.notification_channels["testch"]["chat_id"] == "new-chat-id",
          "chat_id изменён")
    check("updated_at" in app.state_manager.notification_channels["testch"],
          "проставлено время изменения")

    print("\n2) Изменение названия")
    await app.state_manager.update_channel("testch", chat_title="Новое название")
    check(app.state_manager.notification_channels["testch"]["chat_title"] == "Новое название",
          "название изменено")

    print("\n3) Переименование")
    ok = await app.state_manager.update_channel("testch", new_name="renamed")
    check(ok, "переименование выполнено")
    check("renamed" in app.state_manager.notification_channels, "новое имя есть")
    check("testch" not in app.state_manager.notification_channels, "старое имя убрано")

    print("\n4) Конфликты и ошибки")
    await app.state_manager.add_channel("taken", "chat-x")
    ok = await app.state_manager.update_channel("renamed", new_name="taken")
    check(not ok, "переименование в занятое имя отклонено")
    ok = await app.state_manager.update_channel("nonexistent", chat_id="x")
    check(not ok, "несуществующий канал отклонён")

    print("\n5) Команда /channels — компактный вид")
    for i in range(20):
        await app.state_manager.add_channel(f"ch{i:02d}", f"chat-id-{i:03d}")
    msg = FakeMessage()
    await app.cmd_channels(msg, ["/channels"])
    text = plain_text(msg.last)
    check("стр. 1/" in text, "показана нумерация страниц", text[:60])
    check("Каналы (" in text, "показано общее количество")
    lines = [l for l in text.split("\n") if " — " in l]
    check(len(lines) <= 15, "на странице не больше 15 каналов", str(len(lines)))
    check("Chat ID:" not in text, "нет подробностей в списке")

    print("\n6) Пагинация в боте")
    msg2 = FakeMessage()
    await app.cmd_channels(msg2, ["/channels", "2"])
    text2 = plain_text(msg2.last)
    check("стр. 2/" in text2, "вторая страница открывается", text2[:40])
    check("не найден" not in text2, "число не трактуется как имя канала")

    print("\n7) Карточка одного канала")
    msg3 = FakeMessage()
    await app.cmd_channels(msg3, ["/channels", "ch05"])
    text3 = plain_text(msg3.last)
    check("Chat ID:" in text3, "карточка показывает chat_id")
    check("/channel_edit" in text3, "подсказывает команду редактирования")

    print("\n8) /channel_edit")
    msg4 = FakeMessage()
    await app.cmd_channel_edit(msg4, ["/channel_edit", "ch05", "chat_id", "brand-new-id"])
    check(app.state_manager.notification_channels["ch05"]["chat_id"] == "brand-new-id",
          "chat_id изменён командой")

    msg5 = FakeMessage()
    await app.cmd_channel_edit(msg5, ["/channel_edit", "ch05", "title", "Новый чат"])
    check(app.state_manager.notification_channels["ch05"]["chat_title"] == "Новый чат",
          "название изменено командой")

    msg6 = FakeMessage()
    await app.cmd_channel_edit(msg6, ["/channel_edit", "ch05", "name", "ch05_new"])
    check("ch05_new" in app.state_manager.notification_channels, "канал переименован командой")

    msg7 = FakeMessage()
    await app.cmd_channel_edit(msg7, ["/channel_edit", "ch05_new", "name", "ch01"])
    check("уже существует" in plain_text(msg7.last), "конфликт имён обработан")

    msg8 = FakeMessage()
    await app.cmd_channel_edit(msg8, ["/channel_edit", "ch05_new", "bogus", "x"])
    check("Неизвестное поле" in plain_text(msg8.last), "неизвестное поле отклонено")

    msg9 = FakeMessage()
    await app.cmd_channel_edit(msg9, ["/channel_edit"])
    check("Формат" in plain_text(msg9.last), "без аргументов показана подсказка")

    print("\n9) Устойчивость разбора аргументов")
    from bot_multy import normalize_command_text, _clean_arg, _as_page_number

    variants = {
        "/channels 2": "обычный пробел",
        "/channels&nbsp;2": "HTML-сущность nbsp",
        "/channels&#160;2": "HTML-сущность &#160;",
        "/channels\u00a02": "неразрывный пробел",
        "/channels\u200b2": "zero-width пробел",
        "/channels 2\u200b": "zero-width в конце",
        "/channels\u202f2": "узкий неразрывный пробел",
        "/channels  2": "двойной пробел",
    }
    for raw, label in variants.items():
        normalized = normalize_command_text(raw)
        parts = normalized.split()
        is_page = len(parts) > 1 and _as_page_number(_clean_arg(parts[1])) == 2
        check(is_page, f"{label}: распознаётся как страница", f"{raw!r} -> {normalized!r}")

    check(normalize_command_text("/channels 2") == "/channels 2", "обычный текст не меняется")
    check(_as_page_number(_clean_arg("2")) == 2, "число распознаётся")
    check(_as_page_number(_clean_arg("abc")) is None, "имя не считается числом")
    check(_as_page_number(_clean_arg("ch01")) is None, "имя с цифрами не считается числом")

    print("\n10) Команда через обработчик сообщений")
    for raw in ("/channels", "/channels 2"):
        msgc = FakeMessage()
        msgc.text = raw
        msgc.message_id = "msg-" + raw.replace("/", "").replace(" ", "-")
        msgc.chat = type("C", (), {"chat_id": "chat-1", "chat_title": "Чат"})()
        await app.handle_messages(msgc)
        text = plain_text(msgc.last)
        check(bool(msgc.out), f"{raw!r} даёт ответ")

    msg_page = FakeMessage()
    msg_page.text = "/channels 2"
    msg_page.message_id = "msg-page2"
    msg_page.chat = type("C", (), {"chat_id": "chat-1", "chat_title": "Чат"})()
    await app.handle_messages(msg_page)
    check("стр. 2/" in plain_text(msg_page.last), "открывается вторая страница",
          plain_text(msg_page.last)[:40])

    print("\n11) API")
    from aiohttp.test_utils import TestClient, TestServer

    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.put("/api/channels/ch02", json={"chat_title": "API title"})
        check(resp.status == 200, "PUT изменяет канал", str(resp.status))
        check(app.state_manager.notification_channels["ch02"]["chat_title"] == "API title",
              "изменение применилось")

        resp = await client.put("/api/channels/ch02", json={"new_name": "ch03"})
        check(resp.status == 409, "конфликт имён → 409", str(resp.status))

        resp = await client.put("/api/channels/ghost", json={"chat_title": "x"})
        check(resp.status == 404, "несуществующий → 404", str(resp.status))

        resp = await client.put("/api/channels/ch02", json={"new_name": "bad name!"})
        check(resp.status == 400, "недопустимое имя → 400", str(resp.status))

        resp = await client.put("/api/channels/ch02", json={"chat_id": ""})
        check(resp.status == 400, "пустой chat_id → 400", str(resp.status))

        resp = await client.delete("/api/channels/ch02")
        check(resp.status == 200, "DELETE работает", str(resp.status))
        check("ch02" not in app.state_manager.notification_channels, "канал удалён")

        print("\n12) Чат по умолчанию")
        resp = await client.get("/api/default-chat")
        data = await resp.json()
        check(resp.status == 200, "GET /api/default-chat отвечает", str(resp.status))
        check("chat_id" in data, "в ответе есть chat_id")
        check("channels_using" in data, "в ответе есть счётчик каналов")
        check("options" in data, "в ответе есть список вариантов")

        options = data.get("options", [])
        check(len(options) >= 2, "варианты для выбора есть", str(len(options)))
        check(all("chat_id" in o and "channels" in o for o in options),
              "каждый вариант содержит chat_id и каналы")

        # Все варианты — из существующих каналов
        known = {
            info.get("chat_id")
            for info in app.state_manager.notification_channels.values()
            if info.get("chat_id")
        }
        unknown = [o["chat_id"] for o in options if o["chat_id"] not in known]
        check(not unknown, "все варианты соответствуют каналам", str(unknown))

        # Каналы варианта действительно ведут в этот чат
        mismatch = []
        for opt in options:
            for name in opt["channels"]:
                if app.state_manager.get_channel_chat_id(name) != opt["chat_id"]:
                    mismatch.append(name)
        check(not mismatch, "каналы варианта ведут именно в этот чат", str(mismatch))

        resp = await client.post(
            "/api/default-chat",
            json={"chat_id": "newdefaultchat1234567890", "chat_title": "Общий"},
        )
        data = await resp.json()
        check(resp.status == 200, "POST меняет чат", str(resp.status))
        check(data.get("chat_id") == "newdefaultchat1234567890",
              "новое значение применено", str(data.get("chat_id")))
        # Прежнее значение может быть None — если чат по умолчанию был не задан
        check("previous" in data, "прежнее значение возвращено в ответе",
              str(list(data.keys())))

        check(app.state_manager.default_chat == "newdefaultchat1234567890",
              "состояние обновлено", str(app.state_manager.default_chat))
        check(app.state_manager.raw.get("default_chat_title") == "Общий",
              "название сохранено",
              str(app.state_manager.raw.get("default_chat_title")))

        resp = await client.get("/api/default-chat")
        data = await resp.json()
        check(data.get("chat_id") == "newdefaultchat1234567890",
              "значение сохранилось", str(data.get("chat_id")))

        # Слишком короткий идентификатор отклоняется
        resp = await client.post("/api/default-chat", json={"chat_id": "abc"})
        check(resp.status == 400, "короткий chat_id → 400", str(resp.status))

        # Очистка
        resp = await client.post("/api/default-chat", json={"chat_id": ""})
        data = await resp.json()
        check(resp.status == 200, "очистка принята", str(resp.status))
        check(data.get("chat_id") is None, "значение очищено", str(data.get("chat_id")))
        check(app.state_manager.default_chat is None,
              "состояние очищено", str(app.state_manager.default_chat))

        # В уведомлении без канала используется чат по умолчанию
        await client.post(
            "/api/default-chat", json={"chat_id": "chat-by-default-123456"}
        )
        check(app.state_manager.default_chat == "chat-by-default-123456",
              "чат по умолчанию задан для проверки доставки")

        # Страница содержит элементы редактирования
        resp = await client.get("/channels")
        html_page = await resp.text()
        for marker in ("dc-edit", "dc-form", "dc-chat-id", "dc-clear", "default-chat"):
            check(marker in html_page, f"элемент {marker} на странице")

        resp = await client.get("/channels")
        html = await resp.text()
        check(resp.status == 200, "страница каналов отдаётся")
        for marker in ("ch-edit-form", "ch-pager", "ch-page-size", "edit-chat-id"):
            check(marker in html, f"элемент {marker} есть в разметке")
    finally:
        await client.close()

    import shutil

    for name in ("logs_cht", "bs_cht.json", "ob_cht.json", "la_cht.txt"):
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