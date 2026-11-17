# -*- coding: utf-8 -*-
"""
Данные из SDK для диагностики в админке.

Что даёт SDK помимо состояния соединения:

    get_chats()                — все чаты бота: название, тип, непрочитанные
    get_chat_participants()    — участники чата и их роли
    get_chat_by_id()           — сведения об одном чате
    get_file_upload_limits()   — лимит размера файла и запрещённые расширения
    get_chat_history()         — последние сообщения чата
    health_check()             — состояние WebSocket и авторизации
    me_id / me_chat            — идентификаторы бота
    server_name/server_version — параметры сервера

Это позволяет в панели показать, например, что канал ведёт в архивный или
пустой чат, что бот в чате не участник, или что сообщение не пройдёт по
ограничениям сервера.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot")

# Типы чатов TrueConf (chat_type в ответе getChats)
CHAT_TYPES = {
    1: "личный",
    2: "групповой",
    3: "канал",
    4: "избранное",
    5: "избранное",
    6: "групповой",
}

# Роли участников
CHAT_ROLES = {
    "OWNER": "владелец",
    "ADMIN": "администратор",
    "USER": "участник",
    "PARTICIPANT": "участник",
    "READER": "читатель",
}


async def _maybe_await(value: Any) -> Any:
    """Возвращает значение, дожидаясь его только если это корутина."""
    import inspect

    if inspect.isawaitable(value):
        try:
            return await value
        except Exception as exc:
            logger.debug(f"ошибка получения значения: {exc}")
            return None
    return value


def _chat_type_name(chat_type: Any) -> str:
    """Понятное имя типа чата."""
    if chat_type is None:
        return "—"
    try:
        value = int(getattr(chat_type, "value", chat_type))
    except (TypeError, ValueError):
        return str(chat_type)
    return CHAT_TYPES.get(value, f"тип {value}")


def _role_name(role: Any) -> str:
    if role is None:
        return "—"
    text = str(getattr(role, "name", role)).upper()
    return CHAT_ROLES.get(text, str(getattr(role, "value", role)).lower())


@dataclass
class ChannelInfo:
    """Сведения о чате канала, полученные из SDK."""

    name: str
    chat_id: str
    ok: bool = False
    reason: str = ""
    title: Optional[str] = None
    chat_type: Optional[str] = None
    unread: Optional[int] = None
    participants: int = 0
    bot_is_member: Optional[bool] = None
    bot_role: Optional[str] = None
    last_message_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "chat_id": self.chat_id,
            "ok": self.ok,
            "reason": self.reason,
            "title": self.title,
            "chat_type": self.chat_type,
            "unread": self.unread,
            "participants": self.participants,
            "bot_is_member": self.bot_is_member,
            "bot_role": self.bot_role,
            "last_message_at": self.last_message_at,
        }


class SdkInspector:
    """
    Собирает данные из SDK по запросу.

    Все методы терпимы к ошибкам: если сервер не ответил, возвращается
    понятная причина, а не исключение — панель не должна падать из-за
    недоступного чата.
    """

    def __init__(self, bot_getter) -> None:
        self._bot_getter = bot_getter

    @property
    def bot(self):
        return self._bot_getter()

    async def identity(self) -> Dict[str, Any]:
        """Идентификаторы бота и параметры сервера."""
        bot = self.bot
        if bot is None:
            return {"available": False}

        result: Dict[str, Any] = {"available": True}
        try:
            result["me_id"] = bot.me_id
        except Exception:
            result["me_id"] = None
        # server_name и server_version — async_cached_property: это корутины,
        # но подставить их может и обычное значение (заглушки в тестах).
        result["server_name"] = await _maybe_await(getattr(bot, "server_name", None))
        result["server_version"] = await _maybe_await(getattr(bot, "server_version", None))
        try:
            result["health"] = bot.health_check()
        except Exception:
            result["health"] = {}
        return result

    async def chats(self, count: int = 50, page: int = 1) -> Dict[str, Any]:
        """Список чатов бота."""
        bot = self.bot
        if bot is None:
            return {"available": False, "chats": []}
        try:
            response = await bot.get_chats(count=count, page=page)
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}", "chats": []}

        items: List[Dict[str, Any]] = []
        for chat in getattr(response, "chats", []) or []:
            last = getattr(chat, "last_message", None)
            items.append({
                "chat_id": getattr(chat, "chat_id", ""),
                "title": getattr(chat, "title", None),
                "chat_type": _chat_type_name(getattr(chat, "chat_type", None)),
                "unread": getattr(chat, "unread_messages", None),
                "last_message_at": getattr(last, "timestamp", None) if last else None,
            })
        return {"available": True, "count": len(items), "chats": items}

    async def channel_health(
        self,
        channels: Dict[str, Dict[str, Any]],
        inspect_limit: int = 12,
    ) -> Dict[str, Any]:
        """
        Проверяет каналы бота через SDK.

        Для каждого канала (до inspect_limit) выясняет: существует ли чат,
        как он называется, сколько в нём участников и состоит ли там бот.
        Это сразу показывает каналы, ведущие в никуда.
        """
        bot = self.bot
        if bot is None:
            return {"available": False, "items": []}

        items: List[ChannelInfo] = []
        try:
            me_id = bot.me_id
        except Exception:
            me_id = None

        for index, (name, info) in enumerate(channels.items()):
            chat_id = str(info.get("chat_id", ""))
            entry = ChannelInfo(name=name, chat_id=chat_id)

            if not chat_id:
                entry.reason = "не задан chat_id"
                items.append(entry)
                continue

            if index >= inspect_limit:
                # Сверх лимита не проверяем, но не считаем проблемой
                entry.reason = "не проверялся (лимит)"
                items.append(entry)
                continue

            try:
                chat = await bot.get_chat_by_id(chat_id)
            except Exception as exc:
                entry.reason = f"чат не найден: {type(exc).__name__}"
                items.append(entry)
                continue

            entry.ok = True
            entry.title = getattr(chat, "title", None)
            entry.chat_type = _chat_type_name(getattr(chat, "chat_type", None))
            entry.unread = getattr(chat, "unread_messages", None)
            last = getattr(chat, "last_message", None)
            entry.last_message_at = getattr(last, "timestamp", None) if last else None

            try:
                parts = await bot.get_chat_participants(
                    chat_id=chat_id, page_size=20, page_number=1
                )
                plist = getattr(parts, "participants", []) or []
                entry.participants = len(plist)
                for participant in plist:
                    if me_id and getattr(participant, "user_id", None) == me_id:
                        entry.bot_is_member = True
                        entry.bot_role = _role_name(getattr(participant, "role", None))
                        break
                else:
                    entry.bot_is_member = False
            except Exception:
                entry.participants = 0
                entry.bot_is_member = None

            items.append(entry)

        problems = [
            item for item in items
            if not item.ok and item.reason != "не проверялся (лимит)"
        ]
        return {
            "available": True,
            "total": len(channels),
            "inspected": min(len(channels), inspect_limit),
            "problems": len(problems),
            "items": [item.to_dict() for item in items],
        }

    async def limits(self) -> Dict[str, Any]:
        """Ограничения сервера на файлы."""
        bot = self.bot
        if bot is None:
            return {"available": False}
        try:
            limits = await bot.get_file_info_upload_limits()
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

        max_size = getattr(limits, "max_size", None)
        extensions = getattr(limits, "extensions", None)
        return {
            "available": True,
            "max_size_bytes": max_size,
            "max_size_mb": round(max_size / 1024 / 1024, 1) if max_size else None,
            "extensions_mode": getattr(extensions, "mode", None) if extensions else None,
            "extensions": list(getattr(extensions, "list", []) or []) if extensions else [],
        }

    async def history(self, chat_id: Optional[str], count: int = 5) -> Dict[str, Any]:
        """Последние сообщения чата."""
        bot = self.bot
        if bot is None or not chat_id:
            return {"available": False, "messages": []}
        try:
            response = await bot.get_chat_history(chat_id=chat_id, count=count)
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}", "messages": []}

        messages: List[Dict[str, Any]] = []
        for message in getattr(response, "messages", []) or []:
            author = getattr(message, "author", None)
            messages.append({
                "message_id": str(getattr(message, "message_id", "")),
                "timestamp": getattr(message, "timestamp", None),
                "author": getattr(author, "id", None) if author else None,
                "type": str(getattr(message, "type", "")),
            })
        return {"available": True, "count": len(messages), "messages": messages}
