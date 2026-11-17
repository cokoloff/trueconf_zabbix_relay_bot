# -*- coding: utf-8 -*-
"""
Состояние бота, администраторы и менеджер токена.

Всё это вынесено из bot_multy.py и расширено:
    * StateManager — каналы, чат по умолчанию, статистика, история инцидентов;
    * AdminManager — динамический список администраторов с сохранением в state;
    * TokenManager — OAuth-токен с фоновым обновлением и потокобезопасным доступом.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("bot")


# ============================================================================
# СОСТОЯНИЕ
# ============================================================================

class StateManager:
    """Персистентное состояние бота (bot_state.json)."""

    def __init__(self, file_path: str = "bot_state.json", version: str = "11.1"):
        self.file_path = Path(file_path)
        self.version = version
        self.lock = asyncio.Lock()
        self._state = self._load()
        self._state.setdefault("version", version)
        self._state.setdefault("notification_channels", {})
        self._state.setdefault("default_chat", None)
        self._state.setdefault("admins", [])
        self._state.setdefault("error_history", {})
        self._state.setdefault("settings", {
            "delete_messages_enabled": False,
            "error_delete_threshold_hours": 24,
            "error_history_retention_days": 7,
            "max_message_length": 4000,
            "max_retries": 3,
            "retry_delay": 1.0,
        })
        metadata = self._state.setdefault("metadata", {})
        metadata.setdefault("messages_sent", 0)
        metadata.setdefault("messages_failed", 0)
        metadata.setdefault("started_at", datetime.now().isoformat())
        metadata.setdefault("webhooks_received", 0)
        self._dirty = False

    # ---------------------------- служебное ---------------------------- #

    def _load(self) -> dict:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки состояния: {e}")
        return {}

    def _start_auto_save(self) -> None:
        async def auto_save():
            while True:
                await asyncio.sleep(60)
                if self._dirty:
                    await self.save()

        task = asyncio.create_task(auto_save())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def save(self) -> bool:
        async with self.lock:
            try:
                self._state["version"] = self.version
                temp_path = self.file_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self._state, f, ensure_ascii=False, indent=2)
                temp_path.replace(self.file_path)
                self._dirty = False
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения состояния: {e}")
                return False

    def touch(self) -> None:
        self._dirty = True

    def set_local_admin(self, record: dict) -> None:
        """Сохраняет учётные данные local-admin (пароль только в виде хэша)."""
        self._state["local_admin"] = dict(record)
        self._dirty = True

    @property
    def raw(self) -> dict:
        return self._state

    @property
    def metadata(self) -> dict:
        return self._state["metadata"]

    @property
    def settings(self) -> dict:
        return self._state["settings"]

    # ---------------------------- каналы ---------------------------- #

    @property
    def notification_channels(self) -> dict:
        return self._state["notification_channels"]

    @property
    def default_chat(self) -> Optional[str]:
        return self._state.get("default_chat")

    @default_chat.setter
    def default_chat(self, value: Optional[str]) -> None:
        self._state["default_chat"] = value
        self._dirty = True

    def get_channel_chat_id(self, name: str) -> Optional[str]:
        channel = self.notification_channels.get(name)
        return channel.get("chat_id") if channel else None

    async def add_channel(
        self,
        name: str,
        chat_id: str,
        created_by: Optional[str] = None,
        chat_title: Optional[str] = None,
    ) -> None:
        async with self.lock:
            self.notification_channels[name] = {
                "chat_id": chat_id,
                "created_at": datetime.now().isoformat(),
                "created_by": created_by,
                "chat_title": chat_title,
            }
            self._dirty = True
        logger.info(f"📢 Канал '{name}' создан (chat_id={chat_id[:8]}…)")

    async def update_channel(
        self,
        name: str,
        chat_id: Optional[str] = None,
        chat_title: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> bool:
        """
        Изменяет канал: chat_id, название чата и/или имя.

        Возвращает False, если исходного канала нет или новое имя занято.
        """
        async with self.lock:
            current = self.notification_channels.get(name)
            if current is None:
                return False

            target_name = (new_name or name).strip().lower()
            if target_name != name and target_name in self.notification_channels:
                return False

            updated = dict(current)
            if chat_id is not None and chat_id.strip():
                updated["chat_id"] = chat_id.strip()
            if chat_title is not None:
                updated["chat_title"] = chat_title.strip() or None
            updated["updated_at"] = datetime.now().isoformat()

            if target_name != name:
                del self.notification_channels[name]

            self.notification_channels[target_name] = updated
            self._dirty = True

        changes = []
        if chat_id is not None:
            changes.append("chat_id")
        if chat_title is not None:
            changes.append("название")
        if target_name != name:
            changes.append(f"имя: {name} → {target_name}")
        logger.info(f"✏️ Канал '{name}' обновлён ({', '.join(changes) or 'без изменений'})")
        return True

    async def remove_channel(self, name: str) -> bool:
        async with self.lock:
            if name in self.notification_channels:
                del self.notification_channels[name]
                self._dirty = True
                logger.info(f"🗑️ Канал '{name}' удален")
                return True
        return False

    # --------------------------- счётчики --------------------------- #

    async def increment(self, key: str, delta: int = 1) -> None:
        self.metadata[key] = self.metadata.get(key, 0) + delta
        self._dirty = True

    # ----------------------- история инцидентов ---------------------- #

    @property
    def error_history(self) -> dict:
        return self._state["error_history"]

    async def remember_error(self, key: str, message_id: str, channel: Optional[str]) -> None:
        async with self.lock:
            self.error_history[key] = {
                "message_id": message_id,
                "channel": channel,
                "opened_at": datetime.now().isoformat(),
                "resolved_at": None,
            }
            self._prune_history()
            self._dirty = True

    async def pop_error(self, key: str) -> Optional[Dict[str, Any]]:
        async with self.lock:
            record = self.error_history.pop(key, None)
            if record is not None:
                self._dirty = True
            return record

    def get_error(self, key: str) -> Optional[Dict[str, Any]]:
        return self.error_history.get(key)

    def _prune_history(self) -> None:
        retention = int(self.settings.get("error_history_retention_days", 7) or 7)
        max_size = 1000
        cutoff = datetime.now() - timedelta(days=retention)
        for key in list(self.error_history.keys()):
            entry = self.error_history[key]
            try:
                opened = datetime.fromisoformat(entry.get("opened_at", ""))
            except Exception:
                opened = None
            if entry.get("resolved_at") or (opened and opened < cutoff):
                self.error_history.pop(key, None)
        while len(self.error_history) > max_size:
            self.error_history.pop(next(iter(self.error_history)))


# ============================================================================
# АДМИНИСТРАТОРЫ
# ============================================================================

class AdminManager:
    """Список администраторов: статический (из config) + динамический (из state)."""

    PUBLIC_COMMANDS = {"/help", "/start", "/info", "/health", "/ping", "/whoami"}

    def __init__(self, admin_ids: List[str], mode: str = "strict", state: Optional[StateManager] = None):
        self.mode = mode or "strict"
        static_ids = {item.strip() for item in admin_ids if item and item.strip()}
        dynamic_ids = set()
        if state is not None:
            dynamic_ids = {str(item) for item in state.raw.get("admins", [])}
        self._static_ids = static_ids
        self._dynamic_ids = dynamic_ids
        self.state = state
        self._cache: Dict[str, bool] = {}

    @property
    def admin_ids(self) -> set:
        return self._static_ids | self._dynamic_ids

    def is_admin(self, user_id: Optional[str]) -> bool:
        if not user_id:
            return False
        if user_id in self._cache:
            return self._cache[user_id]

        if self.mode == "open":
            result = True
        else:
            result = user_id in self._static_ids or user_id in self._dynamic_ids

        self._cache[user_id] = result
        return result

    def can_execute_command(self, user_id: Optional[str], command: str) -> Tuple[bool, str]:
        if not user_id:
            return False, "Неизвестный пользователь"
        if command in self.PUBLIC_COMMANDS:
            return True, "OK"
        if self.is_admin(user_id):
            return True, "OK"
        return False, "Доступ запрещен"

    def add_admin(self, user_id: str) -> bool:
        user_id = user_id.strip()
        if not user_id or user_id in self.admin_ids:
            return False
        self._dynamic_ids.add(user_id)
        self._cache.pop(user_id, None)
        self._persist()
        logger.info(f"🔐 Добавлен администратор: {user_id}")
        return True

    def remove_admin(self, user_id: str) -> bool:
        if user_id in self._static_ids:
            return False
        if user_id not in self._dynamic_ids:
            return False
        self._dynamic_ids.discard(user_id)
        self._cache.pop(user_id, None)
        self._persist()
        logger.info(f"🔐 Удален администратор: {user_id}")
        return True

    def get_admins(self) -> List[str]:
        return sorted(self.admin_ids)

    def is_static(self, user_id: str) -> bool:
        return user_id in self._static_ids

    def _persist(self) -> None:
        if self.state is not None:
            self.state.raw["admins"] = sorted(self._dynamic_ids)
            self.state.touch()


# ============================================================================
# ТОКЕН
# ============================================================================

class TokenManager:
    """OAuth-токен бота: кэш в файле + фоновое обновление."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.token: Optional[str] = None
        self.expires_at: Optional[datetime] = None
        self.token_file = Path(config.get("token_file", "bot_token.json"))
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
        self._load_token()

    def _load_token(self) -> None:
        try:
            if self.token_file.exists():
                with open(self.token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                token = data.get("token")
                expires_at_str = data.get("expires_at")
                expires_at = datetime.fromisoformat(expires_at_str) if expires_at_str else None
                if token and expires_at:
                    remaining = (expires_at - datetime.now()).total_seconds()
                    if remaining > 3600:
                        self.token = token
                        self.expires_at = expires_at
                        logger.info(f"✅ Загружен токен из файла (действителен {remaining / 3600:.1f} ч)")
                        return
        except Exception as e:
            logger.warning(f"⚠️ Ошибка загрузки токена: {e}")

        self.token = None
        self.expires_at = None

    def _save_token(self) -> None:
        try:
            data = {
                "token": self.token,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.token_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения токена: {e}")

    def is_token_valid(self) -> bool:
        if not self.token or not self.expires_at:
            return False
        return (self.expires_at - datetime.now()).total_seconds() > 300

    def remaining_seconds(self) -> Optional[float]:
        if not self.expires_at:
            return None
        return (self.expires_at - datetime.now()).total_seconds()

    async def get_token(self, force_refresh: bool = False) -> Optional[str]:
        async with self._lock:
            if not force_refresh and self.is_token_valid():
                return self.token

            payload = {
                "client_id": self.config["client_id"],
                "grant_type": "password",
                "username": self.config["username"],
                "password": self.config["password"],
            }
            try:
                async with aiohttp.ClientSession() as session:
                    logger.info(f"🔑 Запрос токена для {self.config['username']}…")
                    async with session.post(
                        self.config["token_url"],
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as response:
                        if response.status in (200, 201):
                            data = await response.json()
                            self.token = data.get("access_token")
                            if not self.token:
                                logger.error("❌ Сервер вернул пустой access_token")
                                return None
                            expires_in = int(data.get("expires_in", 2592000))
                            self.expires_at = datetime.now() + timedelta(seconds=expires_in)
                            self._save_token()
                            logger.info(f"✅ Токен получен (действителен {expires_in / 86400:.0f} дн.)")
                            return self.token

                        error_text = await response.text()
                        logger.error(f"❌ Ошибка получения токена: {response.status} — {error_text[:200]}")
                        return None
            except Exception as e:
                logger.error(f"❌ Ошибка запроса токена: {e}")
                return None

    def start_auto_refresh(self, interval: int = 3600) -> None:
        async def monitor_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    if not self.is_token_valid():
                        logger.warning("⚠️ Токен истекает — обновляем…")
                        await self.get_token(force_refresh=True)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка мониторинга токена: {e}")

        self._refresh_task = asyncio.create_task(monitor_loop())
        logger.info("🔄 Запущен мониторинг токена")

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except (asyncio.CancelledError, Exception):
                pass
