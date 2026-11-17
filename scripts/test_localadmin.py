#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка локального администратора и гибридного входа (SSO + local)."""

import asyncio
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ.setdefault("LOG_DIR", "logs_la")
os.environ.setdefault("STATE_FILE", "bs_la.json")
os.environ.setdefault("OUTBOX_FILE", "ob_la.json")
os.environ["DELIVERED_FILE"] = "dl_test.json"
os.environ.setdefault("LOCAL_ADMIN_PASSWORD_FILE", "local-admin-test-pw.txt")

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


def cleanup():
    import shutil

    for name in ("logs_la", "bs_la.json", "ob_la.json", "local-admin-test-pw.txt"):
        p = Path(name)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


async def main() -> int:
    from test_smoke import install_stub_sdk

    install_stub_sdk()

    from tcbot.localadmin import LocalAdminStore, hash_password, verify_password, password_problems

    print("1) Хэширование паролей")
    h = hash_password("SuperSecret123", iterations=1000)
    check(h.startswith("pbkdf2_sha256$"), "формат pbkdf2_sha256")
    check(verify_password("SuperSecret123", h), "верный пароль принимается")
    check(not verify_password("WrongPass123", h), "неверный пароль отклоняется")
    check(not verify_password("", h), "пустой пароль отклоняется")
    check(hash_password("same", iterations=1000) != hash_password("same", iterations=1000),
          "соль разная — хэши различаются")
    check("SuperSecret123" not in h, "пароль не хранится в открытом виде")

    print("\n2) Политика паролей")
    check(bool(password_problems("short1")), "короткий пароль отклоняется")
    check(bool(password_problems("onlyletters")), "пароль без цифр отклоняется")
    check(bool(password_problems("123456789012")), "пароль без букв отклоняется")
    check(not password_problems("GoodPass1234"), "нормальный пароль принимается")

    print("\n3) Хранилище и вход")
    state = {"local_admin": {}}

    def getter():
        return state

    def setter(data):
        state["local_admin"] = data.get("local_admin", {})

    store = LocalAdminStore(
        state_getter=getter,
        state_setter=setter,
        username="local-admin",
        password="TestPassword123",
        initial_password_file="local-admin-test-pw.txt",
    )
    check(store.stats()["has_password"], "пароль сохранён в состоянии")
    check("password" not in str(state["local_admin"]).lower() or "hash" in str(state["local_admin"]).lower(),
          "в состоянии только хэш")
    ok, reason = store.authenticate("local-admin", "TestPassword123", "10.0.0.1")
    check(ok, "верный логин/пароль", reason)
    ok, reason = store.authenticate("local-admin", "wrong", "10.0.0.1")
    check(not ok and "неверный" in reason, "неверный пароль отклонён", reason)
    ok, _ = store.authenticate("otheruser", "TestPassword123", "10.0.0.1")
    check(not ok, "неверный логин отклонён")

    print("\n4) Блокировка после серии неудач")
    store2 = LocalAdminStore(
        state_getter=getter, state_setter=setter, username="local-admin",
        password="TestPassword123", initial_password_file="local-admin-test-pw.txt",
    )
    for _ in range(5):
        store2.authenticate("local-admin", "bad", "10.9.9.9")
    ok, reason = store2.authenticate("local-admin", "TestPassword123", "10.9.9.9")
    check(not ok, "после 5 неудач вход блокируется", reason)
    check("попыток" in reason, "сообщение о блокировке", reason)
    # другой IP не заблокирован
    ok, _ = store2.authenticate("local-admin", "TestPassword123", "10.9.9.10")
    check(ok, "другой IP не заблокирован")

    print("\n5) Смена пароля")
    ok, reason = store.change_password("TestPassword123", "short", "10.0.0.1")
    check(not ok, "слабый пароль не принимается", reason)
    ok, reason = store.change_password("wrong", "NewPassword456", "10.0.0.1")
    check(not ok, "неверный текущий пароль отклонён", reason)
    ok, reason = store.change_password("TestPassword123", "NewPassword456", "10.0.0.1")
    check(ok, "пароль изменён", reason)
    ok, _ = store.authenticate("local-admin", "NewPassword456", "10.0.0.2")
    check(ok, "новый пароль работает")
    ok, _ = store.authenticate("local-admin", "TestPassword123", "10.0.0.2")
    check(not ok, "старый пароль больше не работает")

    print("\n6) Проверка формата хэша (защита от опечаток в .env)")
    from tcbot.localadmin import is_valid_hash

    check(not is_valid_hash("deadbeefcafe1234567890abcdef"), "client_secret не принимается за хэш")
    check(not is_valid_hash("ExamplePassword123"), "обычный пароль не принимается за хэш")
    check(not is_valid_hash(""), "пустая строка не принимается")
    check(not is_valid_hash("pbkdf2_sha256$1000$abc"), "обрезанный хэш отклоняется")
    check(is_valid_hash(hash_password("RealPassword123", iterations=1000)),
          "настоящий хэш принимается")

    print("\n6b) Пароль имеет приоритет над битым хэшем")
    state_bad = {"local_admin": {}}

    def getter_b():
        return state_bad

    def setter_b(data):
        state_bad["local_admin"] = data.get("local_admin", {})

    store_b = LocalAdminStore(
        state_getter=getter_b, state_setter=setter_b, username="local-admin",
        password="GoodPassword123",
        password_hash="deadbeefcafe1234567890abcdef",   # как в сломанном .env
        initial_password_file="local-admin-test-pw.txt",
    )
    ok, reason = store_b.authenticate("local-admin", "GoodPassword123", "10.1.1.1")
    check(ok, "вход работает, несмотря на битый хэш в конфиге", reason)

    print("\n6c) Только битый хэш — генерируется новый пароль")
    state_only_hash = {"local_admin": {}}

    def getter_c():
        return state_only_hash

    def setter_c(data):
        state_only_hash["local_admin"] = data.get("local_admin", {})

    store_c = LocalAdminStore(
        state_getter=getter_c, state_setter=setter_c, username="local-admin",
        password_hash="not-a-real-hash",
        initial_password_file="local-admin-test-pw.txt",
    )
    check(store_c.stats()["has_password"], "сгенерирован рабочий пароль вместо битого хэша")
    check(is_valid_hash(state_only_hash["local_admin"]["password_hash"]),
          "в состоянии лежит валидный хэш")

    print("\n6) Автогенерация пароля при первом запуске")
    empty_state = {"local_admin": {}}

    def getter3():
        return empty_state

    def setter3(data):
        empty_state["local_admin"] = data.get("local_admin", {})

    store3 = LocalAdminStore(
        state_getter=getter3, state_setter=setter3, username="local-admin",
        initial_password_file="local-admin-test-pw.txt",
    )
    check(store3.stats()["has_password"], "пароль сгенерирован автоматически")
    check(Path("local-admin-test-pw.txt").exists(), "стартовый пароль записан в файл")

    print("\n7) Гибридный режим в приложении")
    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    await app.init_runtime_for_tests()
    app.auth_manager.mode = "both"
    app.auth_manager.local = LocalAdminStore(
        state_getter=lambda: app.state_manager.raw,
        state_setter=lambda d: app.state_manager.set_local_admin(d.get("local_admin", {})),
        username="local-admin",
        password="GuiPassword123",
        initial_password_file="local-admin-test-pw.txt",
    )

    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/login")
        html = await resp.text()
        check(resp.status == 200, "GET /login отдаёт страницу входа", str(resp.status))
        check("local-admin" in html and "password" in html, "форма локального входа есть")

        resp = await client.post(
            "/auth/local",
            data={"username": "local-admin", "password": "GuiPassword123", "next": "/"},
            allow_redirects=False,
        )
        check(resp.status == 302, "успешный локальный вход → редирект", str(resp.status))
        check(resp.cookies.get("tcbot_session") is not None, "сессия установлена")

        resp = await client.get("/api/status")
        check(resp.status == 200, "API доступен после локального входа", str(resp.status))

        resp = await client.get("/api/me")
        me = await resp.json()
        check(me["user"]["via"] == "local", "способ входа отмечен как local")
        check(me["user"]["is_admin"] is True, "local-admin имеет полные права")

        resp = await client.post("/api/settings", json={"max_retries": 2})
        check(resp.status == 200, "local-admin может менять настройки", str(resp.status))

        print("\n8) Неверный пароль и отказ")
        resp = await client.post("/auth/local", data={"username": "local-admin", "password": "nope", "next": "/"})
        check(resp.status == 401, "неверный пароль → 401", str(resp.status))
        counter = await resp.text()
        check("неверный логин или пароль" in counter, "страница входа показывает ошибку")

        print("\n9) Смена пароля через API")
        resp = await client.get("/api/local-admin")
        data = await resp.json()
        check(resp.status == 200 and data["local_admin"]["enabled"], "GET /api/local-admin")

        resp = await client.post("/api/local-admin", json={"current_password": "GuiPassword123", "new_password": "ChangedPass456"})
        check(resp.status == 200, "POST /api/local-admin меняет пароль", str(resp.status))

        resp = await client.post("/api/local-admin", json={"current_password": "GuiPassword123", "new_password": "AnotherPass789"})
        check(resp.status == 400, "старый пароль больше не подходит", str(resp.status))

        print("\n10) Выход")
        resp = await client.get("/auth/logout", allow_redirects=False)
        check(resp.status == 302, "logout редиректит", str(resp.status))
        resp = await client.get("/api/status")
        check(resp.status == 401, "после выхода API закрыт", str(resp.status))
    finally:
        await client.close()

    print("\n11) Режим token сохраняет работоспособность")
    app.auth_manager = app.AuthManager(mode="token", token="svc-token")
    client2 = TestClient(TestServer(await app.build_web_app()))
    await client2.start_server()
    try:
        resp = await client2.get("/api/status", headers={"X-WebUI-Token": "svc-token"})
        check(resp.status == 200, "сервисный токен работает", str(resp.status))
        resp = await client2.get("/api/me", headers={"X-WebUI-Token": "svc-token"})
        me = await resp.json()
        check(me.get("authenticated") is True, "/api/me сообщает доступ", str(me)[:120])
        check(me["user"]["via"] == "token", "способ входа token")
        check(me["user"]["is_admin"] is True, "сервисный доступ с правами admin")

        resp = await client2.get("/api/me")
        check(resp.status == 401, "без токена /api/me закрыт", str(resp.status))
    finally:
        await client2.close()

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