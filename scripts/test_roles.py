#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка извлечения ролей Keycloak и прав доступа."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


def make_sso(admin_roles=None, viewer_roles=None, local_admins=None):
    from tcbot.sso import KeycloakSSO

    return KeycloakSSO(
        server_url="https://auth.example.com",
        realm="aquarius",
        client_id="tcbot-admin",
        admin_roles=admin_roles or ["tcbot-admin"],
        viewer_roles=viewer_roles or ["tcbot-viewer"],
        local_admins=local_admins or [],
    )


def main() -> int:
    from tcbot.sso import SSOUser

    sso = make_sso()

    print("1) Роли из access_token (realm_access)")
    access = {"realm_access": {"roles": ["tcbot-admin", "offline_access"]}}
    roles = sso.extract_roles(access)
    check("tcbot-admin" in roles, "realm_access разобран", str(roles))

    print("\n2) Роли клиента (resource_access)")
    access = {"resource_access": {"tcbot-admin": {"roles": ["tcbot-viewer"]}}}
    roles = sso.extract_roles(access)
    check("tcbot-viewer" in roles, "resource_access разобран", str(roles))

    print("\n3) Группы Keycloak")
    access = {"groups": ["/aq/infra/tcbot-admin", "/aq/staff"]}
    roles = sso.extract_roles(access)
    check("tcbot-admin" in roles, "группа даёт роль по последнему сегменту", str(roles))
    check("staff" in roles, "обычная группа тоже попадает", str(roles))

    print("\n4) Плоский список roles")
    check("tcbot-admin" in sso.extract_roles({"roles": ["tcbot-admin"]}), "claims.roles разобран")

    print("\n5) Пустой набор ролей")
    check(sso.extract_roles({}) == [], "без claims ролей нет")
    check(sso.extract_roles({"realm_access": {}}) == [], "пустой realm_access")

    print("\n6) Права: роли дают доступ")
    user = SSOUser(subject="s", username="user1", roles=["tcbot-admin"])
    is_admin, is_viewer = sso._resolve_rights(user, ["tcbot-admin"])
    check(is_admin and is_viewer, "роль админа даёт полный доступ")

    user = SSOUser(subject="s", username="user1", roles=["tcbot-viewer"])
    is_admin, is_viewer = sso._resolve_rights(user, ["tcbot-viewer"])
    check(not is_admin and is_viewer, "роль просмотра даёт только чтение")

    user = SSOUser(subject="s", username="user1", roles=[])
    is_admin, is_viewer = sso._resolve_rights(user, [])
    check(not is_admin and not is_viewer, "без ролей доступа нет")

    print("\n7) ADMIN_IDS даёт доступ без ролей Keycloak")
    sso2 = make_sso(local_admins=["admin@example.com"])

    # совпадение по e-mail
    user = SSOUser(subject="x", username="admin", email="admin@example.com", roles=[])
    is_admin, _ = sso2._resolve_rights(user, [])
    check(is_admin, "совпадение по e-mail")

    # Keycloak вернул логин без домена, в ADMIN_IDS — с доменом
    user = SSOUser(subject="x", username="admin", email="", roles=[])
    is_admin, _ = sso2._resolve_rights(user, [])
    check(is_admin, "логин без домена совпадает с ADMIN_IDS с доменом")

    # обратный случай
    sso3 = make_sso(local_admins=["admin"])
    user = SSOUser(subject="x", username="admin", email="admin@example.com", roles=[])
    is_admin, _ = sso3._resolve_rights(user, [])
    check(is_admin, "ADMIN_IDS без домена совпадает с e-mail")

    # чужой пользователь
    user = SSOUser(subject="x", username="someone", email="someone@example.com", roles=[])
    is_admin, _ = sso2._resolve_rights(user, [])
    check(not is_admin, "посторонний без ролей не получает доступ")

    print("\n8) Приоритет ролей Keycloak")
    sso4 = make_sso(admin_roles=["Administrators"], viewer_roles=["Users"])
    user = SSOUser(subject="x", username="u", roles=["administrators"])
    is_admin, _ = sso4._resolve_rights(user, ["administrators"])
    check(is_admin, "сравнение ролей без учёта регистра")

    print("\n9) Диагностика claims")
    summary = sso.debug_claims({"realm_access": {"roles": ["tcbot-admin"]}, "groups": ["/a/b"]})
    check("tcbot-admin" in summary, "сводка показывает realm-роли", summary[:80])

    print()
    if FAILED:
        print(f"❌ Провалено: {len(FAILED)}")
        for item in FAILED:
            print(f"   • {item}")
        return 1
    print("✅ Проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
