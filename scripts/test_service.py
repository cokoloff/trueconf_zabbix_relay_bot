#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка перезапуска службы из панели и меток времени в логах."""

import asyncio
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ["LOG_DIR"] = "logs_svc"
os.environ["STATE_FILE"] = "bs_svc.json"
os.environ["OUTBOX_FILE"] = "ob_svc.json"
os.environ["DELIVERED_FILE"] = "dl_svc.json"
os.environ["LOCAL_ADMIN_PASSWORD_FILE"] = "la_svc.txt"
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

    for name in ("logs_svc", "bs_svc.json", "ob_svc.json", "dl_svc.json",
                 "la_svc.txt", "service_call.log"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


async def main() -> int:
    print("1) Метки времени в логах")
    from tcbot import logging_setup

    formatter = logging_setup.LocalTimeFormatter("%(asctime)s", "%Y-%m-%d %H:%M:%S")
    record = logging.LogRecord("t", logging.INFO, "f", 1, "msg", None, None)
    record.created = 1700000000.0

    os.environ["LOG_TZ"] = "0"
    logging_setup.LOG_TZ_OFFSET = 0.0
    logging_setup._TZ_NAME = ""
    utc_text = formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")

    logging_setup.LOG_TZ_OFFSET = 3.0
    msk_text = formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")

    check(utc_text != msk_text, "смещение меняет метку", f"{utc_text} / {msk_text}")
    from datetime import datetime, timedelta, timezone

    expected_utc = datetime.fromtimestamp(1700000000.0, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    expected_msk = datetime.fromtimestamp(
        1700000000.0, timezone(timedelta(hours=3))
    ).strftime("%Y-%m-%d %H:%M:%S")
    check(utc_text == expected_utc, "UTC-метка верна", f"{utc_text} != {expected_utc}")
    check(msk_text == expected_msk, "московская метка верна", f"{msk_text} != {expected_msk}")

    logging_setup._TZ_NAME = "UTC"
    utc_named = formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")
    check(utc_named == expected_utc, "LOG_TZ_NAME=UTC даёт UTC", utc_named)
    logging_setup._TZ_NAME = ""

    print("\n2) API управления службой")
    from test_smoke import install_stub_sdk

    install_stub_sdk()
    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    Path("dl_svc.json").unlink(missing_ok=True)
    await app.init_runtime_for_tests()

    print("\n2a) Перезапуск выключен")
    app.SERVICE_RESTART_ENABLED = False
    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.post("/api/service/restart", json={"confirm": "restart"})
        check(resp.status == 403, "выключено → 403", str(resp.status))
        body = await resp.json()
        check("error" in body, "сказано, что выключено")
        check("hint" in body and "SERVICE_RESTART_ENABLED" in body["hint"],
              "подсказка про настройку", str(body.get("hint")))

        resp = await client.get("/api/service/status")
        data = await resp.json()
        check(resp.status == 200, "статус отвечает", str(resp.status))
        check(data.get("restart_enabled") is False, "в статусе перезапуск выключен")
        check("service" in data, "в статусе есть имя службы")
        check("under_systemd" in data, "в статусе есть признак systemd")
    finally:
        await client.close()

    print("\n2b) Перезапуск включён — нужен подтверждающий параметр")
    app.SERVICE_RESTART_ENABLED = True
    app.SYSTEMD_SERVICE = "trueconf-bot"
    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.post("/api/service/restart", json={})
        check(resp.status == 400, "без confirm → 400", str(resp.status))
        body = await resp.json()
        check("confirm" in str(body.get("hint", "")), "подсказка про confirm",
              str(body.get("hint")))

        resp = await client.post("/api/service/restart", json={"confirm": "no"})
        check(resp.status == 400, "неверный confirm → 400", str(resp.status))

        resp = await client.get("/api/service/status")
        data = await resp.json()
        check(data.get("restart_enabled") is True, "в статусе перезапуск включён")
        check(data.get("service") == "trueconf-bot", "имя службы из конфига",
              str(data.get("service")))
    finally:
        await client.close()

    print("\n2c) Вызов systemctl формируется верно")
    # Подменяем команду: проверяем, что аргументы именно «restart <служба>»
    received = {}

    class FakeProcess:
        returncode = 0

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs
        return FakeProcess()

    original_exec = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = fake_exec
    try:
        await app._restart_service_task()
        args = received.get("args", ())
        check("restart" in args, "передан аргумент restart", str(args))
        check("trueconf-bot" in args, "передано имя службы", str(args))
        check(args.index("restart") < args.index("trueconf-bot"),
              "порядок: restart, затем служба", str(args))
        check(received.get("kwargs", {}).get("stdout") == asyncio.subprocess.DEVNULL,
              "вывод не перехватывается (иначе PermissionError)")
    finally:
        asyncio.create_subprocess_exec = original_exec

    print("\n2d) Режим перезапуска в Docker")
    import os as _os

    # Вне контейнера — systemd
    saved_container = _os.environ.pop("container", None)
    app.SERVICE_RESTART_MODE = "auto"
    check(app.service_restart_mode() == "systemd",
          "вне контейнера выбран systemd", app.service_restart_mode())

    # Внутри контейнера — exit (контейнер поднимется сам)
    _os.environ["container"] = "docker"
    check(app.service_restart_mode() == "exit",
          "в контейнере выбран exit", app.service_restart_mode())

    # Явные настройки перебивают автовыбор
    app.SERVICE_RESTART_MODE = "systemd"
    check(app.service_restart_mode() == "systemd",
          "явный systemd перебивает автовыбор", app.service_restart_mode())
    app.SERVICE_RESTART_MODE = "exit"
    _os.environ.pop("container", None)
    check(app.service_restart_mode() == "exit",
          "явный exit работает вне контейнера", app.service_restart_mode())
    app.SERVICE_RESTART_MODE = "auto"
    if saved_container:
        _os.environ["container"] = saved_container

    # В режиме exit systemctl не вызывается
    _os.environ["container"] = "docker"
    called = {"exec": False}

    async def boom_exec(*args, **kwargs):
        called["exec"] = True
        raise AssertionError("systemctl не должен вызываться в контейнере")

    original_exec2 = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = boom_exec
    exit_called = {"value": False}
    original_exit = _os._exit
    _os._exit = lambda code: exit_called.__setitem__("value", code)
    try:
        app.SERVICE_RESTART_MODE = "auto"
        await app._restart_service_task("exit")
        check(called["exec"] is False, "в режиме exit systemctl не вызывается")
        check(exit_called["value"] == 0, "процесс завершается с кодом 0",
              str(exit_called["value"]))
    finally:
        asyncio.create_subprocess_exec = original_exec2
        _os._exit = original_exit
        _os.environ.pop("container", None)
        app.SERVICE_RESTART_MODE = "auto"

    print("\n3) Настройки по умолчанию")
    import config

    check(getattr(config, "SYSTEMD_SERVICE", ""), "имя службы задано",
          str(getattr(config, "SYSTEMD_SERVICE", "")))
    check(getattr(config, "SERVICE_RESTART_ENABLED", None) is False,
          "перезапуск выключен по умолчанию",
          str(getattr(config, "SERVICE_RESTART_ENABLED", None)))

    print("\n4) Кнопка в панели")
    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/")
        html = await resp.text()
        check("menu-service-restart" in html, "кнопка есть в разметке")
        check("Перезапустить службу" in html, "подпись кнопки на месте")
        check('style="display:none;"' in html, "кнопка скрыта до проверки прав")
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
