#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка истории метрик для графиков и календаря."""

import asyncio
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ["LOG_DIR"] = "logs_met"
os.environ["STATE_FILE"] = "bs_met.json"
os.environ["OUTBOX_FILE"] = "ob_met.json"
os.environ["METRICS_FILE"] = "metrics_test.json"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_met.txt"
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

    for name in ("logs_met", "bs_met.json", "ob_met.json", "la_met.txt",
                 "metrics_test.json", "metrics_test.tmp"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


async def main() -> int:
    from tcbot.metrics import MetricsStore

    print("1) Снимки состояния")
    store = MetricsStore(file_path="metrics_test.json", enabled=True)

    # Первый снимок задаёт базу, прироста ещё нет
    store.record_snapshot({"sent": 100, "queued": 0, "connected": True, "restarts": 1})
    h = store.history(1)["points"]
    check(h[0]["sent"] == 0, "первый снимок без прироста", str(h[0]["sent"]))

    # Второй снимок: отправлено +5, связь была
    store._last_ts = time.time() - 60
    store.record_snapshot({"sent": 105, "queued": 2, "connected": True, "restarts": 1})
    h = store.history(1)["points"]
    check(h[-1]["sent"] == 5, "прирост отправленных", str(h[-1]["sent"]))
    check(h[-1]["queued"] == 2, "размер очереди зафиксирован", str(h[-1]["queued"]))
    # Процент считается от покрытия (фактически наблюдаемого времени),
    # поэтому при полной связи всегда 100%, независимо от длины интервала
    check(h[-1]["ws"] == 100, "связь 100% за интервал", str(h[-1]["ws"]))

    print("\n2) Отсутствие связи")
    # В том же часе уже была связь 60 с; добавляем 60 с без связи.
    # Процент считается от покрытия: 60 из 120 = 50%.
    store._last_ts = time.time() - 60
    store.record_snapshot({"sent": 105, "queued": 5, "connected": False, "restarts": 2})
    h = store.history(1)["points"]
    check(h[-1]["ws"] == 50, "половина интервала без связи → 50%", str(h[-1]["ws"]))
    check(h[-1]["restarts"] == 1, "перезапуск учтён", str(h[-1]["restarts"]))

    # Отдельная точка без связи на чистом store — 0%
    clean = MetricsStore(file_path="metrics_clean.json", enabled=True)
    clean._hourly = {}
    clean._last_snapshot = {"sent": 0, "restarts": 0, "queued": 0}
    clean._last_ts = time.time() - 60
    clean.record_snapshot({"sent": 0, "queued": 0, "connected": False, "restarts": 0})
    clean_h = clean.history(1)["points"]
    check(clean_h[-1]["ws"] == 0, "полное отсутствие связи → 0%", str(clean_h[-1]["ws"]))

    print("\n3) Ряды за период")
    history = store.history(24)
    check(len(history["points"]) == 24, "24 точки за сутки", str(len(history["points"])))
    check(all("label" in p for p in history["points"]), "у точек есть подписи")
    check(all("ts" in p for p in history["points"]), "у точек есть время")

    history6 = store.history(6)
    check(len(history6["points"]) == 6, "6 точек за 6 часов")

    check(len(store.history(1000)["points"]) <= 168, "период ограничен хранимым")

    print("\n4) События каналов")
    store.record_channel_event("network")
    store.record_channel_event("network")
    store.record_channel_event("zabbix")
    days = store.days(365)["days"]
    today = next((d for d in days if d["count"] >= 0), None)
    check(today is not None, "дневная запись создана")
    names = {c["name"]: c["count"] for c in today["by_channel"]}
    check(names.get("network") == 2, "network: 2 события", str(names))
    check(names.get("zabbix") == 1, "zabbix: 1 событие", str(names))
    check(today["channels"] == 2, "каналов учтено: 2", str(today["channels"]))

    print("\n5) Пустой канал не учитывается")
    before = len(store.days(365)["days"])
    store.record_channel_event(None)
    store.record_channel_event("")
    after = len(store.days(365)["days"])
    check(before == after, "None и пустая строка игнорируются")

    print("\n6) Сводка")
    summary = store.summary()
    for key in ("today_sent", "today_webhooks", "today_channels", "last24_sent"):
        check(key in summary, f"сводка содержит {key}")
    check(summary["last24_sent"] >= 5, "за сутки посчитано", str(summary["last24_sent"]))

    print("\n7) Сохранение и загрузка")
    store.save()
    check(Path("metrics_test.json").exists(), "файл создан")

    reloaded = MetricsStore(file_path="metrics_test.json", enabled=True)
    check(len(reloaded.history(24)["points"]) == 24, "история восстановлена")
    days2 = reloaded.days(365)["days"]
    check(any(d["channels"] == 2 for d in days2), "дневная статистика восстановлена")

    print("\n8) Выключенные метрики")
    off = MetricsStore(file_path="metrics_off.json", enabled=False)
    off.record_snapshot({"sent": 10, "queued": 0, "connected": True, "restarts": 0})
    check(len(off.history(1)["points"]) == 1, "точка без данных (нули)")
    check(off.history(1)["points"][0]["sent"] == 0, "данные не пишутся при выключении")
    check(not Path("metrics_off.json").exists(), "файл не создаётся")

    print("\n9) API панели")
    from test_smoke import install_stub_sdk

    install_stub_sdk()
    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    await app.init_runtime_for_tests()
    app.metrics = MetricsStore(file_path="metrics_api.json", enabled=True)
    app.metrics.record_snapshot({"sent": 0, "queued": 0, "connected": True, "restarts": 0})
    app.metrics._last_ts = time.time() - 60
    app.metrics.record_snapshot({"sent": 7, "queued": 1, "connected": True, "restarts": 0})
    app.metrics.record_channel_event("test")

    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/api/metrics?kind=history&hours=6")
        data = await resp.json()
        check(resp.status == 200, "history отвечает", str(resp.status))
        check(len(data["points"]) == 6, "6 точек", str(len(data["points"])))

        resp = await client.get("/api/metrics?kind=days")
        data = await resp.json()
        check(resp.status == 200, "days отвечает")
        check(len(data["days"]) >= 1, "дни возвращаются")

        resp = await client.get("/api/metrics?kind=summary")
        data = await resp.json()
        check("last24_sent" in data, "summary содержит данные")

        resp = await client.get("/api/metrics?kind=bogus")
        check(resp.status == 400, "неизвестный вид → 400", str(resp.status))

        resp = await client.get("/")
        html = await resp.text()
        check("charts-grid" in html, "графики в разметке главной")
        check("activity-week" in html, "календарь в разметке главной")
        check("chart-sent" in html, "canvas для графика отправленных")
    finally:
        await client.close()

    for extra in ("metrics_api.json", "metrics_off.json", "metrics_clean.json"):
        p = Path(extra)
        if p.exists():
            p.unlink()

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
