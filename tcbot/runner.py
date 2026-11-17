# -*- coding: utf-8 -*-
"""
Супервизор соединения (watchdog + heartbeat + переподключение).

Зачем нужен:
    SDK умеет переподключаться сам (ws_max_retries), но в ряде ситуаций цикл
    соединения завершается окончательно: сеть недоступна дольше лимита попыток,
    сервер отверг токен, сессия «зависла» без обрыва TCP. В этом случае объект
    Bot больше никогда не восстановит WebSocket, а приложение продолжит работать
    «вхолостую» — именно так возникала ошибка «WS is not attached».

Что делает BotRunner:
    1. Держит корутину bot.run() под наблюдением и пересоздаёт Bot при её смерти.
    2. Следит за connected_event/authorized_event и фиксирует потерю/возврат связи.
    3. В режимах heartbeat smart/strict периодически проверяет живое соединение
       лёгким API-вызовом (getChats) и перезапускает соединение при «тишине».
    4. Экспонирует health() для веб-GUI, /health и /ready.
"""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from trueconf import Bot, Dispatcher
from trueconf.exceptions import ApiErrorException, TrueConfChatBotError, WSConnectionError

logger = logging.getLogger("bot")
error_log = logging.getLogger("error")


class RestartSignal(Exception):
    """Внутренний сигнал: соединение требует пересоздания."""


class BotRunner:
    def __init__(
        self,
        *,
        dispatcher: Dispatcher,
        token_manager,
        server: str,
        verify_ssl: bool = True,
        web_port: Optional[int] = None,
        sdk_timeout: float = 15.0,
        ws_max_retries: int = 5,
        ws_max_delay: int = 60,
        receive_unread: bool = False,
        skip_self: bool = True,
        heartbeat_mode: str = "smart",
        heartbeat_interval: int = 30,
        watchdog_interval: int = 15,
        idle_threshold: int = 300,
        probe_timeout: float = 10.0,
        max_reconnect_attempts: int = 10,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 1800.0,
        reconnect_backoff: float = 2.0,
        fast_window: float = 600.0,
        quiet_after: float = 600.0,
        on_bot_created: Optional[Callable[[Bot], None]] = None,
    ):
        self.dp = dispatcher
        self.token_manager = token_manager
        self.server = server
        self.verify_ssl = verify_ssl
        self.web_port = web_port
        self.sdk_timeout = sdk_timeout
        self.ws_max_retries = ws_max_retries
        self.ws_max_delay = ws_max_delay
        self.receive_unread = receive_unread
        self.skip_self = skip_self

        self.heartbeat_mode = (heartbeat_mode or "smart").lower()
        self.heartbeat_interval = max(5, int(heartbeat_interval))
        self.watchdog_interval = max(3, min(int(watchdog_interval), self.heartbeat_interval))
        self.idle_threshold = max(self.heartbeat_interval, int(idle_threshold))
        self.probe_timeout = max(3.0, float(probe_timeout))
        self.max_reconnect_attempts = max(1, int(max_reconnect_attempts))
        self.reconnect_delay = max(1.0, float(reconnect_delay))
        self.max_reconnect_delay = max(self.reconnect_delay, float(max_reconnect_delay))
        self.reconnect_backoff = max(1.1, float(reconnect_backoff))
        # Пока простой меньше fast_window — держим частые попытки (короткие обрывы),
        # после — сразу переходим на максимальную паузу (плановые работы).
        self.fast_window = max(30.0, float(fast_window))
        # После quiet_after секунд непрерывного простоя пишем в error.log только
        # первую ошибку — при плановых работах сервер может быть недоступен часами.
        self.quiet_after = max(60.0, float(quiet_after))
        self._outage_started_at: Optional[float] = None
        self._next_retry_at: Optional[float] = None
        self._tls_reported = False

        self.on_bot_created = on_bot_created
        self.bot: Optional[Bot] = None
        self._run_task: Optional[asyncio.Task] = None
        self._supervisor_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._restart_requested = asyncio.Event()

        self._state = "stopped"          # stopped|connecting|authorized|degraded
        self._state_changed_at = datetime.now()
        self._last_error: Optional[str] = None
        self._last_restart_at: Optional[str] = None
        self._started_at: Optional[datetime] = None

        self.restarts = 0
        self.disconnects = 0
        self.probes = 0
        self.probe_failures = 0
        self.consecutive_failures = 0
        self._probe_supported = True
        self._reconnect_delay_current = self.reconnect_delay
        self._events: List[Dict[str, Any]] = []
        self._probe_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # публичное API
    # ------------------------------------------------------------------ #

    @property
    def is_ready(self) -> bool:
        return bool(self.bot and self.bot.authorized_event.is_set())

    def is_ws_connected(self) -> bool:
        return bool(self.bot and self.bot.connected_event.is_set())

    async def start(self) -> None:
        if self._supervisor_task and not self._supervisor_task.done():
            return
        self._stopping = False
        self._restart_requested.clear()
        self._started_at = datetime.now()
        self._supervisor_task = asyncio.create_task(self._supervise(), name="bot-supervisor")
        self._supervisor_task.add_done_callback(self._on_supervisor_done)

    async def stop(self) -> None:
        self._stopping = True
        self._restart_requested.set()
        if self._probe_task and not self._probe_task.done():
            self._probe_task.cancel()
            try:
                await self._probe_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._shutdown_bot()
        self._set_state("stopped")

    async def force_restart(self, reason: str = "manual") -> None:
        """Принудительно пересоздать соединение (используется из админ-панели)."""
        logger.warning(f"♻️ Принудительный перезапуск соединения: {reason}")
        self._record_event("manual_restart", reason)
        self._restart_requested.set()

    async def wait_ready(self, timeout: float = 60.0) -> bool:
        """Ждёт авторизации бота (используется при старте приложения)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.is_ready:
                return True
            if self._stopping:
                return False
            await asyncio.sleep(0.5)
        return self.is_ready

    def health(self) -> Dict[str, Any]:
        bot_health: Optional[Dict[str, Any]] = None
        if self.bot is not None:
            try:
                bot_health = self.bot.health_check()
            except Exception as exc:  # pragma: no cover
                bot_health = {"error": str(exc)}

        uptime = None
        if self._started_at:
            uptime = (datetime.now() - self._started_at).total_seconds()

        now = time.time()
        retry_in = None
        if self._next_retry_at is not None and not self.is_ready:
            retry_in = max(0.0, self._next_retry_at - now)
        outage = None
        if self._outage_started_at is not None and not self.is_ready:
            outage = max(0.0, now - self._outage_started_at)

        return {
            "state": self._state,
            "ready": self.is_ready,
            "ws_connected": self.is_ws_connected(),
            "authorized": self.is_ready,
            "server": self.server,
            "restarts": self.restarts,
            "disconnects": self.disconnects,
            "probes": self.probes,
            "probe_failures": self.probe_failures,
            "last_error": self._last_error,
            "last_restart_at": self._last_restart_at,
            "state_changed_at": self._state_changed_at.isoformat(),
            "uptime_seconds": uptime,
            "heartbeat_mode": self.heartbeat_mode,
            "heartbeat_interval": self.heartbeat_interval,
            "watchdog_interval": self.watchdog_interval,
            "reconnect_delay": self.reconnect_delay,
            "reconnect_max_delay": self.max_reconnect_delay,
            "reconnect_fast_window": self.fast_window,
            "next_retry_in_seconds": retry_in,
            "outage_seconds": outage,
            "sdk": bot_health,
        }

    def recent_events(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self._events[-limit:][::-1]

    # ------------------------------------------------------------------ #
    # внутреннее
    # ------------------------------------------------------------------ #

    def _set_state(self, state: str, **extra: Any) -> None:
        if state != self._state:
            self._state_changed_at = datetime.now()
            self._record_event("state", state, **extra)
            logger.info(f"🔗 Состояние соединения: {self._state} → {state}")
            self._state = state
        else:
            self._state = state

    def _record_event(self, kind: str, value: str, **extra: Any) -> None:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, "value": value}
        entry.update(extra)
        self._events.append(entry)
        if len(self._events) > 200:
            del self._events[:-200]

    def _on_supervisor_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            error_log.error("❌ Супервизор соединения завершился с ошибкой", exc_info=exc)

    def _build_bot(self) -> Bot:
        return Bot(
            server=self.server,
            token=self.token_manager.token,
            dispatcher=self.dp,
            receive_unread_messages=self.receive_unread,
            skip_self_messages=self.skip_self,
            verify_ssl=self.verify_ssl,
            web_port=self.web_port,
            ws_max_retries=self.ws_max_retries,
            ws_max_delay=self.ws_max_delay,
            timeout=self.sdk_timeout,
            on_health_check=self._on_sdk_health,
        )

    async def _on_sdk_health(self, status: Dict[str, Any]) -> None:
        """Колбэк SDK: изменения состояния WebSocket/авторизации."""
        sdk_status = status.get("status")
        if sdk_status == "authorized":
            self._last_error = None
            self.consecutive_failures = 0
            self._reconnect_delay_current = self.reconnect_delay
            self._reset_outage()
            self._set_state("authorized")
        elif sdk_status == "disconnected":
            # Причина есть только при реальном обрыве; при корректной остановке её нет,
            # поэтому такой «разрыв» в статистику не попадает.
            reason = status.get("error")
            if reason:
                self.disconnects += 1
                self._last_error = reason
                error_log.warning(f"🔌 Соединение с сервером потеряно: {reason}")
                self._set_state("degraded")
            else:
                logger.info("🛑 Соединение закрыто (остановка/перезапуск бота)")
                self._set_state("connecting")
        self._record_event("sdk", str(sdk_status))

    async def _shutdown_bot(self) -> None:
        task = self._run_task
        self._run_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        bot = self.bot
        self.bot = None
        if bot is not None:
            try:
                await asyncio.wait_for(bot.shutdown(timeout=5), timeout=15)
            except Exception as exc:
                logger.warning(f"⚠️ Ошибка остановки SDK-бота: {exc}")

    async def _supervise(self) -> None:
        self._set_state("connecting")
        while not self._stopping:
            token = await self.token_manager.get_token()
            if not token:
                delay = self._reconnect_delay_current
                self.consecutive_failures += 1
                self._last_error = "не удалось получить токен"
                if self._outage_started_at is None:
                    self._outage_started_at = time.time()
                self._set_state("connecting")
                await self._sleep_before_retry(delay)
                self._reconnect_delay_current = min(
                    self._reconnect_delay_current * self.reconnect_backoff,
                    self.max_reconnect_delay,
                )
                continue

            bot = self._build_bot()
            self.bot = bot
            if self.on_bot_created is not None:
                try:
                    self.on_bot_created(bot)
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"⚠️ on_bot_created: {exc}")
            self._run_task = asyncio.create_task(bot.run(handle_signals=False), name="bot-run")
            self.restarts += 1
            if self.restarts > 1:
                self._last_restart_at = datetime.now().isoformat(timespec="seconds")

            try:
                ready = await self._wait_ready(bot, timeout=max(30, self.ws_max_delay * 2))
                if not ready:
                    raise RestartSignal("не удалось авторизоваться за отведённое время")

                self._reset_outage()
                self._set_state("authorized")
                self.consecutive_failures = 0
                self._reconnect_delay_current = self.reconnect_delay

                await self._monitor(bot)
            except asyncio.CancelledError:
                raise
            except RestartSignal as signal:
                self.consecutive_failures += 1
                self._last_error = str(signal)
                error_log.error(f"♻️ Перезапуск соединения: {signal}")
                self._set_state("connecting")
            except (ssl.SSLError, ssl.CertificateError) as exc:
                self.consecutive_failures += 1
                reason = getattr(exc, "verify_message", None) or getattr(exc, "reason", None) or str(exc)
                self._last_error = f"TLS: {reason}"
                self._report_tls_failure(reason)
                self._set_state("connecting")
            except TrueConfChatBotError as exc:
                self.consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                error_log.error(f"♻️ Ошибка библиотеки: {self._last_error}")
                self._set_state("connecting")
            except Exception as exc:
                self.consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                error_log.error("♻️ Непредвиденная ошибка соединения", exc_info=exc)
                self._set_state("connecting")
            finally:
                await self._shutdown_bot()

            if self._stopping:
                break

            if self.consecutive_failures >= self.max_reconnect_attempts:
                logger.warning(
                    f"🔑 {self.consecutive_failures} неудачных попыток подряд — "
                    f"обновляем токен"
                )
                await self.token_manager.get_token(force_refresh=True)

            delay = self._reconnect_delay_current
            await self._sleep_before_retry(delay)

            # Экспоненциальный рост с потолком: после нескольких попыток пауза
            # выходит на максимум (по умолчанию 30 минут) — при плановых работах
            # сервер может быть недоступен часами, долбить его незачем.
            self._reconnect_delay_current = min(
                self._reconnect_delay_current * self.reconnect_backoff,
                self.max_reconnect_delay,
            )

    async def _sleep_before_retry(self, delay: float) -> None:
        """Пауза перед переподключением с «тихим» режимом при долгом простое."""
        now = time.time()
        if self._outage_started_at is None:
            self._outage_started_at = now

        outage = now - self._outage_started_at

        if outage >= self.fast_window:
            delay = self.max_reconnect_delay

        quiet = outage >= self.quiet_after

        if quiet:
            logger.info(
                f"⏳ Сервер недоступен {outage / 60:.0f} мин — следующая попытка "
                f"через {delay / 60:.0f} мин (подробности в GUI: /)"
            )
        else:
            error_log.warning(f"⏳ Переподключение через {delay:.0f} с")

        self._next_retry_at = now + delay
        try:
            await asyncio.sleep(delay)
        finally:
            self._next_retry_at = None

    def _report_tls_failure(self, reason: str) -> None:
        """
        Ошибка проверки TLS: сеть «жива», но сертификат не принят.

        Частая причина — на сервере TrueConf самоподписанный сертификат, а на
        хосте бота не установлен корпоративный CA. Бесконечные переподключения
        тут не помогут, поэтому выводим инструкцию и предупреждаем оператора.
        """
        self._last_error = f"TLS: {reason}"
        if self._tls_reported:
            logger.debug(f"🔒 Повторная ошибка TLS: {reason}")
        else:
            self._tls_reported = True
            error_log.error(
                f"🔒 Проверка TLS-сертификата не пройдена: {reason}\n"
                f"   Варианты решения:\n"
                f"   1) указать корпоративный CA: VERIFY_SSL=/path/to/ca.pem\n"
                f"   2) отключить проверку: VERIFY_SSL=false\n"
                f"   3) установить CA в систему: "
                f"/usr/local/share/ca-certificates/*.crt && update-ca-certificates"
            )

    def _reset_outage(self) -> None:
        """Сбрасывает счётчик простоя после успешной авторизации."""
        self._tls_reported = False
        if self._outage_started_at is not None:
            outage = time.time() - self._outage_started_at
            if outage >= self.quiet_after:
                logger.info(f"✅ Связь восстановлена после {outage / 60:.0f} мин простоя")
            self._outage_started_at = None
        self._next_retry_at = None

    async def _wait_ready(self, bot: Bot, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._stopping:
            if bot.authorized_event.is_set():
                return True
            if self._run_task and self._run_task.done():
                if not bot.authorized_event.is_set():
                    exc = None if self._run_task.cancelled() else self._run_task.exception()
                    raise RestartSignal(f"connect-task завершилась: {exc or 'cancelled'}")
            if asyncio.get_running_loop().time() > deadline:
                return False
            await asyncio.sleep(0.5)
        return False

    async def _monitor(self, bot: Bot) -> None:
        """Наблюдение за живым соединением: watchdog + heartbeat."""
        last_probe = asyncio.get_running_loop().time()
        lost_since: Optional[float] = None

        while not self._stopping:
            await asyncio.sleep(self.watchdog_interval)

            if self._restart_requested.is_set():
                self._restart_requested.clear()
                raise RestartSignal("запрошен перезапуск")

            if self._run_task and self._run_task.done():
                exc = None if self._run_task.cancelled() else self._run_task.exception()
                raise RestartSignal(f"connect-task завершилась: {exc or 'cancelled'}")

            now = asyncio.get_running_loop().time()

            if not bot.authorized_event.is_set():
                if lost_since is None:
                    lost_since = now
                    self._set_state("degraded")
                elif now - lost_since >= self.idle_threshold:
                    raise RestartSignal("авторизация не восстановлена за idle-порог")
                continue

            lost_since = None
            if self._state != "authorized":
                self._set_state("authorized")
                logger.info("✅ Соединение восстановлено")

            if self.heartbeat_mode == "off" or not self._probe_supported:
                continue

            if now - last_probe >= self.heartbeat_interval:
                last_probe = now
                await self._probe(bot)

    async def _probe(self, bot: Bot) -> None:
        self.probes += 1
        try:
            await asyncio.wait_for(bot.get_chats(count=1), timeout=self.probe_timeout)
            self.probe_failures = 0
            if self.heartbeat_mode == "strict":
                logger.debug("💓 Heartbeat OK")
        except ApiErrorException as exc:
            # Транспорт жив, сервер ответил ошибкой API — это не повод перезапускаться
            self.probe_failures = 0
            if not self._probe_supported:
                return
            self._probe_supported = False
            logger.warning(
                f"⚠️ Heartbeat-проверка недоступна (сервер вернул API-ошибку: {exc}). "
                f"Полагаемся только на события SDK."
            )
        except (WSConnectionError, ConnectionError, asyncio.TimeoutError, OSError) as exc:
            self.probe_failures += 1
            error_log.warning(
                f"💔 Heartbeat не прошёл ({self.probe_failures}/{self._threshold()}): "
                f"{type(exc).__name__}: {exc}"
            )
            if self.heartbeat_mode == "strict" or self.probe_failures >= self._threshold():
                raise RestartSignal(f"heartbeat: {type(exc).__name__}") from exc
        except Exception as exc:
            self.probe_failures += 1
            error_log.warning(f"💔 Heartbeat: непредвиденная ошибка {type(exc).__name__}: {exc}")

    def _threshold(self) -> int:
        return 1 if self.heartbeat_mode == "strict" else 3
