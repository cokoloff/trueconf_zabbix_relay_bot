# -*- coding: utf-8 -*-
"""
Резервные копии состояния бота.

Файлы состояния (каналы, администраторы, настройки, история ошибок) —
самое ценное, что есть у бота: их потеря означает ручную перенастройку.
Модуль делает копии по расписанию, хранит заданное число последних и
позволяет восстановиться из копии через панель.

Формат имени: bot_state_ГГГГММДД_ЧЧММСС.json — как в прежних версиях,
чтобы старые копии оставались совместимыми.
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot")

# Сколько копий хранить по умолчанию
DEFAULT_KEEP = 20

# Файлы, которые попадают в копию (кроме самого состояния)
EXTRA_FILES = ("bot_token.json", "bot_outbox.json", "bot_metrics.json",
               "bot_delivered.json")


class BackupManager:
    """Создаёт, хранит и восстанавливает резервные копии состояния."""

    def __init__(
        self,
        state_file: str,
        backup_dir: str = "backups",
        keep: int = DEFAULT_KEEP,
        enabled: bool = True,
    ):
        self.state_path = Path(state_file)
        self.backup_dir = Path(backup_dir)
        self.keep = max(1, int(keep))
        self.enabled = enabled

        if self.enabled:
            try:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.error(f"❌ Не удалось создать каталог копий {self.backup_dir}: {exc}")
                self.enabled = False

    # ------------------------------------------------------------------ #
    # создание
    # ------------------------------------------------------------------ #

    def _stamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def create(self, reason: str = "auto") -> Optional[Path]:
        """
        Делает копию файла состояния.

        reason — пометка для журнала («auto», «manual», «before-restore»).
        Возвращает путь к копии или None при ошибке.
        """
        if not self.enabled:
            return None
        if not self.state_path.exists():
            logger.warning(f"⚠️ Копия не создана: {self.state_path} отсутствует")
            return None

        # Имя с точностью до секунды: две копии в одну секунду совпали бы,
        # и страховочная копия перед восстановлением затёрла бы исходную.
        target = self.backup_dir / f"bot_state_{self._stamp()}.json"
        suffix = 1
        while target.exists():
            target = self.backup_dir / (
                f"bot_state_{self._stamp()}_{suffix:02d}.json"
            )
            suffix += 1

        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"❌ Копия не создана — состояние не читается: {exc}")
            return None

        try:
            tmp = target.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(target)
        except Exception as exc:
            logger.error(f"❌ Копия не создана: {exc}")
            return None

        logger.info(f"💾 Резервная копия состояния ({reason}): {target.name}")
        self.rotate()
        return target

    def create_archive(self, target: Optional[Path] = None) -> Optional[Path]:
        """
        Собирает полный архив: состояние и сопутствующие файлы.

        Нужен для выгрузки с сервера — один файл вместо набора.
        """
        target = target or (
            self.backup_dir / f"tcbot_backup_{self._stamp()}.tar.gz"
        )
        candidates = [self.state_path] + [
            self.state_path.parent / name for name in EXTRA_FILES
        ]
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return None

        try:
            with tarfile.open(target, "w:gz") as archive:
                for path in existing:
                    archive.add(path, arcname=path.name)
            logger.info(f"💾 Архив создан: {target.name} ({len(existing)} файлов)")
            return target
        except Exception as exc:
            logger.error(f"❌ Не удалось создать архив: {exc}")
            return None

    def rotate(self) -> int:
        """Удаляет старые копии сверх лимита. Возвращает число удалённых."""
        files = self.list_files()
        if len(files) <= self.keep:
            return 0

        removed = 0
        for path in files[: len(files) - self.keep]:
            try:
                path.unlink()
                removed += 1
            except Exception as exc:
                logger.warning(f"⚠️ Не удалось удалить старую копию {path.name}: {exc}")

        if removed:
            logger.info(f"🧹 Удалено старых копий: {removed} (храним {self.keep})")
        return removed

    # ------------------------------------------------------------------ #
    # список и восстановление
    # ------------------------------------------------------------------ #

    def list_files(self) -> List[Path]:
        """Копии состояния, от старых к новым."""
        if not self.backup_dir.exists():
            return []
        files = [
            path for path in self.backup_dir.glob("bot_state_*.json")
            if path.is_file()
        ]
        return sorted(files, key=lambda path: path.name)

    def list_items(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Описание копий для панели."""
        items: List[Dict[str, Any]] = []
        for path in reversed(self.list_files()[-limit:]):
            try:
                stat = path.stat()
                channels = admins = None
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    channels = len(data.get("notification_channels", {}) or {})
                    admins = len(data.get("admins", []) or [])
                except Exception:
                    pass
                items.append({
                    "name": path.name,
                    "size": stat.st_size,
                    "created_at": int(stat.st_mtime),
                    "channels": channels,
                    "admins": admins,
                })
            except Exception as exc:
                logger.warning(f"⚠️ Не удалось прочитать копию {path.name}: {exc}")
        return items

    def restore(self, name: str) -> Dict[str, Any]:
        """
        Восстанавливает состояние из копии.

        Перед заменой текущее состояние сохраняется — откатиться можно
        всегда. Возвращает описание результата.
        """
        if not self.enabled:
            return {"ok": False, "error": "резервное копирование выключено"}

        # Имя приходит извне — не даём выйти за пределы каталога
        safe_name = Path(name).name
        if not safe_name.startswith("bot_state_") or not safe_name.endswith(".json"):
            return {"ok": False, "error": "недопустимое имя копии"}

        source = self.backup_dir / safe_name
        if not source.exists():
            return {"ok": False, "error": f"копия {safe_name} не найдена"}

        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"копия повреждена: {exc}"}

        if not isinstance(data, dict) or "notification_channels" not in data:
            return {"ok": False, "error": "в копии нет данных состояния"}

        # Сохраняем текущее состояние перед заменой
        safety = self.create("before-restore")
        if safety is None:
            return {"ok": False, "error": "не удалось сохранить текущее состояние"}

        try:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.state_path)
        except Exception as exc:
            return {"ok": False, "error": f"не удалось записать состояние: {exc}"}

        channels = len(data.get("notification_channels", {}) or {})
        admins = len(data.get("admins", []) or [])
        logger.warning(
            f"♻️ Состояние восстановлено из {safe_name}: "
            f"каналов {channels}, администраторов {admins}"
        )
        return {
            "ok": True,
            "restored": safe_name,
            "backup_before": safety.name,
            "channels": channels,
            "admins": admins,
            "version": data.get("version"),
            "note": "для применения изменений перезапустите бота",
        }

    def delete(self, name: str) -> Dict[str, Any]:
        """Удаляет копию по имени."""
        safe_name = Path(name).name
        if not safe_name.startswith("bot_state_") or not safe_name.endswith(".json"):
            return {"ok": False, "error": "недопустимое имя копии"}

        path = self.backup_dir / safe_name
        if not path.exists():
            return {"ok": False, "error": "копия не найдена"}
        try:
            path.unlink()
            logger.info(f"🗑️ Резервная копия удалена: {safe_name}")
            return {"ok": True, "deleted": safe_name}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def stats(self) -> Dict[str, Any]:
        """Сводка для панели."""
        files = self.list_files()
        total = 0
        newest = oldest = None
        for path in files:
            try:
                total += path.stat().st_size
            except Exception:
                pass
        if files:
            newest = files[-1].name
            oldest = files[0].name
        return {
            "enabled": self.enabled,
            "directory": str(self.backup_dir),
            "count": len(files),
            "keep": self.keep,
            "total_size": total,
            "newest": newest,
            "oldest": oldest,
        }
