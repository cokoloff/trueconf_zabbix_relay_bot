#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка резервного копирования состояния."""

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ["LOG_DIR"] = "logs_bk"
os.environ["STATE_FILE"] = "bs_bk.json"
os.environ["OUTBOX_FILE"] = "ob_bk.json"
os.environ["DELIVERED_FILE"] = "dl_bk.json"
os.environ["BACKUP_DIR"] = "bk_test"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_bk.txt"
os.environ["ADMIN_MODE"] = "strict"
os.environ["ADMIN_IDS"] = "admin@example.com"
os.environ.setdefault("WEBUI_AUTH", "none")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


def cleanup():
    for name in ("logs_bk", "bk_test", "bs_bk.json", "ob_bk.json",
                 "dl_bk.json", "la_bk.txt"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def make_state(path: Path, channels: int = 3, admins: int = 1) -> None:
    data = {
        "version": "12.0",
        "notification_channels": {
            f"ch{i}": {"chat_id": f"chat-{i}", "chat_title": f"Чат {i}"}
            for i in range(channels)
        },
        "default_chat": "chat-0",
        "admins": [f"admin{i}@example.com" for i in range(admins)],
        "settings": {"max_retries": 3},
        "metadata": {"messages_sent": 10},
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def main() -> int:
    from tcbot.backup import BackupManager

    Path("bk_test").mkdir(exist_ok=True)
    for stale in Path("bk_test").glob("*.json"):
        stale.unlink()

    print("1) Создание копии")
    make_state(Path("bs_bk.json"), channels=3, admins=1)
    manager = BackupManager("bs_bk.json", backup_dir="bk_test", keep=5, enabled=True)

    created = manager.create("test")
    check(created is not None, "копия создана")
    check(created.exists() if created else False, "файл копии существует")
    check("bot_state_" in (created.name if created else ""),
          "имя по шаблону", created.name if created else "")

    files = manager.list_files()
    check(len(files) == 1, "в списке одна копия", str(len(files)))

    print("\n2) Содержимое копии")
    data = json.loads(created.read_text(encoding="utf-8"))
    check(len(data["notification_channels"]) == 3, "каналы сохранены")
    check(len(data["admins"]) == 1, "администраторы сохранены")
    check(data.get("version") == "12.0", "версия сохранена")

    print("\n3) Описание для панели")
    items = manager.list_items()
    check(len(items) == 1, "элемент в списке", str(len(items)))
    check(items[0]["channels"] == 3, "каналов в описании: 3", str(items[0]["channels"]))
    check(items[0]["admins"] == 1, "админов в описании: 1", str(items[0]["admins"]))
    check(items[0]["size"] > 0, "размер указан", str(items[0]["size"]))

    print("\n4) Уникальность имён в одну секунду")
    second = manager.create("test")
    check(second is not None, "вторая копия создана")
    check(second.name != created.name, "имена различаются",
          f"{second.name} == {created.name}")
    check(len(manager.list_files()) == 2, "обе копии сохранены")

    print("\n5) Ротация старых копий")
    manager.keep = 2
    for _ in range(4):
        manager.create("rotate-test")
    kept = manager.list_files()
    check(len(kept) == 2, "хранится ровно keep копий", str(len(kept)))
    manager.keep = 5

    print("\n6) Восстановление")
    for stale in Path("bk_test").glob("*.json"):
        stale.unlink()
    make_state(Path("bs_bk.json"), channels=5, admins=2)
    restored_from = manager.create("before-change")
    check(restored_from is not None, "копия перед изменением создана")

    # Порти́м состояние
    make_state(Path("bs_bk.json"), channels=1, admins=0)
    broken = json.loads(Path("bs_bk.json").read_text(encoding="utf-8"))
    check(len(broken["notification_channels"]) == 1, "состояние испорчено")

    result = manager.restore(restored_from.name)
    check(result.get("ok") is True, "восстановление успешно", str(result.get("error")))
    check(result.get("channels") == 5, "восстановлено 5 каналов",
          str(result.get("channels")))
    check(result.get("admins") == 2, "восстановлено 2 админа",
          str(result.get("admins")))
    check(result.get("backup_before") != restored_from.name,
          "страховочная копия имеет другое имя", str(result.get("backup_before")))

    after = json.loads(Path("bs_bk.json").read_text(encoding="utf-8"))
    check(len(after["notification_channels"]) == 5, "каналы на месте после восстановления")
    check(len(after["admins"]) == 2, "администраторы на месте")

    print("\n7) Защита от подмены имени")
    evil = manager.restore("../../../etc/passwd")
    check(evil.get("ok") is False, "выход из каталога запрещён", str(evil))
    evil2 = manager.restore("bot_state_x.json")
    check(evil2.get("ok") is False, "несуществующая копия отклонена", str(evil2))

    print("\n8) Повреждённая копия")
    bad = Path("bk_test") / "bot_state_20200101_000000.json"
    bad.write_text("это не json", encoding="utf-8")
    broken_result = manager.restore(bad.name)
    check(broken_result.get("ok") is False, "повреждённая копия отклонена",
          str(broken_result.get("error")))
    bad.unlink()

    print("\n9) Удаление копии")
    victim = manager.create("to-delete")
    deleted = manager.delete(victim.name)
    check(deleted.get("ok") is True, "копия удалена")
    check(not victim.exists(), "файл удалён")

    print("\n10) Сводка")
    stats = manager.stats()
    check(stats["enabled"] is True, "копирование включено")
    check(stats["count"] >= 1, "копии есть", str(stats["count"]))
    check(stats["keep"] == 5, "лимит в сводке", str(stats["keep"]))
    check(stats["total_size"] > 0, "суммарный размер", str(stats["total_size"]))

    print("\n11) Архив")
    archive = manager.create_archive()
    check(archive is not None, "архив создан")
    if archive:
        check(archive.exists(), "файл архива существует")
        check(archive.stat().st_size > 0, "архив не пустой")
        archive.unlink()

    print("\n12) Выключенное копирование")
    off = BackupManager("bs_bk.json", backup_dir="bk_off", keep=5, enabled=False)
    check(off.create() is None, "при выключении копия не создаётся")
    check(not Path("bk_off").exists(), "каталог не создаётся")

    print("\n13) API панели")
    from test_smoke import install_stub_sdk

    install_stub_sdk()
    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    await app.init_runtime_for_tests()
    app.backup_manager = manager

    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/api/backups")
        data = await resp.json()
        check(resp.status == 200, "GET /api/backups отвечает", str(resp.status))
        check("stats" in data and "items" in data, "ответ содержит сводку и список")

        resp = await client.post("/api/backups")
        data = await resp.json()
        check(resp.status == 200, "POST создаёт копию", str(resp.status))
        check("file" in data, "возвращено имя файла", str(data))
        api_name = data.get("file")

        resp = await client.post(f"/api/backups/{api_name}/restore", json={})
        check(resp.status == 400, "восстановление без confirm → 400", str(resp.status))

        resp = await client.post(
            f"/api/backups/{api_name}/restore", json={"confirm": "restore"}
        )
        data = await resp.json()
        check(resp.status == 200, "восстановление с confirm → 200", str(resp.status))
        check(data.get("status") == "ok", "статус ok", str(data))

        resp = await client.delete(f"/api/backups/{api_name}")
        data = await resp.json()
        check(resp.status == 200, "удаление через API", str(resp.status))

        resp = await client.get("/backups")
        html = await resp.text()
        check(resp.status == 200, "страница копий отдаётся")
        for marker in ("bk-rows", "bk-totals", "bk-create", "bk-refresh"):
            check(marker in html, f"элемент {marker} на странице")
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
