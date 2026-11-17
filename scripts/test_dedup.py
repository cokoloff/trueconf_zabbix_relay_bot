#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка защиты от дублей доставки."""

import asyncio
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ["LOG_DIR"] = "logs_dd"
os.environ["STATE_FILE"] = "bs_dd.json"
os.environ["OUTBOX_FILE"] = "ob_dd.json"
os.environ["DELIVERED_FILE"] = "dl_dd.json"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_dd.txt"
os.environ["ADMIN_MODE"] = "strict"
os.environ["ADMIN_IDS"] = "admin@example.com"
os.environ.setdefault("WEBUI_AUTH", "none")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


def cleanup():
    import shutil

    for name in ("logs_dd", "bs_dd.json", "ob_dd.json", "dl_dd.json", "la_dd.txt"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


async def main() -> int:
    from test_smoke import install_stub_sdk

    install_stub_sdk()

    # test_smoke выставляет свой DELIVERED_FILE до импорта bot_multy —
    # возвращаем свой путь и обновляем константу уже импортированного модуля
    os.environ["DELIVERED_FILE"] = "dl_dd.json"
    import bot_multy as app

    app._DELIVERED_FILE = Path("dl_dd.json")

    for stale in ("dl_dd.json", "ob_dd.json", "bs_dd.json"):
        Path(stale).unlink(missing_ok=True)

    TEXT = "🌐 ❌ Проблема GRE-R201-FW-FI\nКоличество сессий более 150000"
    CHAT = "chat-test"

    print("1) Реестр доставленного")
    # Стартуем с пустого реестра: init читает файл с диска
    app._delivered_recent = {}
    app._delivered_dirty = False
    Path("dl_dd.json").unlink(missing_ok=True)
    await app.init_runtime_for_tests()
    app._delivered_recent = {}
    app._delivered_dirty = False
    check(app.was_delivered_recently(CHAT, TEXT) is False, "до отправки не считается доставленным")

    app.mark_delivered(CHAT, TEXT)
    check(app.was_delivered_recently(CHAT, TEXT) is True, "после отметки считается доставленным")
    check(Path("dl_dd.json").exists(), "реестр записан в файл")

    print("\n2) Разные сообщения не блокируются")
    check(app.was_delivered_recently(CHAT, TEXT + " v2") is False, "другой текст не блокируется")
    check(app.was_delivered_recently("other-chat", TEXT) is False, "другой чат не блокируется")

    print("\n3) Реестр переживает перезапуск")
    app._delivered_recent = {}
    app._delivered_dirty = False
    check(app.was_delivered_recently(CHAT, TEXT) is False, "после сброса памяти — пусто")
    app._load_delivered()
    check(app.was_delivered_recently(CHAT, TEXT) is True, "после загрузки — снова блокируется")
    check(len(app._delivered_recent) == 1, "запись восстановлена",
          str(len(app._delivered_recent)))

    print("\n4) Ключ доставки")
    key1 = app.delivery_key(CHAT, TEXT)
    key2 = app.delivery_key(CHAT, TEXT)
    key3 = app.delivery_key(CHAT, TEXT + "x")
    key4 = app.delivery_key("other", TEXT)
    check(key1 == key2, "одинаковые входные данные дают одинаковый ключ")
    check(key1 != key3, "разный текст — разный ключ")
    check(key1 != key4, "разный чат — разный ключ")

    print("\n5) Просроченные записи игнорируются")
    app._delivered_recent[app.delivery_key(CHAT, "old")] = time.time() - 10000
    check(app.was_delivered_recently(CHAT, "old") is False, "просроченная запись не блокирует")

    print("\n6) Повторный вебхук не дублирует отправку")
    await app.runner.start()
    await app.runner.wait_ready(timeout=5)
    await app.state_manager.add_channel("ddtest", "chat-dd", created_by="t")

    from aiohttp.test_utils import TestClient, TestServer

    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        bot = app.bot
        payload = {
            "subject": "Проблема GRE-R201-FW-FI",
            "message": "Количество сессий более 150000",
            "status": "PROBLEM",
        }

        resp = await client.post("/webhook?channel=ddtest", json=payload)
        check(resp.status == 200, "первый вебхук доставлен", str(resp.status))
        check(len(bot.sent) == 1, "одно сообщение в чате", str(len(bot.sent)))

        resp = await client.post("/webhook?channel=ddtest", json=payload)
        check(resp.status == 200, "повторный вебхук принят", str(resp.status))
        check(len(bot.sent) == 1, "повтор НЕ создал второе сообщение", str(len(bot.sent)))

        print("\n7) Сообщение из очереди не дублируется")
        sent_text = bot.sent[0]["text"]
        await app.outbox.put(
            chat_id="chat-dd", text=sent_text, channel="ddtest",
            incident_key="k1", status="PROBLEM",
        )
        check(len(app.outbox) == 1, "сообщение в очереди", str(len(app.outbox)))

        # Имитация рестарта: память пуста, реестр с диска
        app._delivered_recent = {}
        app._delivered_dirty = False
        app._load_delivered()

        before = len(bot.sent)
        delivered = await app.flush_outbox()
        check(delivered == 0, "из очереди ничего не отправлено", str(delivered))
        check(len(bot.sent) == before, "дубля в чате нет", str(len(bot.sent)))
        check(len(app.outbox) == 0, "очередь очищена", str(len(app.outbox)))
    finally:
        await client.close()
        await app.runner.stop()

    print("\n8) Вебхук отвечает 200 даже при сбое вспомогательных операций")
    from aiohttp.test_utils import TestClient, TestServer

    class BrokenMetrics:
        """Метрики падают так же, как падали на боевом сервере."""
        enabled = True

        def record_delivery(self, **kwargs):
            raise KeyError("latency_sum")

        def record_snapshot(self, snapshot):
            pass

        def save(self):
            pass

        @property
        def dirty(self):
            return False

    await app.runner.start()
    await app.runner.wait_ready(timeout=5)
    await app.state_manager.add_channel("dtest", "chat-d", created_by="t")

    client2 = TestClient(TestServer(await app.build_web_app()))
    await client2.start_server()
    try:
        bot = app.bot
        app._delivered_recent = {}
        app._delivered_dirty = False
        app.metrics = BrokenMetrics()

        payload = {"subject": "GRE-R201-FW-FI", "message": "Сессий 151272", "status": "PROBLEM"}
        before = len(bot.sent)
        resp = await client2.post("/webhook?channel=dtest", json=payload)
        check(resp.status == 200, "сбой метрик не ломает ответ", str(resp.status))
        check(len(bot.sent) == before + 1, "сообщение доставлено", str(len(bot.sent)))

        # Отправитель не должен повторять запрос: сообщение уже в чате
        resp = await client2.post("/webhook?channel=dtest", json=payload)
        check(resp.status == 200, "повтор тоже 200", str(resp.status))
        check(len(bot.sent) == before + 1, "повтор не создал дубль", str(len(bot.sent)))

        print("\n9) Сбой истории инцидентов не ломает ответ")
        app.metrics = None
        original_track = app._track_incident

        async def broken_track(*args, **kwargs):
            raise RuntimeError("state broken")

        app._track_incident = broken_track
        try:
            before = len(bot.sent)
            resp = await client2.post(
                "/webhook?channel=dtest",
                json={"subject": "Другой триггер", "message": "текст", "status": "PROBLEM"},
            )
            check(resp.status == 200, "сбой истории не ломает ответ", str(resp.status))
            check(len(bot.sent) == before + 1, "сообщение всё равно доставлено")
        finally:
            app._track_incident = original_track
    finally:
        await client2.close()
        await app.runner.stop()

    cleanup()
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
