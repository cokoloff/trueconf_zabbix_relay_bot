# Разработка и тесты

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# проверка окружения
python check_stack.py
```

## Запуск тестов

Все тесты работают **без сети и без установленного SDK** — библиотека
`trueconf` подменяется заглушками. Это позволяет проверять логику в любом
окружении, включая CI.

```bash
python scripts/test_markup.py         # сборка разметки сообщений
python scripts/test_roles.py           # извлечение ролей Keycloak
python scripts/test_backoff.py         # расчёт пауз переподключения
python scripts/test_channels.py        # каналы: state, API, команды
python scripts/test_localadmin.py      # локальный администратор
python scripts/test_sso.py             # авторизация панели
python scripts/test_outbox.py          # очередь недоставленных
python scripts/test_smoke.py           # сквозная проверка приложения
```

Каждый скрипт печатает список проверок и завершается кодом 1 при ошибке.

### Что покрыто

| Файл | Проверок | Что проверяет |
|---|---|---|
| `test_markup.py` | 21 | экранирование, отсутствие backticks, переносы, маркеры |
| `test_roles.py` | 18 | роли из токенов, `groups`, `ADMIN_IDS`, регистр |
| `test_backoff.py` | 12 | рост паузы, потолок, сброс после восстановления |
| `test_channels.py` | 45 | изменение каналов, пагинация, невидимые символы, API |
| `test_localadmin.py` | 35 | хэширование, блокировки, смена пароля, автогенерация |
| `test_sso.py` | 22 | 401/403, CSRF, подпись cookie, истечение сессии |
| `test_outbox.py` | 20 | накопление, выгрузка, дедупликация, переполнение |
| `test_smoke.py` | 40 | вебхуки, API панели, команды, пересоздание бота |

## Правила разработки

### Разметка сообщений

Никогда не собирайте текст сообщений конкатенацией строк с markdown-
разметкой. Используйте `MessageBuilder` из `tcbot/markup.py`:

```python
from tcbot.markup import MessageBuilder

build = MessageBuilder()
build.title("Заголовок")
build.line("Поле: ", значение)
build.blank()
build.heading("Раздел:")
build.bullet("/команда", "— описание")
await msg.answer(build.build(), parse_mode=ParseMode.HTML)
```

Он экранирует все значения и отдаёт HTML, который TrueConf отображает корректно.
Подробнее о причинах — в [архитектуре](architecture.md#разметка-сообщений).

### Тесты изолированы от окружения

В начале каждого теста переменные задаются **принудительно** (`os.environ[...] = ...`,
а не `setdefault`), иначе `.env` хоста влияет на результат:

```python
os.environ["LOG_DIR"] = "logs_test"
os.environ["STATE_FILE"] = "bot_state_test.json"
os.environ["ADMIN_IDS"] = "admin@example.com"
```

### Стиль кода

- Python 3.10+, аннотации типов;
- логирование через `logging`, а не `print`;
- внешние данные всегда проходят через экранирование;
- изменения состояния — под `asyncio.Lock`.

## Структура проекта

```
bot_multy.py          точка входа
config.py             конфигурация
check_stack.py        самопроверка окружения
tcbot/                пакет приложения (см. architecture.md)
scripts/              тесты
docs/                 документация
```

## Полезные команды

```bash
# синтаксическая проверка всех модулей
python -m py_compile bot_multy.py config.py check_stack.py tcbot/*.py scripts/*.py

# проверка JS панели
node --check <(python -c "from tcbot.appjs import APP_JS; print(APP_JS)")

# запуск с отладкой SDK
WEBSOCKET_DEBUG=true LOG_LEVEL=DEBUG python bot_multy.py
```

## Отладка

### Бот не подключается

1. `python check_stack.py` — проверка зависимостей и конфигурации;
2. при `CERTIFICATE_VERIFY_FAILED` — см. [TLS в установке](installation.md#tls-сертификат);
3. `curl http://localhost:8080/ready` — покажет состояние соединения;
4. `logs/error.log` — причины сбоев связи.

### Сообщения не доходят

1. `/channels <имя>` в чате — существует ли канал;
2. `logs/webhook.log` — принят ли запрос;
3. страница «Очередь» в панели — не копится ли недоставленное;
4. `curl http://localhost:8080/ready` — авторизован ли бот.
