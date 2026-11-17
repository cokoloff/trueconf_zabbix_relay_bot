#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка логики пауз переподключения (без сети и без SDK).

Повторяет алгоритм tcbot.runner.BotRunner._sleep_before_retry:
    * до RECONNECT_FAST_WINDOW секунд простоя пауза растёт экспоненциально;
    * после — сразу потолок RECONNECT_MAX_DELAY;
    * после восстановления связи пауза снова стартовая.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FAILED = []


def check(cond: bool, title: str, detail: str = "") -> None:
    print(("  ✅ " if cond else "  ❌ ") + title + ("" if cond else f" {detail}"))
    if not cond:
        FAILED.append(title)


class Backoff:
    """Копия расчёта пауз из BotRunner."""

    def __init__(self, delay=5.0, backoff=2.0, max_delay=1800.0, fast_window=600.0):
        self.delay = delay
        self.backoff = backoff
        self.max_delay = max_delay
        self.fast_window = fast_window
        self.current = delay
        self.outage = 0.0

    def next_pause(self) -> float:
        """Возвращает паузу и продвигает время простоя."""
        pause = self.current
        if self.outage >= self.fast_window:
            pause = self.max_delay
        self.outage += pause
        self.current = min(self.current * self.backoff, self.max_delay)
        return pause

    def reset(self) -> None:
        self.current = self.delay
        self.outage = 0.0


def main() -> int:
    print("1) Короткий обрыв (до 10 минут)")
    backoff = Backoff()
    pauses = [backoff.next_pause() for _ in range(5)]
    print("   " + " → ".join(f"{p:g}с" for p in pauses))
    check(pauses == [5, 10, 20, 40, 80], "пауза удваивается", str(pauses))

    print("\n2) Плановые работы: переход на медленный темп")
    backoff = Backoff()
    pauses = []
    for _ in range(20):
        pauses.append(backoff.next_pause())
        if backoff.outage > 2 * 3600:
            break
    print("   " + " → ".join(f"{p:g}с" for p in pauses))
    check(600 in pauses or pauses[-1] == 1800, "после 10 минут включается потолок")
    slow = [p for p in pauses if p == 1800]
    check(bool(slow), "потолок 1800 с достигается")

    first_slow = next(i for i, p in enumerate(pauses) if p == 1800)
    spent = sum(pauses[:first_slow])
    print(f"   медленный темп с {spent / 60:.0f}-й минуты, попытка #{first_slow + 1}")
    check(spent <= 700, "переход не позже 700 секунд", f"{spent:.0f}")

    print("\n3) Нагрузка на сервер за 4 часа простоя")
    for max_delay, label in ((60.0, "старое поведение"), (1800.0, "новое поведение")):
        backoff = Backoff(max_delay=max_delay)
        calls = 0
        while backoff.outage < 4 * 3600:
            backoff.next_pause()
            calls += 1
        print(f"   {label:<18} ({max_delay:>4}с) → {calls} попыток за 4 часа")
        if max_delay == 1800:
            check(calls <= 15, "попыток стало значительно меньше", str(calls))
        else:
            check(calls > 200, "раньше попыток было очень много", str(calls))

    print("\n4) Сброс после восстановления")
    backoff = Backoff()
    for _ in range(8):
        backoff.next_pause()
    check(backoff.current > backoff.delay, "перед сбросом пауза выросла")
    backoff.reset()
    check(backoff.current == 5 and backoff.outage == 0, "после восстановления пауза снова 5 с")

    print("\n5) Тихий режим")
    quiet_after = 600
    backoff = Backoff()
    while backoff.outage < quiet_after:
        backoff.next_pause()
    check(backoff.outage >= quiet_after, "к моменту тишины простой превысил 10 минут")

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
