#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка живости контейнера.

Обращается к собственному /health. Используется в HEALTHCHECK Dockerfile —
отдельный файл вместо однострочника: вложенные кавычки в JSON-массиве
Dockerfile легко сломать при правке.
"""

import os
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("WEB_SERVER_PORT", "8080")
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                return 0
            print(f"health: HTTP {response.status}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"health: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
