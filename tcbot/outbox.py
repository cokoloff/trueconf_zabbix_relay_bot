# -*- coding: utf-8 -*-
"""
Durable-очередь недоставленных уведомлений.

Зачем: это relay. Если TrueConf недоступен (плановые работы, авария), Zabbix
повторит вебхук лишь несколько раз за десятки секунд и сдастся — уведомления
за час простоя были бы потеряны безвозвратно.

Outbox складывает недоставленные сообщения на диск и выгружает их после
восстановления связи. Очередь переживает перезапуск процесса.

Свойства:
    * хранение в JSON-файле с атомарной записью (tmp + replace);
    * ограничение размера и срока жизни (TTL), чтобы не расти бесконечно;
    * дедупликация одинаковых уведомлений в коротком окне;
    * необязательное «схлопывание» по incident_key: если по одному триггеру
      накопилось несколько обновлений, при выгрузке уходит только последнее.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot")


class OutboxItem:
    __slots__ = ("id", "chat_id", "channel", "text", "incident_key",
                 "created_at", "attempts", "status", "severity")

    def __init__(
        self,
        item_id: str,
        chat_id: str,
        channel: Optional[str],
        text: str,
        incident_key: Optional[str],
        created_at: float,
        attempts: int = 0,
        status: Optional[str] = None,
        severity: Optional[str] = None,
    ):
        self.id = item_id
        self.chat_id = chat_id
        self.channel = channel
        self.text = text
        self.incident_key = incident_key
        self.created_at = created_at
        self.attempts = attempts
        self.status = status
        self.severity = severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "channel": self.channel,
            "text": self.text,
            "incident_key": self.incident_key,
            "created_at": self.created_at,
            "attempts": self.attempts,
            "status": self.status,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutboxItem":
        return cls(
            item_id=data["id"],
            chat_id=data["chat_id"],
            channel=data.get("channel"),
            text=data["text"],
            incident_key=data.get("incident_key"),
            created_at=float(data.get("created_at", time.time())),
            attempts=int(data.get("attempts", 0)),
            status=data.get("status"),
            severity=data.get("severity"),
        )

    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600


class Outbox:
    """Очередь недоставленных сообщений с сохранением на диск."""

    def __init__(
        self,
        file_path: str = "bot_outbox.json",
        max_size: int = 5000,
        ttl_hours: float = 48.0,
        dedup_window: float = 120.0,
        enabled: bool = True,
    ):
        self.path = Path(file_path)
        self.max_size = max(1, int(max_size))
        self.ttl_hours = max(0.1, float(ttl_hours))
        self.dedup_window = max(0.0, float(dedup_window))
        self.enabled = bool(enabled)

        self._items: List[OutboxItem] = []
        self._lock = asyncio.Lock()
        self._dedup: Dict[str, float] = {}
        self.dropped = 0
        self.enqueued = 0
        self.sent = 0
        self.duplicates = 0

        self._load()

    # ------------------------------------------------------------------ #
    # персистентность
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            raw_items = data.get("items", []) if isinstance(data, dict) else data
            self._items = [OutboxItem.from_dict(item) for item in raw_items]
            logger.info(f"📥 Очередь недоставленных загружена: {len(self._items)} сообщений")
        except Exception as exc:
            logger.error(f"❌ Не удалось прочитать очередь {self.path}: {exc}")
            self._items = []
        self._prune_expired()

    def _save_locked(self) -> None:
        try:
            payload = {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "items": [item.to_dict() for item in self._items],
            }
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=1)
            tmp.replace(self.path)
        except Exception as exc:
            logger.error(f"❌ Не удалось сохранить очередь: {exc}")

    # ------------------------------------------------------------------ #
    # операции
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> List[OutboxItem]:
        return list(self._items)

    def _prune_expired(self) -> int:
        limit = time.time() - self.ttl_hours * 3600
        before = len(self._items)
        self._items = [item for item in self._items if item.created_at >= limit]
        removed = before - len(self._items)
        if removed:
            logger.info(f"🧹 Из очереди удалено {removed} просроченных сообщений")
        return removed

    @staticmethod
    def make_id(chat_id: str, text: str, incident_key: Optional[str] = None) -> str:
        digest = hashlib.sha1(f"{chat_id}|{incident_key or ''}|{text}".encode("utf-8", "ignore"))
        return digest.hexdigest()[:20]

    async def put(
        self,
        chat_id: str,
        text: str,
        channel: Optional[str] = None,
        incident_key: Optional[str] = None,
        status: Optional[str] = None,
        collapse: bool = False,
        severity: Optional[str] = None,
    ) -> Optional[OutboxItem]:
        """
        Ставит сообщение в очередь. Возвращает элемент или None, если не принято
        (выключено, дубликат или очередь переполнена).
        """
        if not self.enabled:
            return None

        item_id = self.make_id(chat_id, text, incident_key)
        now = time.time()

        async with self._lock:
            if self.dedup_window:
                seen_at = self._dedup.get(item_id)
                if seen_at is not None and now - seen_at <= self.dedup_window:
                    logger.debug(f"↩️ Дубликат не поставлен в очередь: {item_id}")
                    # Возвращаем уже стоящий в очереди элемент: для отправителя
                    # уведомление принято, повторно класть его не нужно.
                    existing = next(
                        (candidate for candidate in self._items if candidate.id == item_id),
                        None,
                    )
                    if existing is not None:
                        self.duplicates += 1
                        return existing
                    return None
                self._dedup[item_id] = now
                for key in [k for k, ts in self._dedup.items() if now - ts > self.dedup_window]:
                    self._dedup.pop(key, None)

            if collapse and incident_key:
                self._items = [
                    existing
                    for existing in self._items
                    if not (existing.incident_key == incident_key and existing.chat_id == chat_id)
                ]

            if len(self._items) >= self.max_size:
                self._items.pop(0)
                self.dropped += 1
                logger.warning(
                    f"⚠️ Очередь переполнена ({self.max_size}) — удалено старейшее сообщение. "
                    f"Всего потеряно: {self.dropped}"
                )

            item = OutboxItem(
                item_id=item_id,
                chat_id=chat_id,
                channel=channel,
                text=text,
                incident_key=incident_key,
                created_at=now,
                status=status,
                severity=severity,
            )
            self._items.append(item)
            self.enqueued += 1
            self._save_locked()

        logger.info(
            f"📦 Уведомление сохранено в очередь ({len(self._items)} в ожидании)"
            + (f", простой {item.age_hours():.1f} ч" if item.age_hours() > 0.05 else "")
        )
        return item

    async def pop(self) -> Optional[OutboxItem]:
        async with self._lock:
            self._prune_expired()
            if not self._items:
                return None
            item = self._items.pop(0)
            self._save_locked()
            return item

    async def peek_batch(self, limit: int = 1) -> List[OutboxItem]:
        async with self._lock:
            self._prune_expired()
            return list(self._items[:limit])

    async def mark_sent(self, item: OutboxItem) -> None:
        async with self._lock:
            self.sent += 1
            self._save_locked()

    async def requeue_front(self, item: OutboxItem) -> None:
        """Возвращает сообщение в начало очереди (не удалось отправить)."""
        async with self._lock:
            item.attempts += 1
            self._items.insert(0, item)
            self._save_locked()

    async def clear(self) -> int:
        async with self._lock:
            removed = len(self._items)
            self._items = []
            self._save_locked()
        logger.info(f"🧹 Очередь очищена ({removed} сообщений)")
        return removed

    def stats(self) -> Dict[str, Any]:
        oldest = min((item.created_at for item in self._items), default=None)
        return {
            "enabled": self.enabled,
            "size": len(self._items),
            "max_size": self.max_size,
            "ttl_hours": self.ttl_hours,
            "oldest_age_seconds": (time.time() - oldest) if oldest else None,
            "enqueued_total": self.enqueued,
            "sent_total": self.sent,
            "dropped_total": self.dropped,
            "duplicates_total": self.duplicates,
        }

    def preview(self, limit: int = 20) -> List[Dict[str, Any]]:
        now = time.time()
        result = []
        for item in self._items[:limit]:
            result.append({
                "channel": item.channel,
                "chat_id": item.chat_id,
                "status": item.status,
                "age_seconds": now - item.created_at,
                "attempts": item.attempts,
                "text": item.text[:200],
            })
        return result
