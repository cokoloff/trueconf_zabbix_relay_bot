# -*- coding: utf-8 -*-
"""
Локальный администратор панели — альтернатива SSO.

Зачем: если Keycloak недоступен, панель не должна становиться недоступной.
Учётная запись local-admin хранится в самом боте (пароль — только в виде хэша)
и работает независимо от внешних сервисов.

Хранение пароля:
    PBKDF2-HMAC-SHA256, 260 000 итераций, случайная соль 16 байт.
    Формат: pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>

Первый запуск без пароля:
    пароль генерируется случайно, хэш сохраняется, а сам пароль пишется один раз
    в файл local-admin-initial-password.txt рядом с состоянием бота (у файла
    выставляются права 0600 на POSIX). После смены пароля файл можно удалить.

Защита от подбора:
    счётчик неудач по паре (IP, логин) с блокировкой и ростом задержки:
    5 неудач → 60 с, далее 300 с, далее 900 с.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("bot")

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16

# политика блокировки
MAX_ATTEMPTS = 5
LOCKOUT_STEPS = (60, 300, 900)


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    """Возвращает строку-хэш пароля в формате pbkdf2_sha256$..."""
    if not password:
        raise ValueError("пустой пароль недопустим")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    """Проверяет пароль по сохранённому хэшу (сравнение постоянного времени)."""
    if not password or not stored:
        return False
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            logger.error(f"❌ Неизвестный алгоритм хэша: {algorithm}")
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(expected, actual)
    except Exception as exc:
        logger.error(f"❌ Ошибка проверки пароля: {exc}")
        return False


def is_valid_hash(stored: str) -> bool:
    """
    Проверяет, что строка действительно является нашим хэшем.

    Защищает от типичной ошибки конфигурации: в LOCAL_ADMIN_PASSWORD_HASH
    по ошибке попадает client_secret, токен или обычный пароль. Без проверки
    такой «хэш» сохранялся, и вход становился невозможен.
    """
    if not stored or not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations, salt_b64, hash_b64 = parts
    if algorithm != ALGORITHM:
        return False
    try:
        if int(iterations) < 1:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        digest = base64.b64decode(hash_b64, validate=True)
    except Exception:
        return False
    return len(salt) >= 8 and len(digest) == 32


def password_problems(password: str) -> List[str]:
    """Проверка требований к новому паролю."""
    problems: List[str] = []
    if len(password or "") < 12:
        problems.append("минимум 12 символов")
    if len(password or "") > 256:
        problems.append("не длиннее 256 символов")
    if not any(ch.isdigit() for ch in password or ""):
        problems.append("хотя бы одна цифра")
    if not any(ch.isalpha() for ch in password or ""):
        problems.append("хотя бы одна буква")
    return problems


@dataclass
class LoginAttempt:
    failures: int = 0
    locked_until: float = 0.0
    step: int = 0


class LocalAdminStore:
    """Учётная запись local-admin и учёт попыток входа."""

    def __init__(
        self,
        *,
        state_getter,
        state_setter,
        username: str = "local-admin",
        password: str = "",
        password_hash: str = "",
        enabled: bool = True,
        initial_password_file: str = "local-admin-initial-password.txt",
        iterations: int = ITERATIONS,
    ):
        self.state_getter = state_getter
        self.state_setter = state_setter
        self.username = (username or "local-admin").strip()
        self.enabled = bool(enabled)
        self.initial_password_file = Path(initial_password_file)
        self.iterations = iterations
        self._attempts: Dict[str, LoginAttempt] = {}

        record = self._load() or {}
        stored_hash = record.get("password_hash", "")
        stored_user = record.get("username") or self.username
        self.username = stored_user

        changed = False

        # Приоритет у явного открытого пароля: если администратор задал
        # LOCAL_ADMIN_PASSWORD, он и должен работать. Хэш используется, когда
        # пароль не задан.
        if password:
            if password_hash:
                logger.warning(
                    "⚠️ Заданы LOCAL_ADMIN_PASSWORD и LOCAL_ADMIN_PASSWORD_HASH — "
                    "используется пароль из LOCAL_ADMIN_PASSWORD"
                )
            stored_hash = hash_password(password, iterations)
            changed = True
            logger.info("🔐 Пароль local-admin взят из LOCAL_ADMIN_PASSWORD и сохранён как хэш")
        elif password_hash:
            if is_valid_hash(password_hash):
                stored_hash = password_hash
                changed = True
            else:
                logger.error(
                    "❌ LOCAL_ADMIN_PASSWORD_HASH не похож на наш хэш "
                    "(ожидается pbkdf2_sha256$<итерации>$<соль>$<хеш>). "
                    "Значение проигнорировано — используется ранее сохранённый пароль."
                )

        if stored_hash and not is_valid_hash(stored_hash):
            logger.error(
                "❌ В состоянии сохранён некорректный хэш local-admin — "
                "он будет заменён."
            )
            stored_hash = ""

        if not stored_hash:
            if not self.enabled:
                logger.info("🔐 Локальный администратор выключен")
            else:
                generated = secrets.token_urlsafe(18)
                stored_hash = hash_password(generated, iterations)
                changed = True
                self._dump_initial_password(generated)
                logger.warning(
                    "🔐 Для local-admin сгенерирован пароль — он записан в "
                    f"{self.initial_password_file.resolve()}. "
                    "Смените пароль в панели и удалите файл."
                )

        if changed:
            self._save({"username": self.username, "password_hash": stored_hash})
        else:
            self._save({"username": self.username, "password_hash": stored_hash}) if not record else None

    # ------------------------------ состояние ------------------------------ #

    def _load(self) -> Optional[dict]:
        try:
            data = self.state_getter() or {}
            record = data.get("local_admin")
            return record if isinstance(record, dict) else None
        except Exception as exc:
            logger.error(f"❌ Не удалось прочитать local_admin из состояния: {exc}")
            return None

    def _save(self, record: dict) -> None:
        try:
            record = dict(record)
            record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            data = self.state_getter() or {}
            data["local_admin"] = record
            self.state_setter(data)
        except Exception as exc:
            logger.error(f"❌ Не удалось сохранить local_admin: {exc}")

    def _dump_initial_password(self, password: str) -> None:
        try:
            self.initial_password_file.write_text(
                "Пароль локального администратора панели TrueConf Zabbix Relay Bot\n"
                f"Логин: {self.username}\n"
                f"Пароль: {password}\n\n"
                "Смените пароль в панели (карточка «Локальный администратор») "
                "и удалите этот файл.\n",
                encoding="utf-8",
            )
            if os.name == "posix":
                os.chmod(self.initial_password_file, 0o600)
        except Exception as exc:
            logger.error(f"❌ Не удалось записать стартовый пароль в файл: {exc}")
            logger.warning(f"🔐 Стартовый пароль local-admin: {password}")

    # ------------------------------- проверка ------------------------------- #

    @property
    def is_configured(self) -> bool:
        record = self._load() or {}
        return bool(record.get("password_hash"))

    def _key(self, ip: str, username: str) -> str:
        return f"{ip}|{username.lower()}"

    def lock_remaining(self, ip: str, username: str) -> float:
        attempt = self._attempts.get(self._key(ip, username))
        if attempt and attempt.locked_until > time.time():
            return attempt.locked_until - time.time()
        return 0.0

    def authenticate(self, username: str, password: str, ip: str = "") -> Tuple[bool, str]:
        """
        Проверяет логин и пароль.

        Возвращает (успех, причина отказа). Учитывает блокировку по попыткам.
        """
        if not self.enabled:
            return False, "локальный вход отключён"

        key = self._key(ip, username)

        # защита от подбора
        attempt = self._attempts.setdefault(key, LoginAttempt())
        remaining = self.lock_remaining(ip, username)
        if remaining > 0:
            return False, f"слишком много попыток, повторите через {int(remaining) + 1} с"

        record = self._load() or {}
        stored_hash = record.get("password_hash", "")
        stored_user = record.get("username") or self.username

        if not stored_hash:
            return False, "пароль не задан"

        # сравнение логина постоянного времени + проверка пароля
        user_ok = hmac.compare_digest(stored_user.lower(), (username or "").lower())
        pass_ok = verify_password(password or "", stored_hash)

        if user_ok and pass_ok:
            self._attempts.pop(key, None)
            logger.info(f"✅ Вход local-admin: {stored_user} (ip={ip or '—'})")
            return True, "ok"

        attempt.failures += 1
        if attempt.failures >= MAX_ATTEMPTS:
            step = min(attempt.step, len(LOCKOUT_STEPS) - 1)
            delay = LOCKOUT_STEPS[step]
            attempt.locked_until = time.time() + delay
            attempt.failures = 0
            attempt.step = min(attempt.step + 1, len(LOCKOUT_STEPS) - 1)
            logger.warning(
                f"🚫 local-admin: {MAX_ATTEMPTS} неудачных попыток с {ip or '—'} для '{username}', "
                f"блокировка {delay} с"
            )
        else:
            logger.warning(
                f"⚠️ Неудачный вход local-admin: '{username}' с {ip or '—'} "
                f"({attempt.failures}/{MAX_ATTEMPTS})"
            )
        return False, "неверный логин или пароль"

    def change_password(self, current: str, new: str, ip: str = "") -> Tuple[bool, str]:
        """Меняет пароль local-admin (требует текущий пароль)."""
        if not self.enabled:
            return False, "локальный вход отключён"
        ok, reason = self.authenticate(self.username, current, ip)
        if not ok:
            return False, reason

        problems = password_problems(new)
        if problems:
            return False, "пароль слишком простой: " + ", ".join(problems)

        self._save({"username": self.username, "password_hash": hash_password(new, self.iterations)})
        self._attempts.clear()
        if self.initial_password_file.exists():
            try:
                self.initial_password_file.unlink()
                logger.info("🧹 Файл стартового пароля удалён")
            except Exception:
                pass
        logger.info(f"🔑 Пароль local-admin изменён (ip={ip or '—'})")
        return True, "ok"

    def stats(self) -> dict:
        record = self._load() or {}
        return {
            "enabled": self.enabled,
            "username": record.get("username") or self.username,
            "has_password": bool(record.get("password_hash")),
            "updated_at": record.get("updated_at"),
            "initial_password_file": str(self.initial_password_file.resolve())
            if self.initial_password_file.exists()
            else None,
        }
