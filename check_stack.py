#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка запускаемого окружения: версия SDK, зависимости, конфигурация."""

import sys

REQUIRED = {
    "trueconf": ("python-trueconf-bot", "1.5.5"),
    "aiohttp": ("aiohttp", "3.9"),
    "dotenv": ("python-dotenv", "1.0"),
}

print(f"Python: {sys.version.split()[0]}")

ok = True
for module, (package, minimum) in REQUIRED.items():
    try:
        __import__(module)
    except Exception as exc:
        print(f"❌ {package}: не установлен ({type(exc).__name__}) — pip install -r requirements.txt")
        ok = False

if ok:
    from importlib import metadata

    for package in ("python-trueconf-bot", "aiohttp", "python-dotenv"):
        try:
            print(f"✅ {package} {metadata.version(package)}")
        except Exception:
            print(f"⚠️ {package}: версия не определена")

    import trueconf

    for attr in ("Bot", "Dispatcher", "Router", "Message", "ParseMode"):
        if not hasattr(trueconf, attr):
            print(f"❌ SDK несовместим: нет trueconf.{attr}")
            ok = False

    try:
        from trueconf.exceptions import ApiErrorException  # noqa: F401
        from trueconf.utils import safe_split_text  # noqa: F401
    except Exception as exc:
        print(f"❌ SDK несовместим: {exc}")
        ok = False

    try:
        import config

        missing = [name for name in ("TRUECONF_SERVER", "TRUECONF_PASSWORD") if not getattr(config, name, None)]
        if missing:
            print(f"⚠️ Не заданы: {', '.join(missing)} (проверьте .env)")
    except Exception as exc:
        print(f"⚠️ config.py: {exc}")

    try:
        import config
        from tcbot.localadmin import is_valid_hash

        mode = str(getattr(config, "WEBUI_AUTH", "none")).lower()
        print(f"🔐 Вход в панель: {mode}")

        if mode in ("both", "local", "keycloak"):
            password_hash = getattr(config, "LOCAL_ADMIN_PASSWORD_HASH", "")
            password = getattr(config, "LOCAL_ADMIN_PASSWORD", "")
            if password_hash and not is_valid_hash(password_hash):
                print(
                    "❌ LOCAL_ADMIN_PASSWORD_HASH не является нашим хэшем "
                    "(pbkdf2_sha256$...). Похоже, туда записан client_secret или пароль."
                )
                ok = False
            elif password_hash and password:
                print("⚠️ Заданы и пароль, и хэш — будет использован пароль")
    except Exception as exc:
        print(f"⚠️ Проверка local-admin: {exc}")

print("✅ Окружение готово" if ok else "❌ Окружение не готово")
raise SystemExit(0 if ok else 1)
