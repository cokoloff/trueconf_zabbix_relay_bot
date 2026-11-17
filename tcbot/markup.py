# -*- coding: utf-8 -*-
"""
Формирование текста сообщений с учётом особенностей TrueConf Server.

Почему это нужно (проверено на живом сервере 5.5.8):

1. Обратные кавычки в MARKDOWN сервер превращает в тег code lang="pre".
   Клиент TrueConf этот тег не поддерживает и показывает его как текст —
   отсюда поехавший код в /help. Поэтому backticks не используем никогда.

2. Сырые угловые скобки вида <id> сервер считает HTML-тегом и выбрасывает
   вместе с содержимым (в логах видно <id></id>). Значит любые < и > в тексте
   обязаны быть экранированы как &lt; и &gt;.

3. В MARKDOWN строки, начинающиеся с дефиса, склеиваются: перевод строки
   пропадает (Firing- alertname = X- job = Y). Маркер • ведёт себя корректно.

4. HTML-режим сохраняет разметку один-в-один и не имеет пунктов 1-3, поэтому
   для структурированных сообщений (справка, статус) используем именно его.

Итог: строим HTML, где каждое значение из внешнего мира проходит через escape.
"""

from __future__ import annotations

from html import escape
from typing import Iterable, Optional


def esc(value: Optional[object]) -> str:
    """Экранирует текст для HTML-разметки TrueConf."""
    if value is None:
        return ""
    return escape(str(value), quote=False)


class MessageBuilder:
    """
    Собирает HTML-сообщение: заголовки, строки, списки, выделение.

    Пример:
        msg = MessageBuilder()
        msg.title("Бот v12")
        msg.line("Ваш ID: ", user_id)
        msg.blank()
        msg.heading("Публичные команды:")
        msg.bullet("/help", "- эта справка")
        text = msg.build()
    """

    def __init__(self) -> None:
        self._parts: list[str] = []

    def raw(self, html: str) -> "MessageBuilder":
        """Добавляет уже готовый HTML (без экранирования)."""
        self._parts.append(html)
        return self

    def text(self, value: object) -> "MessageBuilder":
        """Добавляет экранированный текст без перевода строки."""
        self._parts.append(esc(value))
        return self

    def bold(self, value: object) -> "MessageBuilder":
        self._parts.append("<b>" + esc(value) + "</b>")
        return self

    def italic(self, value: object) -> "MessageBuilder":
        self._parts.append("<i>" + esc(value) + "</i>")
        return self

    def code(self, value: object) -> "MessageBuilder":
        """
        Выделяет команду или идентификатор.

        Тега code в TrueConf нет, поэтому оставляем обычный текст: раньше
        именно он и превращался в невидимый клиенту тег.
        """
        self._parts.append(esc(value))
        return self

    def line(self, *chunks: object, bold: bool = False) -> "MessageBuilder":
        """Одна строка: аргументы склеиваются, спецсимволы экранируются."""
        rendered = [esc(chunk) for chunk in chunks if chunk is not None]
        text = "".join(rendered)
        if bold and text:
            self._parts.append("<b>" + text + "</b>")
        else:
            self._parts.append(text)
        return self

    def heading(self, value: object) -> "MessageBuilder":
        """Заголовок раздела."""
        self._parts.append("<b>" + esc(value) + "</b>")
        return self

    def title(self, value: object) -> "MessageBuilder":
        """Крупный заголовок сообщения."""
        self._parts.append("<b>" + esc(value) + "</b>")
        return self

    def blank(self) -> "MessageBuilder":
        """Пустая строка."""
        self._parts.append("")
        return self

    def bullet(self, command: object, description: object = "") -> "MessageBuilder":
        """
        Пункт списка.

        Маркер • выбран вместо дефиса, потому что дефис в начале строки
        в markdown склеивает соседние строки.
        """
        tail = " " + esc(description) if description else ""
        self._parts.append("• " + esc(command) + tail)
        return self

    def rule(self) -> "MessageBuilder":
        """Горизонтальная черта из символов (HTML hr клиент не рисует)."""
        self._parts.append("─" * 20)
        return self

    def extend(self, items: Iterable[object]) -> "MessageBuilder":
        for item in items:
            self.line(item)
        return self

    def build(self) -> str:
        """Склеивает строки через br - единственный рабочий перенос в TrueConf."""
        return "<br>".join(self._parts)

    def __bool__(self) -> bool:
        return bool(self._parts)


def plain_text(html: str) -> str:
    """
    Грубое превращение нашего HTML в обычный текст.

    Нужно для запасной отправки без разметки, если сервер отклонит HTML.
    """
    return (
        html.replace("<br>", "\n")
        .replace("<b>", "")
        .replace("</b>", "")
        .replace("<i>", "")
        .replace("</i>", "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def safe_text(value: object) -> str:
    """
    Готовит произвольный текст (например, тело вебхука) к отправке.

    Экранирует угловые скобки и амперсанд, чтобы сервер не принял их за теги,
    и заменяет markdown-дефис в начале строки на •, иначе строки склеятся.
    """
    if value is None:
        return ""
    text = str(value)
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("- "):
            indent = line[: len(line) - len(stripped)]
            line = indent + "• " + stripped[2:]
        lines.append(line)
    return escape("\n".join(lines), quote=False)
