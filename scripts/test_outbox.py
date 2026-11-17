#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка durable-очереди: недоставка, накопление, выгрузка, перезапуск."""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault("WEB_SERVER_PORT", "18090")
os.environ.setdefault("LOG_DIR", "logs_outbox")
os.environ.setdefault("STATE_FILE", "bot_state_outbox.json")
os.environ.setdefault("OUTBOX_FILE", "bot_outbox_test.json")
os.environ["DELIVERED_FILE"] = "dl_test.json"
os.environ.setdefault("OUTBOX_TTL_HOURS", "48")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


async def main() -> int:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from test_smoke import install_stub_sdk  # переиспользуем заглушки SDK

    install_stub_sdk()

    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    await app.init_runtime_for_tests()
    await app.runner.start()
    await app.runner.wait_ready(timeout=5)

    for path in (Path("bot_outbox_test.json"),):
        if path.exists():
            path.unlink()
    app.outbox = app.Outbox(file_path="bot_outbox_test.json", max_size=50, ttl_hours=48, dedup_window=0)

    aioapp = await app.build_web_app()
    client = TestClient(TestServer(aioapp))
    await client.start_server()
    try:
        bot = app.bot

        await client.post("/api/channels", json={"name": "obtest", "chat_id": "chat-ob"})

        print("\n1) Сервер недоступен — вебхуки не теряются")
        bot.authorized_event.clear()
        app.WEBHOOK_WAIT_TIMEOUT = 0.3
        payload = {
            "subject": "PROBLEM: CPU on host-1",
            "message": "CPU 95%",
            "status": "PROBLEM",
            "host": "host-1",
        }
        resp = await client.post("/webhook?channel=obtest", json=payload)
        body = await resp.json()
        check(resp.status == 202, "ответ 202 (принято в очередь)", str(resp.status))
        check(body.get("status") == "queued", "статус queued", str(body))
        check(len(app.outbox) == 1, "сообщение в очереди", str(len(app.outbox)))

        for i in range(3):
            await client.post(
                "/webhook?channel=obtest",
                json={"subject": f"PROBLEM: disk {i}", "message": f"disk {i}", "status": "PROBLEM", "host": f"h{i}"},
            )
        check(len(app.outbox) == 4, "накопились все 4 сообщения", str(len(app.outbox)))

        print("\n2) Очередь переживает перезапуск процесса")
        reloaded = app.Outbox(file_path="bot_outbox_test.json", max_size=50, ttl_hours=48, dedup_window=0)
        check(len(reloaded) == 4, "после перечитывания файла — те же 4 сообщения", str(len(reloaded)))
        persisted = json.loads(Path("bot_outbox_test.json").read_text(encoding="utf-8"))
        check(len(persisted["items"]) == 4, "файл на диске содержит 4 записи")

        print("\n3) Связь восстановилась — выгружаем")
        bot.authorized_event.set()
        bot.sent.clear()
        delivered = await app.flush_outbox()
        check(delivered == 4, "выгружено 4 сообщения", str(delivered))
        check(len(app.outbox) == 0, "очередь пуста", str(len(app.outbox)))
        check(len(bot.sent) == 4, "все 4 отправлены в TrueConf", str(len(bot.sent)))
        check(all(m["chat_id"] == "chat-ob" for m in bot.sent), "ушли в правильный чат")
        check(
            "CPU on host-1" in bot.sent[0]["text"] and "disk 2" in bot.sent[-1]["text"],
            "порядок FIFO сохранён",
        )

        print("\n4) Дедупликация")
        Path("bot_outbox_test.json").unlink(missing_ok=True)
        app.outbox = app.Outbox(file_path="bot_outbox_test.json", max_size=50, ttl_hours=48, dedup_window=60)
        bot.authorized_event.clear()
        dup = {"subject": "PROBLEM: same", "message": "same", "status": "PROBLEM", "host": "same"}
        r1 = await client.post("/webhook?channel=obtest", json=dup)
        r2 = await client.post("/webhook?channel=obtest", json=dup)
        check(r1.status == 202 and r2.status == 202, "оба запроса приняты")
        check(len(app.outbox) == 1, "дубликат не задублировал очередь", str(len(app.outbox)))

        print("\n5) Схлопывание по триггеру")
        Path("bot_outbox_test.json").unlink(missing_ok=True)
        app.outbox = app.Outbox(file_path="bot_outbox_test.json", max_size=50, ttl_hours=48, dedup_window=0)
        for value in ("CPU 90", "CPU 95", "CPU 99"):
            await app.outbox.put(
                chat_id="chat-ob",
                text=f"CPU {value}",
                channel="obtest",
                incident_key="same-trigger",
                status="PROBLEM",
                collapse=True,
            )
        check(len(app.outbox) == 1, "осталось одно (последнее) сообщение", str(len(app.outbox)))
        check("CPU 99" in app.outbox.items[0].text, "сохранено последнее значение")

        print("\n6) Переполнение очереди")
        Path("bot_outbox_test.json").unlink(missing_ok=True)
        app.outbox = app.Outbox(file_path="bot_outbox_test.json", max_size=5, ttl_hours=48, dedup_window=0)
        for i in range(8):
            await app.outbox.put(chat_id="c", text=f"msg {i}", channel="obtest")
        check(len(app.outbox) == 5, "размер ограничен 5", str(len(app.outbox)))
        check(app.outbox.dropped == 3, "3 старейших вытеснены", str(app.outbox.dropped))

        print("\n7) API панели")
        resp = await client.get("/api/outbox")
        data = await resp.json()
        check(resp.status == 200 and "stats" in data, "GET /api/outbox отдаёт статистику")
        resp = await client.post("/api/outbox?action=clear")
        data = await resp.json()
        check(resp.status == 200 and data.get("cleared") == 5, "очистка очереди работает", str(data))
        check(len(app.outbox) == 0, "после очистки очередь пуста")

        print("\n8) Статус содержит блок очереди")
        resp = await client.get("/api/status")
        data = await resp.json()
        check("outbox" in data and data["outbox"].get("size") == 0, "GET /api/status содержит outbox")
    finally:
        await client.close()
        await app.runner.stop()
        for path in ("bot_outbox_test.json", "bot_outbox_test.tmp"):
            p = Path(path)
            if p.exists():
                p.unlink()

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