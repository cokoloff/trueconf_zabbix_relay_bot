#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка формирования разметки сообщений (без сети)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


def main() -> int:
    from tcbot.markup import MessageBuilder, esc, plain_text, safe_text

    print("1) Экранирование")
    check(esc("<id>") == "&lt;id&gt;", "угловые скобки экранируются", esc("<id>"))
    check(esc("A & B") == "A &amp; B", "амперсанд экранируется", esc("A & B"))
    check(esc(None) == "", "None даёт пустую строку")
    check(esc('"x"') == '"x"', "кавычки не трогаем (не нужны в тексте)")

    print("\n2) Никаких backticks и тегов code")
    build = MessageBuilder()
    build.bullet("/admin_add <id>", "— добавить")
    result = build.build()
    check("`" not in result, "нет обратных кавычек (сервер сделал бы <code>)")
    check("<code" not in result, "нет тега code")
    check("&lt;id&gt;" in result, "угловые скобки экранированы", result)

    print("\n3) Переводы строк через br")
    build = MessageBuilder()
    build.line("первая")
    build.line("вторая")
    result = build.build()
    check("<br>" in result, "строки соединяются через <br>", result)
    check("\n" not in result, "сырых переводов строк нет")

    print("\n4) Маркеры списка")
    build = MessageBuilder()
    build.bullet("/help", "— справка")
    result = build.build()
    check(result.startswith("• "), "используется маркер •", result)
    check("- " not in result.split("• ")[0], "дефис не в начале строки")

    print("\n5) Заголовки")
    build = MessageBuilder()
    build.title("Заголовок")
    check(build.build() == "<b>Заголовок</b>", "title даёт жирный текст", build.build())

    print("\n6) Опасный ввод из вебхука")
    check("&lt;script&gt;" in safe_text("<script>"), "теги из вебхука обезврежены",
          safe_text("<script>"))
    check("A &amp; B" in safe_text("A & B"), "амперсанд обезврежен")
    converted = safe_text("Firing\n - alertname = X")
    check("•" in converted, "дефис списка заменён на •", converted)

    print("\n7) Обратное превращение в текст")
    build = MessageBuilder()
    build.line("Строка один")
    build.line("Строка два")
    plain = plain_text(build.build())
    check("<br>" not in plain and "<b>" not in plain, "теги удалены", plain)
    check(plain.count("\n") == 1, "переводы строк восстановлены", repr(plain))

    print("\n8) Полная справка")
    build = MessageBuilder()
    build.title("👋 TrueConf Zabbix Bot v12.0")
    build.line("Ваш ID: ", "user@domain")
    build.blank()
    build.heading("Команды:")
    build.bullet("/admin_add <id>", "— добавить")
    build.bullet("/register <имя>", "— создать")
    full = build.build()
    check("`" not in full, "нет backticks во всей справке")
    check(full.count("&lt;") == 2, "оба угловых аргумента экранированы", str(full.count("&lt;")))
    check("</code>" not in full, "нет закрывающих тегов code")

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
