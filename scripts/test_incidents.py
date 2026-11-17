#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка режимов реакции на восстановление инцидента."""

import asyncio
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ["LOG_DIR"] = "logs_inc"
os.environ["STATE_FILE"] = "bs_inc.json"
os.environ["OUTBOX_FILE"] = "ob_inc.json"
os.environ["DELIVERED_FILE"] = "dl_inc.json"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_inc.txt"
os.environ["ADMIN_MODE"] = "strict"
os.environ["ADMIN_IDS"] = "admin@example.com"
os.environ.setdefault("WEBUI_AUTH", "none")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


def cleanup():
    for name in ("logs_inc", "bs_inc.json", "ob_inc.json", "dl_inc.json", "la_inc.txt"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


async def main() -> int:
    print("1) Ключ инцидента совпадает у PROBLEM и RESOLVED")
    from test_smoke import install_stub_sdk

    install_stub_sdk()
    import bot_multy as app

    pairs = [
        ("по triggerid",
         {"subject": "❌ Проблема GRE", "triggerid": "12345"},
         {"subject": "✅ Решено GRE", "triggerid": "12345"}),
        ("по имени триггера",
         {"subject": "❌ Проблема GRE-R201", "message": "a"},
         {"subject": "✅ Решено GRE-R201", "message": "b"}),
        ("по тексту без меток",
         {"message": "❌ Проблема Zabbix\nSelf check failed"},
         {"message": "✅ Решено Zabbix\nSelf check failed"}),
    ]
    for label, problem, resolved in pairs:
        k1 = app.parse_alert(problem, "net")["incident_key"]
        k2 = app.parse_alert(resolved, "net")["incident_key"]
        check(k1 == k2, f"ключи совпадают {label}", f"{k1} != {k2}")

    # Разные инциденты дают разные ключи
    a = app.parse_alert({"subject": "❌ Проблема A"}, "net")["incident_key"]
    b = app.parse_alert({"subject": "❌ Проблема B"}, "net")["incident_key"]
    check(a != b, "разные триггеры — разные ключи")

    print("\n2) Очистка меток статуса")
    check(app._strip_status_marks("❌ Проблема GRE-R201") == "GRE-R201",
          "❌ Проблема убрано",
          app._strip_status_marks("❌ Проблема GRE-R201"))
    check(app._strip_status_marks("✅ Решено GRE-R201") == "GRE-R201",
          "✅ Решено убрано",
          app._strip_status_marks("✅ Решено GRE-R201"))
    check(app._strip_status_marks("Обычный текст") == "Обычный текст",
          "текст без меток не меняется")

    print("\n3) Режимы реакции")
    for mode in ("notify", "delete", "resolve", "both"):
        await app.init_runtime_for_tests()
        app._delivered_recent = {}
        app._delivered_dirty = False
        app.state_manager.settings["incident_mode"] = mode
        app.state_manager.settings["delete_messages_enabled"] = True
        app.state_manager.settings["error_delete_threshold_hours"] = 999
        app.state_manager.raw["error_history"] = {}

        try:
            app.bot.sent.clear()
        except Exception:
            pass

        await app.runner.start()
        await app.runner.wait_ready(timeout=5)

        k1 = app.parse_alert({"subject": "❌ Проблема Тест", "message": "x"}, "net")["incident_key"]
        k2 = app.parse_alert({"subject": "✅ Решено Тест", "message": "x"}, "net")["incident_key"]

        await app._track_incident(
            {"status": "PROBLEM", "incident_key": k1,
             "subject": "❌ Проблема Тест", "message": "x"},
            "chat-1", "net", "msg-123",
        )
        stored = app.state_manager.get_error(k1)
        check(stored is not None, f"[{mode}] проблема записана в историю")
        check(stored and stored.get("message_id") == "msg-123",
              f"[{mode}] message_id сохранён",
              str(stored.get("message_id") if stored else None))

        before = len(app.bot.sent)
        await app._track_incident(
            {"status": "RESOLVED", "incident_key": k2,
             "subject": "✅ Решено Тест", "message": "x"},
            "chat-1", "net", None,
        )
        added = len(app.bot.sent) - before

        if mode == "notify":
            check(added == 0, "[notify] сообщение не отправляется", str(added))
        elif mode == "delete":
            check(added == 0, "[delete] сообщение не отправляется", str(added))
        elif mode == "resolve":
            check(added == 1, "[resolve] отправлено «восстановлено»", str(added))
        else:
            check(added == 1, "[both] отправлено «восстановлено»", str(added))

        check(app.state_manager.get_error(k1) is None,
              f"[{mode}] инцидент убран из истории")

        await app.runner.stop()

    print("\n3b) Режим для отдельного канала")
    await app.init_runtime_for_tests()
    app._delivered_recent = {}
    app._delivered_dirty = False
    app.state_manager.raw["error_history"] = {}
    app.state_manager.settings["incident_mode"] = "notify"
    app.state_manager.settings["delete_messages_enabled"] = True
    app.state_manager.settings["error_delete_threshold_hours"] = 999

    await app.state_manager.add_channel("own", "chat-own", created_by="t")
    await app.state_manager.add_channel("inherits", "chat-inh", created_by="t")

    # Каналу own задаём свой режим
    await app.state_manager.set_channel_incident_mode("own", "resolve")
    check(app.state_manager.channel_incident_mode("own") == "resolve",
          "своя настройка канала сохранена")
    check(app.state_manager.channel_incident_mode("inherits") is None,
          "без своей настройки — None (наследует)")

    check(app.state_manager.channel_incident_mode("ghost") is None,
          "несуществующий канал — None")

    # Сброс на наследование
    await app.state_manager.set_channel_incident_mode("own", None)
    check(app.state_manager.channel_incident_mode("own") is None,
          "настройка канала сброшена на наследование")

    await app.state_manager.set_channel_incident_mode("own", "both")
    check(app.state_manager.channel_incident_mode("own") == "both",
          "режим both применён к каналу")

    # Фактическое поведение: свой режим важнее глобального
    await app.runner.start()
    await app.runner.wait_ready(timeout=5)
    try:
        app.bot.sent.clear()
        k1 = app.parse_alert({"subject": "❌ Проблема own", "message": "x"}, "own")["incident_key"]
        k2 = app.parse_alert({"subject": "✅ Решено own", "message": "x"}, "own")["incident_key"]
        await app._track_incident(
            {"status": "PROBLEM", "incident_key": k1,
             "subject": "❌ Проблема own", "message": "x"},
            "chat-own", "own", "msg-own",
        )
        before = len(app.bot.sent)
        await app._track_incident(
            {"status": "RESOLVED", "incident_key": k2,
             "subject": "✅ Решено own", "message": "x"},
            "chat-own", "own", None,
        )
        added = len(app.bot.sent) - before
        check(added == 1, "свой режим канала (both) важнее глобального", str(added))

        # Канал без своей настройки — работает глобальный notify
        app.bot.sent.clear()
        g1 = app.parse_alert({"subject": "❌ Проблема inh", "message": "y"}, "inherits")["incident_key"]
        g2 = app.parse_alert({"subject": "✅ Решено inh", "message": "y"}, "inherits")["incident_key"]
        await app._track_incident(
            {"status": "PROBLEM", "incident_key": g1,
             "subject": "❌ Проблема inh", "message": "y"},
            "chat-inh", "inherits", "msg-inh",
        )
        before = len(app.bot.sent)
        await app._track_incident(
            {"status": "RESOLVED", "incident_key": g2,
             "subject": "✅ Решено inh", "message": "y"},
            "chat-inh", "inherits", None,
        )
        added = len(app.bot.sent) - before
        check(added == 0, "канал без своей настройки наследует глобальную", str(added))
    finally:
        await app.runner.stop()

    print("\n3c) Повторные PROBLEM не теряются")
    await app.init_runtime_for_tests()
    app._delivered_recent = {}
    app._delivered_dirty = False
    app.state_manager.raw["error_history"] = {}
    app.state_manager.settings["incident_mode"] = "notify"

    key_rep = "repeatkey"
    # Zabbix повторяет одну и ту же проблему несколько раз
    for i in range(4):
        await app.state_manager.remember_error(
            key_rep, f"msg-{i + 1}", "linux_infra"
        )

    record_rep = app.state_manager.get_error(key_rep)
    check(record_rep is not None, "инцидент записан")
    ids_rep = record_rep.get("message_ids", [])
    check(len(ids_rep) == 4, "сохранены все 4 message_id", str(ids_rep))
    check(record_rep.get("repeat_count") == 4, "счётчик повторов: 4",
          str(record_rep.get("repeat_count")))
    check(record_rep.get("message_id") == "msg-4",
          "последний id тоже сохранён", str(record_rep.get("message_id")))

    # Повтор с уже известным id не создаёт дубликат
    await app.state_manager.remember_error(key_rep, "msg-4", "linux_infra")
    record_rep2 = app.state_manager.get_error(key_rep)
    check(len(record_rep2.get("message_ids", [])) == 4,
          "дубликат id не добавляется",
          str(record_rep2.get("message_ids")))

    # Удаление всех накопленных сообщений
    app.state_manager.raw["error_history"] = {}
    await app.state_manager.add_channel("rep", "chat-rep", created_by="t")
    await app.state_manager.set_channel_incident_mode("rep", "delete")
    app.state_manager.settings["delete_messages_enabled"] = True
    app.state_manager.settings["error_delete_threshold_hours"] = 999

    await app.runner.start()
    await app.runner.wait_ready(timeout=5)
    try:
        try:
            app.bot.removed.clear()
        except Exception:
            pass

        key_del = "delkey"
        for i in range(3):
            await app._track_incident(
                {"status": "PROBLEM", "incident_key": key_del,
                 "subject": "❌ Проблема X", "message": "x"},
                "chat-rep", "rep", f"del-msg-{i + 1}",
            )

        stored_del = app.state_manager.get_error(key_del)
        check(len(stored_del.get("message_ids", [])) == 3,
              "три сообщения накоплены", str(stored_del.get("message_ids")))

        await app._track_incident(
            {"status": "RESOLVED", "incident_key": key_del,
             "subject": "✅ Решено X", "message": "x"},
            "chat-rep", "rep", None,
        )

        removed = getattr(app.bot, "removed", [])
        check(len(removed) == 3, "удалены все три сообщения", str(removed))
        check(app.state_manager.get_error(key_del) is None,
              "инцидент убран из истории")
    finally:
        await app.runner.stop()

    print("\n3d) Инцидент переживает перезапуск")
    await app.init_runtime_for_tests()
    app._delivered_recent = {}
    app._delivered_dirty = False
    app.state_manager.raw["error_history"] = {}
    await app.state_manager.add_channel("persist", "chat-persist", created_by="t")
    await app.state_manager.set_channel_incident_mode("persist", "delete")

    key_persist = "persistkey"
    for i in range(3):
        await app._track_incident(
            {"status": "PROBLEM", "incident_key": key_persist,
             "subject": "❌ Проблема P", "message": "x"},
            "chat-persist", "persist", f"persist-msg-{i + 1}",
        )

    # Имитация рестарта: читаем файл заново
    from tcbot.state import StateManager

    reloaded = StateManager(os.environ["STATE_FILE"], version="test")
    rec_persist = reloaded.get_error(key_persist)

    check(rec_persist is not None, "инцидент сохранён на диск")
    if rec_persist:
        check(len(rec_persist.get("message_ids", [])) == 3,
              "все три сообщения сохранены",
              str(rec_persist.get("message_ids")))
        check(rec_persist.get("repeat_count") == 3,
              "счётчик повторов сохранён",
              str(rec_persist.get("repeat_count")))
        check(rec_persist.get("channel") == "persist",
              "канал инцидента сохранён", str(rec_persist.get("channel")))
    check(reloaded.channel_incident_mode("persist") == "delete",
          "режим канала сохранён")

    # После «рестарта» удаление должно сработать по сохранённым id
    await app.state_manager.remember_error(key_persist, "", "persist")
    record_after = app.state_manager.get_error(key_persist)
    ids_after = record_after.get("message_ids", [])
    check(len(ids_after) == 3,
          "повторная запись не теряет накопленные id", str(ids_after))

    print("\n4) Настройка режима через API")
    from aiohttp.test_utils import TestClient, TestServer

    await app.init_runtime_for_tests()
    app.state_manager.settings["incident_mode"] = "notify"
    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/api/settings")
        data = await resp.json()
        check("incident_mode" in data.get("settings", {}),
              "режим есть в настройках")

        resp = await client.post("/api/settings", json={"incident_mode": "resolve"})
        check(resp.status == 200, "режим сохраняется", str(resp.status))
        check(app.state_manager.settings["incident_mode"] == "resolve",
              "значение применено", str(app.state_manager.settings["incident_mode"]))

        resp = await client.post("/api/settings", json={"incident_mode": "bogus"})
        check(resp.status == 400, "неизвестный режим отклонён", str(resp.status))

        # Режим с удалением включает удаление
        app.state_manager.settings["delete_messages_enabled"] = False
        resp = await client.post("/api/settings", json={"incident_mode": "delete"})
        check(app.state_manager.settings["delete_messages_enabled"] is True,
              "режим delete включает удаление")

        resp = await client.get("/settings")
        html = await resp.text()
        for marker in ("set-incident-mode", "set-mode-hint"):
            check(marker in html, f"элемент {marker} на странице настроек")
    finally:
        await client.close()

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
