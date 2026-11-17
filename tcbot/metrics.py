# -*- coding: utf-8 -*-
"""
История метрик для графиков и календаря активности.

Схема (как в NextCloud Admin):
    * раз в METRICS_INTERVAL секунд снимается «точка» состояния бота;
    * точки агрегируются по часам и хранятся ограниченное время;
    * по дням ведётся счётчик обработанных уведомлений с разбивкой по каналам —
      из него строится календарь недели.

Хранение: отдельный JSON-файл (по умолчанию bot_metrics.json), чтобы не
раздувать bot_state.json. Запись атомарная.

Данные только для чтения в панели: на работу бота они не влияют.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot")

# Сколько часов хранить почасовые точки (7 суток)
HOURLY_TTL_HOURS = 168
# Сколько дней хранить дневную статистику (для календаря)
DAILY_TTL_DAYS = 400


class MetricsStore:
    """
    Копит историю метрик и отдаёт её для графиков.

    Точка (bucket) — один час:

        {"ts": 1700000000, "sent": 12, "queued": 0, "ws": 60, "restarts": 0}

    где sent — отправлено за час, ws — секунд связи в этом часе.
    """

    def __init__(self, file_path: str = "bot_metrics.json", enabled: bool = True):
        self.path = Path(file_path)
        self.enabled = enabled

        self._hourly: Dict[str, Dict[str, Any]] = {}
        self._daily: Dict[str, Dict[str, Any]] = {}
        self._load()

        # Для расчёта прироста между снимками
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._last_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # хранение
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._hourly = data.get("hourly", {}) or {}
            self._daily = data.get("daily", {}) or {}
            logger.info(
                f"📈 История метрик загружена: {len(self._hourly)} часов, "
                f"{len(self._daily)} дней"
            )
        except Exception as exc:
            logger.error(f"❌ Не удалось прочитать {self.path}: {exc}")
            self._hourly, self._daily = {}, {}

    def _save(self) -> None:
        if not self.enabled:
            return
        try:
            payload = {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "hourly": self._hourly,
                "daily": self._daily,
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            logger.error(f"❌ Не удалось сохранить метрики: {exc}")

    # ------------------------------------------------------------------ #
    # накопление
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hour_key(ts: Optional[float] = None) -> str:
        moment = datetime.fromtimestamp(ts or time.time())
        return moment.strftime("%Y-%m-%dT%H")

    @staticmethod
    def _day_key(ts: Optional[float] = None) -> str:
        return datetime.fromtimestamp(ts or time.time()).strftime("%Y-%m-%d")

    def record_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """
        Принимает текущее состояние и добавляет прирост к истории.

        snapshot:
            sent      — всего отправлено (счётчик растёт)
            queued    — текущий размер очереди
            connected — связь есть (bool)
            restarts  — всего перезапусков связи
        """
        if not self.enabled:
            return

        now = time.time()
        sent_total = int(snapshot.get("sent", 0) or 0)
        restarts_total = int(snapshot.get("restarts", 0) or 0)
        queued = int(snapshot.get("queued", 0) or 0)
        connected = bool(snapshot.get("connected"))

        previous = self._last_snapshot
        delta_sent = 0
        delta_restarts = 0
        interval = 0

        if previous is not None:
            delta_sent = max(0, sent_total - int(previous.get("sent", 0) or 0))
            delta_restarts = max(0, restarts_total - int(previous.get("restarts", 0) or 0))
            interval = max(0, min(now - self._last_ts, 3600))

        self._last_snapshot = {
            "sent": sent_total,
            "restarts": restarts_total,
            "queued": queued,
        }
        self._last_ts = now

        hour = self._hour_key(now)
        bucket = self._hourly.setdefault(
            hour, {"ts": int(now), "sent": 0, "queued_max": 0,
                   "ws": 0, "restarts": 0, "snapshots": 0}
        )
        bucket["sent"] += delta_sent
        bucket["queued_max"] = max(bucket.get("queued_max", 0), queued)
        bucket["restarts"] += delta_restarts
        bucket["snapshots"] += 1
        # Покрытие — сколько секунд реально наблюдали в этом часе.
        # Процент связи считаем от покрытия, а не от 3600: иначе при старте
        # в середине часа или коротком прогоне значение занижается.
        if interval > 0:
            bucket["covered"] = bucket.get("covered", 0) + int(interval)
            if connected:
                bucket["ws"] += int(interval)
        bucket["ts"] = int(now)

        # Дневная сводка — для календаря
        day = self._day_key(now)
        daily = self._daily.get(day)
        if daily is None:
            daily = {"date": day, "sent": 0, "restarts": 0, "channels": {}, "webhooks": 0}
            self._daily[day] = daily
        daily["sent"] += delta_sent
        daily["restarts"] += delta_restarts

        self._prune()

    def record_channel_event(self, channel: Optional[str], count: int = 1) -> None:
        """Учитывает уведомление для канала (для календаря и разбивки)."""
        if not self.enabled or not channel:
            return
        day = self._day_key()
        daily = self._daily.get(day)
        if daily is None:
            daily = {"date": day, "sent": 0, "restarts": 0, "channels": {}, "webhooks": 0}
            self._daily[day] = daily
        channels = daily.setdefault("channels", {})
        channels[channel] = int(channels.get(channel, 0)) + count
        daily["webhooks"] = int(daily.get("webhooks", 0)) + count

    def _prune(self) -> None:
        hour_limit = self._hour_key(time.time() - HOURLY_TTL_HOURS * 3600)
        for key in [k for k in self._hourly if k < hour_limit]:
            self._hourly.pop(key, None)

        day_limit = (datetime.now() - timedelta(days=DAILY_TTL_DAYS)).strftime("%Y-%m-%d")
        for key in [k for k in self._daily if k < day_limit]:
            self._daily.pop(key, None)

    def save(self) -> None:
        self._prune()
        self._save()

    # ------------------------------------------------------------------ #
    # выдача для графиков
    # ------------------------------------------------------------------ #

    def history(self, hours: int = 24) -> Dict[str, Any]:
        """Почасовые ряды за период — для линейных графиков."""
        hours = max(1, min(int(hours), HOURLY_TTL_HOURS))
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=hours - 1)

        points: List[Dict[str, Any]] = []
        for index in range(hours):
            moment = start + timedelta(hours=index)
            key = moment.strftime("%Y-%m-%dT%H")
            bucket = self._hourly.get(key)
            if bucket:
                covered = int(bucket.get("covered", 0))
                ws_share = (
                    round(min(1.0, bucket.get("ws", 0) / covered) * 100)
                    if covered > 0 else None
                )
                points.append({
                    "ts": int(moment.timestamp()),
                    "label": moment.strftime("%H:%M"),
                    "sent": bucket.get("sent", 0),
                    "queued": bucket.get("queued_max", 0),
                    "ws": ws_share,
                    "restarts": bucket.get("restarts", 0),
                })
            else:
                points.append({
                    "ts": int(moment.timestamp()),
                    "label": moment.strftime("%H:%M"),
                    "sent": 0,
                    "queued": 0,
                    "ws": None,
                    "restarts": 0,
                })

        return {"hours": hours, "points": points}

    def days(self, limit: int = 365) -> Dict[str, Any]:
        """Дневная статистика — для календаря активности."""
        limit = max(1, min(int(limit), DAILY_TTL_DAYS))
        keys = sorted(self._daily.keys())[-limit:]

        result: List[Dict[str, Any]] = []
        for key in keys:
            day = self._daily[key]
            channels = day.get("channels", {}) or {}
            by_channel = [
                {"name": name, "count": int(value)}
                for name, value in sorted(channels.items(), key=lambda kv: -int(kv[1]))
            ]
            result.append({
                "date": key,
                "count": int(day.get("sent", 0)),
                "webhooks": int(day.get("webhooks", 0)),
                "restarts": int(day.get("restarts", 0)),
                "channels": len(channels),
                "by_channel": by_channel,
            })
        return {"days": result}

    def summary(self) -> Dict[str, Any]:
        """Короткая сводка для панели."""
        today = self._day_key()
        day = self._daily.get(today, {})
        last_hours = self.history(24)["points"]
        return {
            "today_sent": int(day.get("sent", 0)),
            "today_webhooks": int(day.get("webhooks", 0)),
            "today_channels": len(day.get("channels", {}) or {}),
            "last24_sent": sum(p["sent"] for p in last_hours),
            "points": len(self._hourly),
            "days": len(self._daily),
        }
