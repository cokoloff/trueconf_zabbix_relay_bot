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
os.environ["DELIVERED_FILE"] = "dl_test.json"
os.environ["METRICS_FILE"] = "metrics_test.json"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_met.txt"
os.environ["ADMIN_MODE"] = "strict"
os.environ["ADMIN_IDS"] = "admin@example.com"
os.environ.setdefault("WEBUI_AUTH", "none")

# Чистим файлы прошлых прогонов: иначе счётчики копятся между запусками
for _stale in ("metrics_test.json", "metrics_ch.json", "metrics_clean.json", "metrics_api.json"):
    Path(_stale).unlink(missing_ok=True)

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

    # Снимок состояния: отправки считаются отдельно (record_delivery),
    # здесь только очередь, связь и перезапуски
    store.record_snapshot({"queued": 0, "connected": True, "restarts": 1})
    h = store.history(1)["points"]
    check(h[0]["sent"] == 0, "первый снимок без отправок", str(h[0]["sent"]))

    store._last_ts = time.time() - 60
    store.record_snapshot({"queued": 2, "connected": True, "restarts": 1})
    h = store.history(1)["points"]
    check(h[-1]["queued"] == 2, "размер очереди зафиксирован", str(h[-1]["queued"]))
    # Процент считается от покрытия (фактически наблюдаемого времени),
    # поэтому при полной связи всегда 100%, независимо от длины интервала
    check(h[-1]["ws"] == 100, "связь 100% за интервал", str(h[-1]["ws"]))

    print("\n2) Отсутствие связи")
    # В том же часе уже была связь 60 с; добавляем 60 с без связи.
    # Процент считается от покрытия: 60 из 120 = 50%.
    store._last_ts = time.time() - 60
    store.record_snapshot({"queued": 5, "connected": False, "restarts": 2})
    h = store.history(1)["points"]
    check(h[-1]["ws"] == 50, "половина интервала без связи → 50%", str(h[-1]["ws"]))
    check(h[-1]["restarts"] == 1, "перезапуск учтён", str(h[-1]["restarts"]))

    # Отдельная точка без связи на чистом store — 0%
    clean = MetricsStore(file_path="metrics_clean.json", enabled=True)
    clean._hourly = {}
    clean._last_snapshot = {"restarts": 0, "queued": 0}
    clean._last_ts = time.time() - 60
    clean.record_snapshot({"queued": 0, "connected": False, "restarts": 0})
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

    print("\n4) Доставка по каналам")
    store2 = MetricsStore(file_path="metrics_ch.json", enabled=True)
    store2.record_delivery("network", "PROBLEM", 0.05, success=True)
    store2.record_delivery("network", "RESOLVED", 0.07, success=True)
    store2.record_delivery("zabbix", "PROBLEM", 0.12, success=True)
    store2.record_delivery("network", "PROBLEM", 0.5, success=False)

    hist = store2.history(24)
    totals = {c["name"]: c["count"] for c in hist["channels"]}
    check(totals.get("network") == 3, "network: 3 доставки", str(totals))
    check(totals.get("zabbix") == 1, "zabbix: 1 доставка", str(totals))

    statuses = {s["name"]: s["count"] for s in hist["statuses"]}
    check(statuses.get("PROBLEM") == 3, "PROBLEM: 3", str(statuses))
    check(statuses.get("RESOLVED") == 1, "RESOLVED: 1", str(statuses))

    point = hist["points"][-1]
    check(point["sent"] == 3, "успешных отправок 3", str(point["sent"]))
    check(point["failed"] == 1, "отказов 1", str(point["failed"]))
    check(point["latency"] is not None and 0.05 < point["latency"] < 0.15,
          "средняя задержка посчитана", str(point["latency"]))

    days = store2.days(365)["days"]
    today = days[-1] if days else None
    check(today is not None, "дневная запись создана")
    day_names = {c["name"]: c["count"] for c in today["by_channel"]}
    check(day_names.get("network") == 3, "в дневной сводке network: 3", str(day_names))
    check(today["channels"] == 2, "каналов учтено: 2", str(today["channels"]))

    print("\n4b) Отчёт по каналам")
    report = store2.channel_report(24)
    check(report["totals"]["channels"] == 2, "два канала в отчёте",
          str(report["totals"]["channels"]))
    check(report["totals"]["sent"] == 3, "всего отправлено 3",
          str(report["totals"]["sent"]))
    check(report["totals"]["failed"] == 1, "отказов 1",
          str(report["totals"]["failed"]))
    check(report["totals"]["success_rate"] == 75.0, "успешность 75%",
          str(report["totals"]["success_rate"]))

    by_name = {c["name"]: c for c in report["channels"]}
    net = by_name.get("network")
    check(net is not None, "канал network в отчёте")
    check(net["sent"] == 2, "network: отправлено 2", str(net["sent"]))
    check(net["failed"] == 1, "network: отказов 1", str(net["failed"]))
    check(net["total"] == 3, "network: всего 3", str(net["total"]))
    check(net["success_rate"] == 66.7, "network: успешность 66.7%",
          str(net["success_rate"]))
    check(net["avg_latency"] is not None and net["avg_latency"] > 0,
          "network: средняя задержка", str(net["avg_latency"]))
    check(net["max_latency"] is not None, "network: максимальная задержка",
          str(net["max_latency"]))
    check(len(net["hourly"]) == 24, "network: ряд по часам", str(len(net["hourly"])))
    check(sum(net["hourly"]) == 3, "network: ряд суммируется в общее",
          str(sum(net["hourly"])))
    net_statuses = {s["name"]: s["count"] for s in net["statuses"]}
    check(net_statuses.get("PROBLEM") == 2, "network: PROBLEM 2", str(net_statuses))
    check(net_statuses.get("RESOLVED") == 1, "network: RESOLVED 1", str(net_statuses))
    check(net["last_at"] is not None, "network: время последней отправки")

    # Сортировка: первым идёт канал с большим числом доставок
    check(report["channels"][0]["name"] == "network", "сортировка по количеству",
          str([c["name"] for c in report["channels"]]))

    print("\n4b2) Определение статуса по тексту (Zabbix без поля status)")
    from test_smoke import install_stub_sdk as _install

    _install()
    import bot_multy as app_module

    status_cases = [
        ("❌ Проблема GRE-R201-FW-FI", "PROBLEM"),
        ("✅ Решено GRE-R201-FW-FI", "RESOLVED"),
        ("PROBLEM: CPU high", "PROBLEM"),
        ("RESOLVED: CPU high", "RESOLVED"),
        ("🔥 Проблема на сервере", "PROBLEM"),
        ("Авария: сервер недоступен", "PROBLEM"),
        ("Восстановлено: диск в норме", "RESOLVED"),
        ("[1С] Объем памяти превышает 80%", ""),
        ("", ""),
    ]
    for text, expected in status_cases:
        got = app_module.guess_status(text)
        check(got == expected, f"статус для {text[:28]!r}",
              f"{got!r} != {expected!r}")

    # Разбор вебхука без поля status
    alert = app_module.parse_alert(
        {"message": "❌ Проблема GRE-R201-FW-FI\nСессий 151272"}, "network"
    )
    check(alert["status"] == "PROBLEM",
          "parse_alert определяет PROBLEM по тексту", alert["status"])

    alert2 = app_module.parse_alert({"message": "✅ Решено GRE-R201-FW-FI"}, "network")
    check(alert2["status"] == "RESOLVED",
          "parse_alert определяет RESOLVED по тексту", alert2["status"])

    # Явное поле status имеет приоритет над текстом
    alert3 = app_module.parse_alert(
        {"message": "❌ Проблема X", "status": "RESOLVED"}, "network"
    )
    check(alert3["status"] == "RESOLVED",
          "явный status важнее текста", alert3["status"])

    print("\n4b3) Строгость Zabbix из текста")
    from test_smoke import install_stub_sdk as _install2

    _install2()
    import bot_multy as app_mod

    severity_cases = [
        ("Строгость: Disaster 💀", "Disaster"),
        ("Строгость: High 🔥", "High"),
        ("Строгость: Average ⚡", "Average"),
        ("Строгость: Warning ⚠️", "Warning"),
        ("Строгость: Information ℹ️", "Information"),
        ("Строгость: Not classified", "Not classified"),
        ("без строгости вообще", ""),
        ("", ""),
    ]
    for text, expected in severity_cases:
        got = app_mod.guess_severity(text)
        check(got == expected, f"строгость для {text[:26]!r}",
              f"{got!r} != {expected!r}")

    alert_sev = app_mod.parse_alert(
        {"message": "❌ Проблема Zabbix\nСтрогость: Average ⚡"}, "network"
    )
    check(alert_sev["severity"] == "Average",
          "parse_alert извлекает строгость", alert_sev.get("severity"))
    check(alert_sev["status"] == "PROBLEM",
          "статус и строгость независимы", alert_sev.get("status"))

    # Явное поле важнее текста
    alert_sev2 = app_mod.parse_alert(
        {"message": "Строгость: High", "severity": "Disaster"}, "network"
    )
    check(alert_sev2["severity"] == "Disaster",
          "явная строгость важнее текста", alert_sev2.get("severity"))

    print("\n4b4) Накопление строгости в метриках")
    store_sev = MetricsStore(file_path="metrics_sev.json", enabled=True)
    store_sev.record_delivery("esb", "PROBLEM", 0.1, success=True, severity="Disaster")
    store_sev.record_delivery("esb", "PROBLEM", 0.1, success=True, severity="High")
    store_sev.record_delivery("esb", "PROBLEM", 0.1, success=True, severity="High")
    store_sev.record_delivery("esb", "RESOLVED", 0.1, success=True, severity="Average")

    hist_sev = store_sev.history(24)
    sev_map = {s["name"]: s["count"] for s in hist_sev["severities"]}
    check(sev_map.get("Disaster") == 1, "Disaster: 1", str(sev_map))
    check(sev_map.get("High") == 2, "High: 2", str(sev_map))
    check(sev_map.get("Average") == 1, "Average: 1", str(sev_map))

    # Порядок: тяжёлые сверху
    names = [s["name"] for s in hist_sev["severities"]]
    check(names[0] == "Disaster", "первым идёт Disaster", str(names))
    check(names.index("High") < names.index("Average"),
          "High раньше Average", str(names))

    # Сохранение и восстановление
    store_sev.save()
    restored_sev = MetricsStore(file_path="metrics_sev.json", enabled=True)
    sev_restored = {s["name"]: s["count"] for s in restored_sev.history(24)["severities"]}
    check(sev_restored.get("High") == 2, "строгость переживает перезапуск",
          str(sev_restored))
    Path("metrics_sev.json").unlink(missing_ok=True)

    print("\n4b5) Временная шкала (точки)")
    store_tl = MetricsStore(file_path="metrics_tl.json", enabled=True)
    base_ts = time.time()
    for offset, channel in [(0, "network"), (120, "esb"), (130, "esb"),
                            (700, "zabbix"), (3600, "data")]:
        store_tl._events.append({
            "ts": base_ts - offset,
            "channel": channel,
            "status": "PROBLEM",
            "severity": "High",
            "ok": True,
        })

    tl = store_tl.timeline(24, 5)
    check(len(tl["points"]) > 0, "точки на шкале есть", str(len(tl["points"])))
    check(tl["bucket_minutes"] == 5, "шаг по умолчанию 5 мин",
          str(tl["bucket_minutes"]))

    total_events = sum(p["total"] for p in tl["points"])
    check(total_events == 5, "все события учтены", str(total_events))

    # Соседние по времени события попадают в одну точку
    merged = [p for p in tl["points"] if p["total"] > 1]
    check(len(merged) >= 1, "события в одном интервале объединены",
          str([p["total"] for p in tl["points"]]))

    # В точке есть разбивка по каналам
    has_channels = all(isinstance(p["channels"], list) for p in tl["points"])
    check(has_channels, "у каждой точки есть разбивка по каналам")
    names = set()
    for point in tl["points"]:
        for item in point["channels"]:
            names.add(item["name"])
    check("esb" in names and "network" in names,
          "каналы в точках присутствуют", str(sorted(names)))

    # Есть подпись времени для подсказки
    first = tl["points"][0]
    check("label" in first and "time" in first, "у точки есть время для подсказки",
          str(first.keys()))

    # Порядок по времени
    stamps = [p["ts"] for p in tl["points"]]
    check(stamps == sorted(stamps), "точки отсортированы по времени")

    print("\n4b5-2) Масштабирование шкалы")
    store_scale = MetricsStore(file_path="metrics_scale.json", enabled=True)
    now_scale = time.time()
    for _ in range(300):
        store_scale._events.append({
            "ts": now_scale - (hash(str(_)) % (168 * 3600)),
            "channel": "net", "status": "PROBLEM",
            "severity": "High", "ok": True,
        })

    # Автоподбор: на больших периодах шаг крупнее
    steps = {}
    for hours in (1, 6, 24, 72, 168):
        auto = store_scale.timeline(hours, None)
        steps[hours] = auto["bucket_minutes"]
        check(len(auto["points"]) <= 400,
              f"точек не больше 400 за {hours} ч", str(len(auto["points"])))
    check(steps[1] <= steps[24] <= steps[168],
          "шаг растёт с периодом", str(steps))
    check(steps[168] >= 60, "за неделю шаг не меньше часа", str(steps[168]))

    # Явный шаг соблюдается
    explicit = store_scale.timeline(24, 1)
    check(explicit["bucket_minutes"] == 1, "явный шаг 1 мин соблюдён",
          str(explicit["bucket_minutes"]))
    explicit5 = store_scale.timeline(24, 5)
    check(explicit5["bucket_minutes"] == 5, "явный шаг 5 мин соблюдён",
          str(explicit5["bucket_minutes"]))
    explicit60 = store_scale.timeline(24, 60)
    check(explicit60["bucket_minutes"] == 60, "явный шаг 60 мин соблюдён",
          str(explicit60["bucket_minutes"]))

    # Крупный шаг даёт меньше точек
    check(len(explicit60["points"]) < len(explicit5["points"]),
          "крупный шаг объединяет события",
          f"{len(explicit60['points'])} vs {len(explicit5['points'])}")

    # Защита от лавины точек на длинном периоде
    crowded = store_scale.timeline(168, 1)
    check(crowded["bucket_minutes"] > 1,
          "мелкий шаг на неделе автоматически укрупняется",
          str(crowded["bucket_minutes"]))
    check(len(crowded["points"]) <= 3000,
          "точек не больше 3000", str(len(crowded["points"])))

    # Сумма событий сохраняется при любом шаге
    total_events_scale = len(store_scale._events)
    for bucket in (1, 15, 60):
        data_scale = store_scale.timeline(24, bucket)
        counted = sum(p["total"] for p in data_scale["points"])
        check(counted <= total_events_scale,
              f"при шаге {bucket} мин события не дублируются", str(counted))
    Path("metrics_scale.json").unlink(missing_ok=True)

    print("\n4b5-0) Столбики по каналам: проблемы и решения")
    store_cb = MetricsStore(file_path="metrics_cb.json", enabled=True)
    store_cb._hourly = {}
    for _ in range(4):
        store_cb.record_delivery("balanced", "PROBLEM", 0.1, success=True)
    for _ in range(4):
        store_cb.record_delivery("balanced", "RESOLVED", 0.1, success=True)
    for _ in range(6):
        store_cb.record_delivery("bad", "PROBLEM", 0.1, success=True)
    for _ in range(2):
        store_cb.record_delivery("good", "PROBLEM", 0.1, success=True)
    for _ in range(8):
        store_cb.record_delivery("good", "RESOLVED", 0.1, success=True)

    hist_cb = store_cb.history(24)
    cb_map = {c["name"]: c for c in hist_cb["channels"]}

    bal_cb = cb_map.get("balanced", {})
    check(bal_cb.get("count") == 8, "balanced: всего 8", str(bal_cb.get("count")))
    check(bal_cb.get("problem") == 4, "balanced: проблем 4",
          str(bal_cb.get("problem")))
    check(bal_cb.get("resolved") == 4, "balanced: решений 4",
          str(bal_cb.get("resolved")))

    bad_cb = cb_map.get("bad", {})
    check(bad_cb.get("problem") == 6, "bad: проблем 6", str(bad_cb.get("problem")))
    check(bad_cb.get("resolved") == 0, "bad: решений 0", str(bad_cb.get("resolved")))

    good_cb = cb_map.get("good", {})
    check(good_cb.get("problem") == 2, "good: проблем 2", str(good_cb.get("problem")))
    check(good_cb.get("resolved") == 8, "good: решений 8",
          str(good_cb.get("resolved")))

    # Сумма problems+resolved равна count (для учтённых статусов)
    for name, item in cb_map.items():
        split_sum = item.get("problem", 0) + item.get("resolved", 0)
        check(split_sum == item["count"],
              f"{name}: разбивка сходится с итогом",
              f"{split_sum} != {item['count']}")

    # Сортировка: первым идёт канал с большим объёмом
    names_order = [c["name"] for c in hist_cb["channels"]]
    check(names_order[0] in ("balanced", "good"),
          "сортировка по количеству", str(names_order))
    Path("metrics_cb.json").unlink(missing_ok=True)

    print("\n4b5-1) Мини-график: проблемы и решения по часам")
    store_sp = MetricsStore(file_path="metrics_sp.json", enabled=True)
    store_sp._hourly = {}
    now_sp = time.time()

    # Три профиля: сбалансированный, только проблемы, перекос в решения
    profiles = {
        "balanced": {"PROBLEM": 5, "RESOLVED": 5},
        "bad": {"PROBLEM": 9},
        "good": {"PROBLEM": 2, "RESOLVED": 8},
    }
    for hour_back in range(3):
        ts_sp = now_sp - hour_back * 3600
        bucket = store_sp._hour_bucket(ts_sp)
        detail = bucket.setdefault("channel_stats", {})
        for name, statuses in profiles.items():
            total_sp = sum(statuses.values())
            detail[name] = {
                "sent": total_sp, "failed": 0,
                "latency_sum": 0.1 * total_sp, "latency_n": total_sp,
                "latency_max": 0.2, "statuses": dict(statuses),
                "last_at": int(ts_sp),
            }

    report_sp = store_sp.channel_report(24)
    by_name = {c["name"]: c for c in report_sp["channels"]}

    bal = by_name.get("balanced", {})
    check(bal.get("problems") == 15, "сбалансированный: проблем 15",
          str(bal.get("problems")))
    check(bal.get("resolved") == 15, "сбалансированный: решений 15",
          str(bal.get("resolved")))

    bad_ch = by_name.get("bad", {})
    check(bad_ch.get("problems") == 27, "только проблемы: 27",
          str(bad_ch.get("problems")))
    check(bad_ch.get("resolved") == 0, "только проблемы: решений 0",
          str(bad_ch.get("resolved")))

    good_ch = by_name.get("good", {})
    check(good_ch.get("problems") == 6, "перекос в решения: проблем 6",
          str(good_ch.get("problems")))
    check(good_ch.get("resolved") == 24, "перекос в решения: решений 24",
          str(good_ch.get("resolved")))

    # Почасовые ряды для графика
    check("hourly_problem" in bal, "есть ряд проблем по часам")
    check("hourly_resolved" in bal, "есть ряд решений по часам")
    check(len(bal.get("hourly_problem", [])) == 24,
          "ряд проблем нужной длины",
          str(len(bal.get("hourly_problem", []))))
    check(sum(bal.get("hourly_problem", [])) == 15,
          "ряд проблем суммируется",
          str(sum(bal.get("hourly_problem", []))))
    check(sum(bal.get("hourly_resolved", [])) == 15,
          "ряд решений суммируется",
          str(sum(bal.get("hourly_resolved", []))))

    # У канала только с проблемами ряд решений нулевой
    check(all(v == 0 for v in bad_ch.get("hourly_resolved", [])) or
          sum(bad_ch.get("hourly_resolved", [])) == 0,
          "у проблемного канала решений нет")
    Path("metrics_sp.json").unlink(missing_ok=True)

    print("\n4b5-3) Проблемы и решения разделены")
    store_st = MetricsStore(file_path="metrics_st.json", enabled=True)
    # Ставим события в СЕРЕДИНУ пятиминутного слота, чтобы все они
    # гарантированно попали в один интервал (границы слота здесь не мешают).
    base_st = (int(time.time()) // 300) * 300 + 60
    # В одном интервале: 3 проблемы и 2 решения
    for i in range(3):
        store_st._events.append({
            "ts": base_st + i * 10, "channel": "network",
            "status": "PROBLEM", "severity": "High", "ok": True,
        })
    for i in range(2):
        store_st._events.append({
            "ts": base_st + 100 + i * 10, "channel": "esb",
            "status": "RESOLVED", "severity": "High", "ok": True,
        })

    tl_st = store_st.timeline(2, 5)
    mixed = [p for p in tl_st["points"] if p["problems"] and p["resolved"]]
    check(len(mixed) == 1, "интервал со смешанными статусами найден", str(len(mixed)))
    if mixed:
        point_st = mixed[0]
        check(point_st["problems"] == 3, "проблем: 3", str(point_st["problems"]))
        check(point_st["resolved"] == 2, "решено: 2", str(point_st["resolved"]))
        check(point_st["total"] == 5, "всего: 5", str(point_st["total"]))
        check("weekday" in point_st, "есть день недели для подсказки",
              str(point_st.get("weekday")))
        check("time" in point_st, "есть время для подсказки")
        by = point_st.get("by_channel", {})
        check(by.get("network", {}).get("problem") == 3,
              "проблемы по каналам", str(by))
        check(by.get("esb", {}).get("resolved") == 2,
              "решения по каналам", str(by))

    # Интервал только с проблемами
    only_p = MetricsStore(file_path="metrics_op.json", enabled=True)
    only_p._events.append({
        "ts": base_st, "channel": "net", "status": "PROBLEM",
        "severity": "High", "ok": True,
    })
    tl_op = only_p.timeline(1, 5)
    check(tl_op["points"][0]["problems"] == 1, "только проблема посчитана")
    check(tl_op["points"][0]["resolved"] == 0, "решений нет")

    # Интервал только с решениями
    only_r = MetricsStore(file_path="metrics_or.json", enabled=True)
    only_r._events.append({
        "ts": base_st, "channel": "net", "status": "RESOLVED",
        "severity": "High", "ok": True,
    })
    tl_or = only_r.timeline(1, 5)
    check(tl_or["points"][0]["resolved"] == 1, "только решение посчитано")
    check(tl_or["points"][0]["problems"] == 0, "проблем нет")

    for garbage in ("metrics_st.json", "metrics_op.json", "metrics_or.json"):
        Path(garbage).unlink(missing_ok=True)

    print("\n4b6) События переживают перезапуск")
    store_tl.save()
    reloaded_tl = MetricsStore(file_path="metrics_tl.json", enabled=True)
    check(len(reloaded_tl._events) == 5, "события загружены с диска",
          str(len(reloaded_tl._events)))
    tl2 = reloaded_tl.timeline(24, 5)
    check(sum(p["total"] for p in tl2["points"]) == 5,
          "шкала восстановлена", str(sum(p["total"] for p in tl2["points"])))
    Path("metrics_tl.json").unlink(missing_ok=True)

    print("\n4c) Календарь: итог совпадает с детализацией")
    days_ch = store2.days(365)["days"]
    today_ch = days_ch[-1]
    total_today = sum(c["count"] for c in today_ch["by_channel"])
    check(today_ch["count"] == total_today,
          "итог дня равен сумме по каналам",
          f"{today_ch['count']} != {total_today}")

    print("\n4d) Время по Москве (UTC+3)")
    from tcbot.metrics import MOSCOW_TZ
    from datetime import datetime, timezone
    now_msk = datetime.now(MOSCOW_TZ)
    now_utc = datetime.now(timezone.utc)
    check(now_msk.utcoffset().total_seconds() == 10800, "смещение +3 часа",
          str(now_msk.utcoffset()))
    diff_hours = round((now_msk.hour - now_utc.hour) % 24)
    check(diff_hours == 3, "московское время опережает UTC на 3 ч",
          str(diff_hours))

    store_tz = MetricsStore(file_path="metrics_tz.json", enabled=True)
    store_tz.record_delivery("esb", "PROBLEM", 0.1)
    hist_tz = store_tz.history(2)
    last_label = hist_tz["points"][-1]["label"]
    expected = datetime.now(MOSCOW_TZ).strftime("%H:00")
    check(last_label == expected, "метка часа совпадает с московским временем",
          f"{last_label} != {expected}")
    day_tz = store_tz.days(1)["days"][0]
    check(day_tz["date"] == now_msk.strftime("%Y-%m-%d"),
          "дата дня совпадает с московской", day_tz["date"])
    Path("metrics_tz.json").unlink(missing_ok=True)

    print("\n4e) Восстановление разбивки из старого файла")
    import json as _json
    old_key = store_tz._hour_key()
    legacy = {
        "hourly": {
            old_key: {
                "ts": 1, "sent": 10, "failed": 0, "queued_max": 0,
                "ws": 3600, "covered": 3600, "restarts": 0,
                "channel_stats": {
                    "esb": {"sent": 6, "failed": 0,
                            "statuses": {"PROBLEM": 6}, "last_at": 1},
                },
            }
        },
        "daily": {},
    }
    Path("metrics_legacy.json").write_text(_json.dumps(legacy), encoding="utf-8")
    restored = MetricsStore(file_path="metrics_legacy.json", enabled=True)
    hist_rest = restored.history(1)
    check(any(c["name"] == "esb" for c in hist_rest["channels"]),
          "каналы восстановлены из channel_stats", str(hist_rest["channels"]))
    check(any(s["name"] == "PROBLEM" for s in hist_rest["statuses"]),
          "статусы восстановлены из channel_stats", str(hist_rest["statuses"]))
    Path("metrics_legacy.json").unlink(missing_ok=True)

    print("\n5) Пустой канал не учитывается")
    before = len(store.days(365)["days"])
    store.record_channel_event(None)
    store.record_channel_event("")
    after = len(store.days(365)["days"])
    check(before == after, "None и пустая строка игнорируются")

    print("\n6) Сводка")
    summary = store.summary()
    for key in ("today_sent", "today_channels", "last24_sent", "last24_failed", "avg_latency"):
        check(key in summary, f"сводка содержит {key}")
    check(summary["last24_sent"] >= 0, "за сутки посчитано", str(summary["last24_sent"]))

    print("\n7) Сохранение и загрузка")
    store.save()
    store2.save()
    check(Path("metrics_test.json").exists(), "файл создан")
    check(Path("metrics_ch.json").exists(), "файл с доставками создан")

    reloaded = MetricsStore(file_path="metrics_test.json", enabled=True)
    check(len(reloaded.history(24)["points"]) == 24, "история восстановлена")

    reloaded2 = MetricsStore(file_path="metrics_ch.json", enabled=True)
    hist_restored = reloaded2.history(24)
    check(any(c["name"] == "network" for c in hist_restored["channels"]),
          "разбивка по каналам восстановлена", str(hist_restored["channels"]))
    days2 = reloaded2.days(365)["days"]
    check(any(d["channels"] >= 2 for d in days2), "дневная статистика восстановлена")

    print("\n7b) Метрики переживают перезапуск")
    restarted = MetricsStore(file_path="metrics_ch.json", enabled=True)
    hist_r = restarted.history(24)
    names_r = {c["name"]: c["count"] for c in hist_r["channels"]}
    check(names_r.get("network") == 3, "каналы восстановлены после рестарта",
          str(names_r))
    statuses_r = {s["name"]: s["count"] for s in hist_r["statuses"]}
    check(statuses_r.get("PROBLEM") == 3, "статусы восстановлены", str(statuses_r))
    check(hist_r["points"][-1]["sent"] == 3, "отправки восстановлены",
          str(hist_r["points"][-1]["sent"]))

    rep_r = restarted.channel_report(24)
    check(rep_r["totals"]["sent"] == 3, "отчёт по каналам восстановлен",
          str(rep_r["totals"]["sent"]))
    net_r = next((c for c in rep_r["channels"] if c["name"] == "network"), None)
    check(net_r is not None, "канал network в отчёте после рестарта")
    if net_r:
        check(net_r["sent"] == 2, "network: отправки сохранены", str(net_r["sent"]))
        check(net_r["failed"] == 1, "network: отказы сохранены", str(net_r["failed"]))
        check(net_r["avg_latency"] is not None, "network: задержка сохранена")

    # Новая сессия продолжает накапливать, а не начинает заново
    restarted.record_delivery("network", "PROBLEM", 0.09, success=True)
    hist_after = restarted.history(24)
    total_after = {c["name"]: c["count"] for c in hist_after["channels"]}
    check(total_after.get("network") == 4,
          "после рестарта счётчик продолжается, а не сбрасывается",
          str(total_after))

    # Флаг изменений и сохранение
    check(restarted.dirty is True, "есть несохранённые изменения")
    restarted.save()
    check(restarted.dirty is False, "после сохранения флаг сброшен")

    print("\n8) Выключенные метрики")
    off = MetricsStore(file_path="metrics_off.json", enabled=False)
    off.record_snapshot({"queued": 0, "connected": True, "restarts": 0})
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
    app.metrics.record_delivery("test", "PROBLEM", 0.1, success=True)
    app.metrics._last_ts = time.time() - 60
    app.metrics.record_delivery("test", "RESOLVED", 0.2, success=True)
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

        resp = await client.get("/api/metrics?kind=channels&hours=6")
        data = await resp.json()
        check(resp.status == 200, "channels отвечает", str(resp.status))
        check("channels" in data and "statuses" in data, "разбивка по каналам и статусам")
        check(any(c["name"] == "test" for c in data["channels"]), "канал test учтён",
              str(data["channels"]))

        resp = await client.get("/api/metrics?kind=channel-report&hours=6")
        data = await resp.json()
        check(resp.status == 200, "channel-report отвечает", str(resp.status))
        check("channels" in data and "totals" in data, "отчёт содержит каналы и итоги")
        check(data["totals"]["channels"] >= 1, "каналы в итогах",
              str(data["totals"]))

        resp = await client.get("/channel-stats")
        html_page = await resp.text()
        check(resp.status == 200, "страница статистики отдаётся")
        for marker in ("cs-rows", "cs-totals", "cs-hours", "cs-search"):
            check(marker in html_page, f"элемент {marker} на странице")

        resp = await client.get("/api/metrics?kind=statuses&hours=6")
        data = await resp.json()
        check(resp.status == 200, "statuses отвечает")
        check("statuses" in data, "статусы возвращаются")

        resp = await client.get("/api/metrics?kind=bogus")
        check(resp.status == 400, "неизвестный вид → 400", str(resp.status))

        resp = await client.get("/")
        html = await resp.text()
        check("charts-grid" in html, "графики в разметке главной")
        check("activity-week" in html, "календарь в разметке главной")
        check("chart-sent" in html, "canvas для графика отправленных")

        # На главной не должно быть графика по каналам и строгости:
        # при 30 каналах они не помещаются, они переехали в статистику
        check("chart-channels" not in html,
              "графика по каналам нет на главной")
        check("severity-bars" not in html,
              "строгости нет на главной")
        check("chart-queue" in html, "очередь есть на главной")

        resp = await client.get("/channel-stats")
        stats_html = await resp.text()
        check(resp.status == 200, "страница статистики отдаётся")
        check("chart-channels" in stats_html,
              "график по каналам на странице статистики")
        check("severity-bars" in stats_html,
              "строгость на странице статистики")
        check("chart-sent-2" in stats_html,
              "динамика отправок на странице статистики")
        check("chart-latency-2" in stats_html,
              "задержка на странице статистики")
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