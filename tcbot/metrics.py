# -*- coding: utf-8 -*-
"""
История метрик для графиков и календаря в панели.

Что копится:

    по часам   — отправлено, отказы, задержка доставки, очередь, связь,
                 перезапуски, разбивка по каналам и по статусам (PROBLEM/RESOLVED)
    по дням    — то же для календаря, с разбивкой по каналам

Схема (как в NextCloud Admin): фоновый сборщик раз в METRICS_INTERVAL секунд
снимает счётчики состояния, а события доставки учитываются по факту —
при каждом вебхуке. Хранится отдельный JSON-файл, чтобы не раздувать
bot_state.json. Запись атомарная.

Данные только для чтения в панели: на работу бота они не влияют.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("bot")

# РњРµС‚РєРё РІСЂРµРјРµРЅРё РІ РїР°РЅРµР»Рё РїРѕРєР°Р·С‹РІР°РµРј РїРѕ РњРѕСЃРєРІРµ (UTC+3), РєР°Рє РїСЂРёРЅСЏС‚Рѕ РІ
# СЌРєСЃРїР»СѓР°С‚Р°С†РёРё. РЎРµСЂРІРµСЂ РјРѕР¶РµС‚ Р¶РёС‚СЊ РІ UTC вЂ” С‚РѕРіРґР° Р±РµР· СЃРјРµС‰РµРЅРёСЏ РіСЂР°С„РёРєРё
# В«СЃСЉРµР·Р¶Р°СЋС‚В» РЅР° С‚СЂРё С‡Р°СЃР° РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅРѕ СЂРµР°Р»СЊРЅРѕРіРѕ РІСЂРµРјРµРЅРё СЃРѕР±С‹С‚РёР№.
MOSCOW_TZ = timezone(timedelta(hours=3))

# Сколько часов хранить почасовые точки (7 суток)
HOURLY_TTL_HOURS = 168
# Сколько дней хранить дневную статистику (для календаря)
DAILY_TTL_DAYS = 400

# Предел числа каналов в разбивке (защита от распухания файла)
MAX_CHANNELS = 60

# Сколько последних событий хранить для точечной шкалы времени.
# Буфер нужен, чтобы знать точное время каждой отправки, а не только час.
MAX_EVENTS = 2000


def _new_bucket(ts: int) -> Dict[str, Any]:
    return {
        "ts": ts,
        "sent": 0,          # успешно доставлено
        "failed": 0,        # не доставлено
        "latency_sum": 0.0, # суммарная задержка доставки, сек
        "latency_n": 0,     # число замеров
        "queued_max": 0,    # максимум в очереди
        "ws": 0,            # секунд со связью
        "covered": 0,       # секунд наблюдения
        "restarts": 0,
        "channels": {},     # имя канала -> число отправок
        "statuses": {},     # PROBLEM/RESOLVED/... -> число
        "channel_stats": {},  # имя канала -> подробная статистика
        "severities": {},   # строгость Zabbix -> число
        "channel_status": {},  # канал -> {problem, resolved}
    }


class MetricsStore:
    """Копит историю метрик и отдаёт её для графиков."""

    def __init__(self, file_path: str = "bot_metrics.json", enabled: bool = True):
        self.path = Path(file_path)
        self.enabled = enabled

        self._hourly: Dict[str, Dict[str, Any]] = {}
        self._daily: Dict[str, Dict[str, Any]] = {}

        # Поля должны существовать ДО _load(), иначе загрузка пишет в них,
        # а следующая строка их обнуляет — события молча теряются.
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._last_ts: float = 0.0
        self._dirty = False
        # Точные события доставки: (ts, канал, статус, строгость)
        self._events: Deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)

        self._load()

    # ------------------------------------------------------------------ #
    # хранение
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_bucket(bucket: Dict[str, Any], ts: int = 0) -> Dict[str, Any]:
        """
        Дополняет бакет недостающими полями.

        Файл метрик мог быть записан более ранней версией бота, где часть
        полей отсутствовала. Без нормализации обращение к ним падало с
        KeyError — а это исключение в обработчике вебхука приводило к ответу
        500, Zabbix повторял запрос, и одно уведомление уходило в чат
        несколько раз.
        """
        if not isinstance(bucket, dict):
            bucket = _new_bucket(ts)
        defaults = _new_bucket(ts or int(bucket.get("ts", 0) or 0))
        for key, value in defaults.items():
            if key not in bucket or bucket[key] is None:
                bucket[key] = value
        if not isinstance(bucket.get("channels"), dict):
            bucket["channels"] = {}
        if not isinstance(bucket.get("statuses"), dict):
            bucket["statuses"] = {}
        if not isinstance(bucket.get("channel_stats"), dict):
            bucket["channel_stats"] = {}
        if not isinstance(bucket.get("channel_status"), dict):
            bucket["channel_status"] = {}

        # Восстанавливаем разбивку по статусам из подробной статистики:
        # файл прошлой версии хранил channel_stats, но не channel_status,
        # из-за чего столбики на графике оставались одноцветными.
        if not bucket["channel_status"] and bucket["channel_stats"]:
            for name, stat in bucket["channel_stats"].items():
                if not isinstance(stat, dict):
                    continue
                problems = 0
                resolved = 0
                for status_name, count in (stat.get("statuses") or {}).items():
                    upper = str(status_name).upper()
                    if upper in ("RESOLVED", "OK", "RECOVERY", "RESOLVE"):
                        resolved += int(count)
                    elif upper in ("PROBLEM", "FIRING", "ALERT"):
                        problems += int(count)
                sent = int(stat.get("sent", 0))
                # Если статусов меньше, чем отправок, остаток считаем
                # проблемами: в старых записях статус не передавался вовсе.
                missing = sent - problems - resolved
                if missing > 0:
                    problems += missing
                if problems or resolved:
                    bucket["channel_status"][name] = {
                        "problem": problems,
                        "resolved": resolved,
                    }

        # Восстанавливаем разбивку из подробной статистики: файл прошлой
        # версии мог хранить channel_stats, но не channels/statuses.
        if not bucket["channels"] and bucket["channel_stats"]:
            for name, stat in bucket["channel_stats"].items():
                if isinstance(stat, dict):
                    total = int(stat.get("sent", 0)) + int(stat.get("failed", 0))
                    if total:
                        bucket["channels"][name] = total
        if not bucket["statuses"]:
            merged: Dict[str, int] = {}
            for stat in bucket["channel_stats"].values():
                if isinstance(stat, dict) and isinstance(stat.get("statuses"), dict):
                    for status_name, count in stat["statuses"].items():
                        merged[status_name] = merged.get(status_name, 0) + int(count)
            bucket["statuses"] = merged
        return bucket

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._hourly = data.get("hourly", {}) or {}
            self._daily = data.get("daily", {}) or {}
            # Файл мог быть создан прошлой версией — приводим к текущей схеме
            self._hourly = {
                key: self._normalize_bucket(value) for key, value in self._hourly.items()
            }
            self._daily = {
                key: self._normalize_bucket(value) for key, value in self._daily.items()
            }
            events = data.get("events") or []
            if isinstance(events, list):
                cutoff = time.time() - HOURLY_TTL_HOURS * 3600
                self._events = deque(
                    (
                        event for event in events
                        if isinstance(event, dict)
                        and float(event.get("ts", 0)) >= cutoff
                    ),
                    maxlen=MAX_EVENTS,
                )
            logger.info(
                f"📈 История метрик загружена: {len(self._hourly)} часов, "
                f"{len(self._daily)} дней, {len(self._events)} событий"
            )
        except Exception as exc:
            logger.error(f"❌ Не удалось прочитать {self.path}: {exc}")
            self._hourly, self._daily = {}, {}

    def _save(self) -> None:
        if not self.enabled:
            return
        try:
            payload = {
                "updated_at": datetime.now(MOSCOW_TZ).isoformat(timespec="seconds"),
                "hourly": self._hourly,
                "daily": self._daily,
                # Точные времена событий: без них шкала времени пуста после
                # перезапуска, остаются только почасовые агрегаты.
                "events": list(self._events),
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty = False
        except Exception as exc:
            logger.error(f"❌ Не удалось сохранить метрики: {exc}")

    # ------------------------------------------------------------------ #
    # ключи
    # ------------------------------------------------------------------ #

    @staticmethod
    def _local(ts: Optional[float] = None) -> datetime:
        """Р’СЂРµРјСЏ СЃРѕР±С‹С‚РёСЏ РІ РјРѕСЃРєРѕРІСЃРєРѕР№ Р·РѕРЅРµ."""
        return datetime.fromtimestamp(ts or time.time(), MOSCOW_TZ)

    @staticmethod
    def _hour_key(ts: Optional[float] = None) -> str:
        return MetricsStore._local(ts).strftime("%Y-%m-%dT%H")

    @staticmethod
    def _day_key(ts: Optional[float] = None) -> str:
        return MetricsStore._local(ts).strftime("%Y-%m-%d")

    def _hour_bucket(self, ts: Optional[float] = None) -> Dict[str, Any]:
        now = ts or time.time()
        key = self._hour_key(now)
        bucket = self._hourly.get(key)
        if bucket is None:
            bucket = _new_bucket(int(now))
            self._hourly[key] = bucket
        else:
            bucket = self._normalize_bucket(bucket, int(now))
        return bucket

    def _day_bucket(self, ts: Optional[float] = None) -> Dict[str, Any]:
        now = ts or time.time()
        key = self._day_key(now)
        bucket = self._daily.get(key)
        if bucket is None:
            bucket = _new_bucket(int(now))
            bucket["date"] = key
            self._daily[key] = bucket
        else:
            bucket = self._normalize_bucket(bucket, int(now))
            bucket["date"] = key
        return bucket

    @staticmethod
    def _bump(mapping: Dict[str, int], name: str, count: int = 1) -> None:
        """Увеличивает счётчик, не давая словарю расти бесконечно."""
        if len(mapping) >= MAX_CHANNELS and name not in mapping:
            return
        mapping[name] = int(mapping.get(name, 0)) + count

    # ------------------------------------------------------------------ #
    # накопление — события доставки
    # ------------------------------------------------------------------ #

    def record_delivery(
        self,
        channel: Optional[str],
        status: Optional[str],
        latency: float,
        success: bool = True,
        severity: Optional[str] = None,
    ) -> None:
        """
        Учитывает одну попытку доставки уведомления.

        Вызывается из обработчика вебхука — это основной источник данных
        для графиков «по каналам», «по статусам» и «задержка доставки».
        """
        if not self.enabled:
            return

        now = time.time()
        hour = self._hour_bucket(now)
        day = self._day_bucket(now)

        for bucket in (hour, day):
            if success:
                bucket["sent"] += 1
                if latency and latency > 0:
                    bucket["latency_sum"] += float(latency)
                    bucket["latency_n"] += 1
            else:
                bucket["failed"] += 1

        name = channel or "default"
        self._bump(hour["channels"], name)
        self._bump(day["channels"], name)

        # Разбивка по каналам с разделением на проблемы и решения:
        # нужна для двухцветной столбчатой диаграммы.
        is_resolved_status = str(status or "").upper() in (
            "RESOLVED", "OK", "RECOVERY", "RESOLVE"
        )
        bucket_kind = "resolved" if is_resolved_status else "problem"
        for bucket in (hour, day):
            per_channel = bucket.setdefault("channel_status", {})
            if len(per_channel) < MAX_CHANNELS or name in per_channel:
                entry = per_channel.setdefault(
                    name, {"problem": 0, "resolved": 0}
                )
                entry[bucket_kind] = int(entry.get(bucket_kind, 0)) + 1

        # Подробности по каналу: успехи, отказы, задержка, разбивка по статусам.
        # Такой срез позволяет показать статистику каждого канала отдельно.
        for bucket in (hour, day):
            detail = bucket.setdefault("channel_stats", {})
            if len(detail) < MAX_CHANNELS or name in detail:
                stat = detail.setdefault(name, {
                    "sent": 0, "failed": 0,
                    "latency_sum": 0.0, "latency_n": 0, "latency_max": 0.0,
                    "statuses": {}, "last_at": 0,
                })
                if success:
                    stat["sent"] += 1
                    if latency and latency > 0:
                        stat["latency_sum"] += float(latency)
                        stat["latency_n"] += 1
                        stat["latency_max"] = max(stat["latency_max"], float(latency))
                else:
                    stat["failed"] += 1
                if status:
                    self._bump(stat["statuses"], status.upper())
                stat["last_at"] = int(now)

        self._events.append({
            "ts": round(now, 1),
            "channel": name,
            "status": (status or "").upper() or None,
            "severity": severity or None,
            "ok": bool(success),
        })

        if status:
            self._bump(hour["statuses"], status.upper())
            self._bump(day["statuses"], status.upper())

        # Строгость Zabbix (Disaster/High/Average/Warning/Information)
        if severity:
            self._bump(hour.setdefault("severities", {}), severity)
            self._bump(day.setdefault("severities", {}), severity)

        self._dirty = True

    # ------------------------------------------------------------------ #
    # накопление — снимки состояния
    # ------------------------------------------------------------------ #

    def record_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """
        Принимает текущее состояние и добавляет прирост к истории.

        snapshot:
            queued    — текущий размер очереди
            connected — связь есть (bool)
            restarts  — всего перезапусков связи
        """
        if not self.enabled:
            return

        now = time.time()
        queued = int(snapshot.get("queued", 0) or 0)
        restarts_total = int(snapshot.get("restarts", 0) or 0)
        connected = bool(snapshot.get("connected"))

        previous = self._last_snapshot
        delta_restarts = 0
        interval = 0.0

        if previous is not None:
            delta_restarts = max(0, restarts_total - int(previous.get("restarts", 0) or 0))
            interval = max(0.0, min(now - self._last_ts, 3600))

        self._last_snapshot = {"restarts": restarts_total, "queued": queued}
        self._last_ts = now

        hour = self._hour_bucket(now)
        hour["queued_max"] = max(hour.get("queued_max", 0), queued)
        hour["restarts"] += delta_restarts
        if interval > 0:
            hour["covered"] = hour.get("covered", 0) + int(interval)
            if connected:
                hour["ws"] += int(interval)

        day = self._day_bucket(now)
        day["queued_max"] = max(day.get("queued_max", 0), queued)
        day["restarts"] += delta_restarts

        self._prune()
        self._dirty = True

    def record_channel_event(self, channel: Optional[str], count: int = 1) -> None:
        """Совместимость: учитывает событие канала без статуса."""
        self.record_delivery(channel, None, 0.0, success=True)

    def _prune(self) -> None:
        hour_limit = self._hour_key(time.time() - HOURLY_TTL_HOURS * 3600)
        for key in [k for k in self._hourly if k < hour_limit]:
            self._hourly.pop(key, None)

        day_limit = (datetime.now(MOSCOW_TZ) - timedelta(days=DAILY_TTL_DAYS)).strftime("%Y-%m-%d")
        for key in [k for k in self._daily if k < day_limit]:
            self._daily.pop(key, None)

    def save(self) -> None:
        self._prune()
        self._save()

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------ #
    # выдача для графиков
    # ------------------------------------------------------------------ #

    def history(self, hours: int = 24) -> Dict[str, Any]:
        """Почасовые ряды за период — для линейных графиков."""
        hours = max(1, min(int(hours), HOURLY_TTL_HOURS))
        now = datetime.now(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=hours - 1)

        points: List[Dict[str, Any]] = []
        for index in range(hours):
            moment = start + timedelta(hours=index)
            key = moment.strftime("%Y-%m-%dT%H")
            bucket = self._hourly.get(key)

            label = moment.strftime("%H:%M")
            ts = int(moment.timestamp())

            if not bucket:
                points.append({
                    "ts": ts, "label": label, "sent": 0, "failed": 0,
                    "queued": 0, "ws": None, "restarts": 0,
                    "latency": None, "channels": {}, "statuses": {},
                    "severities": {},
                })
                continue

            covered = int(bucket.get("covered", 0))
            ws_share = (
                round(min(1.0, bucket.get("ws", 0) / covered) * 100)
                if covered > 0 else None
            )
            latency_n = int(bucket.get("latency_n", 0))
            latency = (
                round(bucket.get("latency_sum", 0.0) / latency_n, 3)
                if latency_n else None
            )

            points.append({
                "ts": ts,
                "label": label,
                "sent": bucket.get("sent", 0),
                "failed": bucket.get("failed", 0),
                "queued": bucket.get("queued_max", 0),
                "ws": ws_share,
                "restarts": bucket.get("restarts", 0),
                "latency": latency,
                "channels": dict(bucket.get("channels", {})),
                "channel_status": dict(bucket.get("channel_status", {})),
                "statuses": dict(bucket.get("statuses", {})),
                "severities": dict(bucket.get("severities", {})),
            })

        return {
            "hours": hours,
            "points": points,
            "channels": self.channel_totals(points),
            "statuses": self._status_totals(points),
            "severities": self._severity_totals(points),
        }

    @staticmethod
    def channel_totals(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Суммирует отправки по каналам за период.

        Для каждого канала отдаём и общее число, и разбивку на проблемы
        и решения — диаграмма раскрашивает столбики по статусу.
        """
        totals: Dict[str, Dict[str, int]] = {}
        for point in points:
            for name, count in (point.get("channels") or {}).items():
                entry = totals.setdefault(name, {"count": 0, "problem": 0, "resolved": 0})
                entry["count"] += int(count)

            for name, split in (point.get("channel_status") or {}).items():
                if not isinstance(split, dict):
                    continue
                entry = totals.setdefault(name, {"count": 0, "problem": 0, "resolved": 0})
                entry["problem"] += int(split.get("problem", 0) or 0)
                entry["resolved"] += int(split.get("resolved", 0) or 0)

        ordered = sorted(totals.items(), key=lambda kv: -kv[1]["count"])
        return [
            {
                "name": name,
                "count": data["count"],
                "problem": data["problem"],
                "resolved": data["resolved"],
            }
            for name, data in ordered
        ]

    def status_totals(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Разбивка по статусам за период."""
        points = self.history(hours)["points"]
        return self._status_totals(points)

    @staticmethod
    def _status_totals(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        totals: Dict[str, int] = {}
        for point in points:
            for name, count in (point.get("statuses") or {}).items():
                totals[name] = totals.get(name, 0) + int(count)
        ordered = sorted(totals.items(), key=lambda kv: -kv[1])
        return [{"name": name, "count": count} for name, count in ordered]

    def channel_report(self, hours: int = 24, limit: int = 100) -> Dict[str, Any]:
        """
        Подробная статистика по каждому каналу за период.

        Возвращает по каждому каналу: отправлено, отказы, процент успеха,
        средняя и максимальная задержка, разбивка по статусам, время последней
        отправки и распределение по часам (для мини-графика).
        """
        hours = max(1, min(int(hours), HOURLY_TTL_HOURS))
        now = datetime.now(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=hours - 1)

        # Аккумуляторы по каналам
        agg: Dict[str, Dict[str, Any]] = {}

        for index in range(hours):
            moment = start + timedelta(hours=index)
            key = moment.strftime("%Y-%m-%dT%H")
            bucket = self._hourly.get(key)
            if not bucket:
                continue

            for name, stat in (bucket.get("channel_stats") or {}).items():
                entry = agg.setdefault(name, {
                    "name": name,
                    "sent": 0,
                    "failed": 0,
                    "latency_sum": 0.0,
                    "latency_n": 0,
                    "latency_max": 0.0,
                    "statuses": {},
                    "last_at": 0,
                    "hourly": [0] * hours,
                    # Почасовая разбивка по статусам — для мини-графика,
                    # где видно соотношение проблем и решений.
                    "hourly_problem": [0] * hours,
                    "hourly_resolved": [0] * hours,
                })
                entry["sent"] += int(stat.get("sent", 0))
                entry["failed"] += int(stat.get("failed", 0))
                entry["latency_sum"] += float(stat.get("latency_sum", 0.0))
                entry["latency_n"] += int(stat.get("latency_n", 0))
                max_latency = stat.get("latency_max")
                if max_latency:
                    entry["latency_max"] = max(entry["latency_max"], float(max_latency))
                entry["last_at"] = max(entry["last_at"], int(stat.get("last_at", 0)))
                entry["hourly"][index] = int(stat.get("sent", 0)) + int(stat.get("failed", 0))

                stat_statuses = stat.get("statuses") or {}
                for status_name, count in stat_statuses.items():
                    entry["statuses"][status_name] = (
                        entry["statuses"].get(status_name, 0) + int(count)
                    )

                # Раскладываем по двум корзинам: проблемы и решения
                problems = 0
                resolved = 0
                for status_name, count in stat_statuses.items():
                    upper = str(status_name).upper()
                    if upper in ("RESOLVED", "OK", "RECOVERY", "RESOLVE"):
                        resolved += int(count)
                    elif upper in ("PROBLEM", "FIRING", "ALERT"):
                        problems += int(count)
                entry["hourly_problem"][index] += problems
                entry["hourly_resolved"][index] += resolved

        items: List[Dict[str, Any]] = []
        for name, entry in agg.items():
            total = entry["sent"] + entry["failed"]
            avg_latency = (
                round(entry["latency_sum"] / entry["latency_n"], 3)
                if entry["latency_n"] else None
            )
            items.append({
                "name": name,
                "sent": entry["sent"],
                "failed": entry["failed"],
                "total": total,
                "success_rate": round(entry["sent"] / total * 100, 1) if total else None,
                "avg_latency": avg_latency,
                "max_latency": round(entry["latency_max"], 3) if entry["latency_max"] else None,
                "statuses": [
                    {"name": status_name, "count": count}
                    for status_name, count in sorted(
                        entry["statuses"].items(), key=lambda kv: -kv[1]
                    )
                ],
                "last_at": entry["last_at"] or None,
                "hourly": entry["hourly"],
                "hourly_problem": entry["hourly_problem"],
                "hourly_resolved": entry["hourly_resolved"],
                "problems": sum(entry["hourly_problem"]),
                "resolved": sum(entry["hourly_resolved"]),
            })

        items.sort(key=lambda item: -item["total"])
        items = items[:limit]

        # Итоги по всем каналам
        total_sent = sum(item["sent"] for item in items)
        total_failed = sum(item["failed"] for item in items)
        latencies = [item["avg_latency"] for item in items if item["avg_latency"]]

        return {
            "hours": hours,
            "channels": items,
            "totals": {
                "channels": len(items),
                "sent": total_sent,
                "failed": total_failed,
                "success_rate": (
                    round(total_sent / (total_sent + total_failed) * 100, 1)
                    if (total_sent + total_failed) else None
                ),
                "avg_latency": round(sum(latencies) / len(latencies), 3) if latencies else None,
            },
        }

    @staticmethod
    def _severity_totals(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Суммирует строгость уведомлений за период."""
        totals: Dict[str, int] = {}
        for point in points:
            for name, count in (point.get("severities") or {}).items():
                totals[name] = totals.get(name, 0) + int(count)
        # Тяжёлые сверху: так нагляднее
        order = ["Disaster", "High", "Average", "Warning", "Information", "Not classified"]
        return [
            {"name": name, "count": totals[name]}
            for name in sorted(
                totals, key=lambda n: (order.index(n) if n in order else len(order), -totals[n])
            )
        ]

    def severity_totals(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Разбивка по строгости за период."""
        return self._severity_totals(self.history(hours)["points"])

    def timeline(
        self, hours: int = 24, bucket_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        События на шкале времени — для точечного графика.

        Возвращает группы точек: за каждый интервал собраны каналы и число
        отправок. Размер точки зависит от числа сообщений, а при наведении
        видно, что именно и когда ушло.

        bucket_minutes:
            None — подобрать автоматически под период (около 200 точек);
            число — заданный шаг, но с защитой от слишком мелкого шага,
            иначе точек будут десятки тысяч и график не отрисуется.
        """
        hours = max(1, min(int(hours), HOURLY_TTL_HOURS))

        if bucket_minutes is None or int(bucket_minutes) <= 0:
            # Автоподбор: держим около 200 точек на любом периоде
            target_points = 200
            raw = max(1, int(round(hours * 60 / target_points)))
            # Округляем до удобных значений
            for step in (1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440):
                if raw <= step:
                    bucket_minutes = step
                    break
            else:
                bucket_minutes = 1440
        else:
            bucket_minutes = int(bucket_minutes)
            # Защита от лавины точек: не больше ~3000 на график
            minimum = max(1, int(hours * 60 / 3000))
            bucket_minutes = max(bucket_minutes, minimum)

        now = time.time()
        since = now - hours * 3600
        bucket_seconds = max(60, bucket_minutes * 60)

        groups: Dict[int, Dict[str, Any]] = {}

        # Точные события (появились в этой версии)
        for event in self._events:
            ts = float(event.get("ts", 0))
            if ts < since:
                continue
            slot = int(ts // bucket_seconds) * bucket_seconds
            group = groups.setdefault(slot, {
                "ts": slot,
                "total": 0,
                "channels": {},
                "statuses": {},
                "severities": {},
                "failed": 0,
                "problems": 0,
                "resolved": 0,
                "by_channel": {},
            })
            group["total"] += 1
            name = event.get("channel") or "default"
            group["channels"][name] = group["channels"].get(name, 0) + 1

            # Разделяем проблемы и решения: на графике они красятся по-разному
            status = (event.get("status") or "").upper()
            is_resolved = status in ("RESOLVED", "OK", "RECOVERY", "RESOLVE")
            if is_resolved:
                group["resolved"] += 1
            else:
                group["problems"] += 1

            slot_info = group["by_channel"].setdefault(
                name, {"problem": 0, "resolved": 0}
            )
            if is_resolved:
                slot_info["resolved"] += 1
            else:
                slot_info["problem"] += 1
            if event.get("status"):
                st = event["status"]
                group["statuses"][st] = group["statuses"].get(st, 0) + 1
            if event.get("severity"):
                sv = event["severity"]
                group["severities"][sv] = group["severities"].get(sv, 0) + 1
            if not event.get("ok", True):
                group["failed"] += 1

        # Дополняем почасовыми данными — для периодов до появления событий:
        # точное время неизвестно, ставим точку на начало часа.
        if bucket_minutes >= 60:
            start_hour = datetime.fromtimestamp(since, MOSCOW_TZ).replace(
                minute=0, second=0, microsecond=0
            )
            moment = start_hour
            while moment.timestamp() <= now:
                key = moment.strftime("%Y-%m-%dT%H")
                bucket = self._hourly.get(key)
                if bucket:
                    slot = int(moment.timestamp() // bucket_seconds) * bucket_seconds
                    if slot not in groups:
                        channels = dict(bucket.get("channels", {}) or {})
                        total = sum(int(v) for v in channels.values())
                        if not total and bucket.get("sent"):
                            total = int(bucket.get("sent", 0))
                        if total:
                            statuses = dict(bucket.get("statuses", {}) or {})
                            problems = int(statuses.get("PROBLEM", 0))
                            resolved = int(
                                statuses.get("RESOLVED", 0)
                                + statuses.get("OK", 0)
                                + statuses.get("RECOVERY", 0)
                            )
                            groups[slot] = {
                                "ts": slot,
                                "total": total,
                                "channels": channels,
                                "statuses": statuses,
                                "severities": dict(bucket.get("severities", {}) or {}),
                                "failed": int(bucket.get("failed", 0)),
                                "problems": problems,
                                "resolved": resolved,
                                "by_channel": {},
                                "approximate": True,
                            }
                moment += timedelta(hours=1)

        points = []
        for slot in sorted(groups):
            group = groups[slot]
            channel_list = sorted(
                ({"name": k, "count": int(v)} for k, v in group["channels"].items()),
                key=lambda item: -item["count"],
            )
            moment = datetime.fromtimestamp(slot, MOSCOW_TZ)
            points.append({
                "ts": int(slot),
                "label": moment.strftime("%d.%m %H:%M"),
                "time": moment.strftime("%H:%M"),
                "date": moment.strftime("%d.%m"),
                "weekday": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][
                    moment.weekday()
                ],
                "total": group["total"],
                "failed": group["failed"],
                "problems": group.get("problems", 0),
                "resolved": group.get("resolved", 0),
                "channels": channel_list,
                "by_channel": group.get("by_channel", {}),
                "statuses": group["statuses"],
                "severities": group["severities"],
                "approximate": bool(group.get("approximate")),
            })

        return {
            "hours": hours,
            "bucket_minutes": bucket_minutes,
            "points": points,
            "max_total": max((p["total"] for p in points), default=0),
        }

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
            # РС‚РѕРі РґРЅСЏ СЃС‡РёС‚Р°РµРј РїРѕ СЂР°Р·Р±РёРІРєРµ РїРѕ РєР°РЅР°Р»Р°Рј, РµСЃР»Рё РѕРЅР° РµСЃС‚СЊ.
            # Р Р°РЅСЊС€Рµ Р±СЂР°Р»СЃСЏ СЃС‡С‘С‚С‡РёРє sent, Р° РєР°РЅР°Р»С‹ Р·Р°РїРѕР»РЅСЏР»РёСЃСЊ С‚РѕР»СЊРєРѕ
            # С‡Р°СЃС‚СЊСЋ РїСѓС‚РµР№ вЂ” РёС‚РѕРі Рё РґРµС‚Р°Р»РёР·Р°С†РёСЏ СЂР°СЃС…РѕРґРёР»РёСЃСЊ (18 РїСЂРѕС‚РёРІ 4).
            channel_sum = sum(int(v) for v in channels.values())
            count = channel_sum if channels else int(day.get("sent", 0))
            result.append({
                "date": key,
                "count": count,
                "failed": int(day.get("failed", 0)),
                "restarts": int(day.get("restarts", 0)),
                "channels": len(channels),
                "by_channel": by_channel,
            })
        return {"days": result}

    def summary(self) -> Dict[str, Any]:
        """Короткая сводка для панели."""
        today_key = self._day_key()
        day = self._daily.get(today_key, {})
        points = self.history(24)["points"]
        latencies = [p["latency"] for p in points if p.get("latency")]
        return {
            "today_sent": int(day.get("sent", 0)),
            "today_failed": int(day.get("failed", 0)),
            "today_channels": len(day.get("channels", {}) or {}),
            "last24_sent": sum(p["sent"] for p in points),
            "last24_failed": sum(p["failed"] for p in points),
            "avg_latency": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "top_channels": self.channel_totals(points)[:5],
            "statuses": self._status_totals(points),
            "points": len(self._hourly),
            "days": len(self._daily),
        }
