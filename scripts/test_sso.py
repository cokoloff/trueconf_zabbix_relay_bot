#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка SSO-слоя: сессии, роли, защита маршрутов (без внешней сети)."""

import asyncio
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(PROJECT_ROOT)

os.environ.setdefault("LOG_DIR", "logs_sso_t")
os.environ.setdefault("STATE_FILE", "bs_sso_t.json")
os.environ.setdefault("OUTBOX_FILE", "ob_sso_t.json")
os.environ["DELIVERED_FILE"] = "dl_test.json"

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


class FakeSSO:
    """Минимальная замена KeycloakSSO для проверки слоя авторизации."""

    def __init__(self):
        from tcbot.sso import SessionSigner

        self.signer = SessionSigner("test-secret", ttl=60)
        self.cookie_secure = False
        self.redirect_uri = "http://localhost/auth/callback"
        self.logged_in_user = None

    async def build_login_url(self, redirect_uri, next_url="/"):
        return "http://sso/auth", {"state": "s1", "nonce": "n1", "verifier": "v1", "next": next_url}

    async def authenticate(self, code, state_data):
        from tcbot.sso import SSOUser

        return self.logged_in_user

    async def logout_url(self, redirect_uri):
        return "http://sso/logout?redirect=" + redirect_uri


async def main() -> int:
    from test_smoke import install_stub_sdk

    install_stub_sdk()

    from tcbot.auth import AuthManager
    from tcbot.sso import SSOUser

    import bot_multy as app
    from aiohttp.test_utils import TestClient, TestServer

    print("1) Режим token")
    await app.init_runtime_for_tests()
    app.auth_manager = AuthManager(mode="token", token="secret-token")
    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/api/status")
        check(resp.status == 401, "без токена → 401", str(resp.status))
        resp = await client.get("/api/status", headers={"X-WebUI-Token": "secret-token"})
        check(resp.status == 200, "с токеном → 200", str(resp.status))
        resp = await client.get("/health")
        check(resp.status == 200, "health всегда доступен", str(resp.status))
    finally:
        await client.close()

    print("\n2) Режим keycloak — нет сессии")
    fake = FakeSSO()
    app.auth_manager = AuthManager(mode="keycloak", sso=fake)
    client = TestClient(TestServer(await app.build_web_app()))
    await client.start_server()
    try:
        resp = await client.get("/api/status", allow_redirects=False)
        check(resp.status == 401, "API без сессии → 401", str(resp.status))

        resp = await client.get("/", allow_redirects=False)
        check(resp.status in (302, 200), "страница без сессии: редирект или логин", str(resp.status))

        resp = await client.get("/webhook", allow_redirects=False)
        check(resp.status in (404, 405), "вебхук не требует SSO", str(resp.status))

        print("\n3) Вход через callback")
        fake.logged_in_user = SSOUser(
            subject="u1", username="admin1", email="admin1@example.com",
            name="Админ", roles=["tcbot-admin"], is_admin=True, is_viewer=True,
        )
        # готовим state-cookie
        login = await client.get("/auth/login", allow_redirects=False)
        state_cookie = login.cookies.get("tcbot_oidc_state")
        check(login.status == 302, "login редиректит в Keycloak", str(login.status))
        check(state_cookie is not None, "state-cookie установлена")

        client.session.cookie_jar.update_cookies(
            {"tcbot_oidc_state": fake.signer.dumps({"state": "s1", "nonce": "n1", "verifier": "v1", "next": "/"})}
        )
        resp = await client.get("/auth/callback?code=abc&state=s1", allow_redirects=False)
        check(resp.status == 302, "callback принимает код", str(resp.status))
        check(resp.cookies.get("tcbot_session") is not None, "сессия установлена")

        resp = await client.get("/api/status")
        check(resp.status == 200, "с сессией API доступен", str(resp.status))

        resp = await client.get("/api/me")
        me = await resp.json()
        check(me.get("authenticated") is True, "GET /api/me сообщает авторизацию")
        check(me["user"]["is_admin"] is True, "роль admin видна в /api/me")

        print("\n4) Права просмотра")
        fake.logged_in_user = SSOUser(
            subject="u2", username="viewer1", email="viewer1@example.com",
            name="Наблюдатель", roles=["tcbot-viewer"], is_admin=False, is_viewer=True,
        )
        await client.get("/auth/logout", allow_redirects=False)
        client.session.cookie_jar.update_cookies(
            {"tcbot_oidc_state": fake.signer.dumps({"state": "s1", "nonce": "n1", "verifier": "v1", "next": "/"})}
        )
        await client.get("/auth/callback?code=abc&state=s1", allow_redirects=False)
        resp = await client.get("/api/status")
        check(resp.status == 200, "viewer читает статус", str(resp.status))
        resp = await client.post("/api/settings", json={"max_retries": 1})
        check(resp.status == 403, "viewer не может менять настройки", str(resp.status))

        print("\n5) Отказ без роли")
        fake.logged_in_user = SSOUser(
            subject="u3", username="nobody", email="nobody@example.com",
            roles=["other"], is_admin=False, is_viewer=False,
        )
        await client.get("/auth/logout", allow_redirects=False)
        client.session.cookie_jar.update_cookies(
            {"tcbot_oidc_state": fake.signer.dumps({"state": "s1", "nonce": "n1", "verifier": "v1", "next": "/"})}
        )
        resp = await client.get("/auth/callback?code=abc&state=s1", allow_redirects=False)
        check(resp.status == 403, "без роли → 403", str(resp.status))

        print("\n6) Защита от CSRF")
        client.session.cookie_jar.update_cookies(
            {"tcbot_oidc_state": fake.signer.dumps({"state": "OTHER", "nonce": "n1", "verifier": "v1", "next": "/"})}
        )
        resp = await client.get("/auth/callback?code=abc&state=s1", allow_redirects=False)
        check(resp.status == 400, "несовпадение state → 400", str(resp.status))

        print("\n7) Выход")
        resp = await client.get("/auth/logout", allow_redirects=False)
        check(resp.status == 302, "logout редиректит", str(resp.status))
    finally:
        await client.close()

    print("\n8) Подпись сессии")
    from tcbot.sso import SessionSigner

    signer = SessionSigner("key", ttl=60)
    good = signer.dumps({"sub": "1"})
    check(signer.loads(good) is not None, "валидная cookie принимается")
    check(signer.loads(good[:-2] + "xx") is None, "подделанная cookie отклоняется")
    expired = SessionSigner("key", ttl=0).dumps({"sub": "1"})
    await asyncio.sleep(1.1)
    check(SessionSigner("key", ttl=0).loads(expired) is None, "истёкшая cookie отклоняется")

    print("\n8b) Подбор scope для Keycloak")
    from tcbot.sso import KeycloakSSO

    def make_sso(scope: str, accepted: set):
        """SSO с подменённой проверкой scope."""
        client = KeycloakSSO(
            server_url="https://auth.example.com",
            realm="test",
            client_id="tcbot",
            client_secret="secret",
            redirect_uri="https://bot.example.com/auth/callback",
            scope=scope,
            verify_ssl=False,
        )

        async def fake_discovery():
            return {"authorization_endpoint": "https://auth.example.com/auth"}

        async def fake_accepted(value: str) -> bool:
            return set(value.split()) <= accepted

        client.discovery = fake_discovery
        client._scope_accepted = fake_accepted
        return client

    # Keycloak отклонил groups — вход должен работать без него
    sso_groups = make_sso(
        "openid profile email roles groups",
        {"openid", "profile", "email", "roles"},
    )
    resolved = await sso_groups.resolve_scope()
    check("groups" not in resolved.split(), "недоступный scope убран из запроса", resolved)
    check("roles" in resolved.split(), "рабочий scope сохранён", resolved)
    check(resolved.split()[0] == "openid", "openid запрашивается первым", resolved)
    check("groups" in sso_groups._rejected_scopes, "отброшенный scope запомнен",
          str(sso_groups._rejected_scopes))

    # Повторный вход не тратит запросы на проверку
    calls = {"n": 0}
    original = sso_groups._scope_accepted

    async def counting(value: str) -> bool:
        calls["n"] += 1
        return await original(value)

    sso_groups._scope_accepted = counting
    again = await sso_groups.resolve_scope()
    check(again == resolved, "повторный вход даёт тот же scope", again)
    check(calls["n"] <= 1, "повторно не проверяет рабочий набор", str(calls["n"]))

    # Все scope доступны — запрашиваем полный набор
    sso_ok = make_sso(
        "openid profile email roles groups",
        {"openid", "profile", "email", "roles", "groups"},
    )
    full = await sso_ok.resolve_scope()
    check("groups" in full.split(), "доступный scope не отбрасывается", full)

    # Пустой scope — остаётся openid
    sso_empty = make_sso("", {"openid"})
    minimal = await sso_empty.resolve_scope()
    check(minimal == "openid", "без настроек запрашивается только openid", minimal)

    print("\n8c) Настройки scope по умолчанию")
    import config as cfg_module
    default_scope = cfg_module.SSO_SCOPE
    check("openid" in default_scope, "openid запрашивается всегда", default_scope)
    check("roles" in default_scope,
          "roles запрашивается — без него нет ролей", default_scope)
    check("groups" not in default_scope,
          "groups не запрашивается по умолчанию", default_scope)

    # Роли извлекаются без groups
    sso_roles = make_sso("openid profile email roles", {"openid", "profile", "email", "roles"})
    claims = {
        "realm_access": {"roles": ["tcbot-admin", "offline_access"]},
        "resource_access": {"tcbot": {"roles": ["tcbot-viewer"]}},
    }
    extracted = sso_roles.extract_roles(claims)
    check("tcbot-admin" in extracted, "роль из realm_access найдена", str(extracted))
    check("tcbot-viewer" in extracted, "роль клиента найдена", str(extracted))

    # На всякий случай: если роли придут группой, они тоже распознаются
    group_claims = {"realm_access": {"roles": ["offline_access"]},
                    "groups": ["/infra/tcbot-admin"]}
    group_roles = sso_roles.extract_roles(group_claims)
    check("tcbot-admin" in group_roles,
          "роль из groups тоже поддерживается (если scope включат)", str(group_roles))

    print("\n9) Ключи JWKS и разбор токена")
    from tcbot.sso import decode_jwt_unverified

    token = (
        "eyJhbGciOiJSUzI1NiJ9."
        + __import__("base64").urlsafe_b64encode(b'{"sub":"abc","realm_access":{"roles":["tcbot-admin"]}}').decode().rstrip("=")
        + ".sig"
    )
    claims = decode_jwt_unverified(token)
    check(claims.get("sub") == "abc", "payload разбирается без верификации")

    for path in ("logs_sso_t", "bs_sso_t.json", "ob_sso_t.json"):
        p = Path(path)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            import shutil

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