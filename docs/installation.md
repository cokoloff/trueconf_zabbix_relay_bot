# Установка и настройка

## Содержание

- [Требования](#требования)
- [Docker](#docker)
- [Без Docker](#без-docker)
- [Параметры окружения](#параметры-окружения)
- [TLS-сертификат](#tls-сертификат)
- [systemd](#systemd)
- [Обновление](#обновление)

## Требования

| Компонент | Версия |
|---|---|
| TrueConf Server | 5.5.x (боты поддерживаются с 5.5.0) |
| Python | 3.10+ |
| python-trueconf-bot | >= 1.5.5 |

Сервисная учётная запись TrueConf должна иметь право создавать ботов.
Вебхуки приходят по HTTP — обычно достаточно разрешить доступ от сервера
Zabbix/Grafana к порту панели.

## Docker

### Сборка и запуск

```bash
cp .env.example .env
# отредактируйте .env

docker compose up -d --build
docker compose logs -f tcbot
```

### Что внутри образа

- базовый слой `python:3.12-slim`;
- `libmagic1` — требуется библиотекой `python-magic` из SDK;
- приложение работает от непривилегированного пользователя `tcbot` (uid 10001);
- `HEALTHCHECK` обращается к `/health` каждые 30 секунд.

### Тома

| Том | Что хранит |
|---|---|
| `tcbot-data` | `bot_state.json`, `bot_token.json`, `bot_outbox.json`, файл стартового пароля local-admin |
| `tcbot-logs` | файлы логов |

Тома переживают пересоздание контейнера. Удалить их можно командой
`docker compose down -v` — **это уничтожит состояние и очередь**.

### Проверка

```bash
curl -s http://localhost:8080/health   # {"status":"ok","version":"12.0"}
curl -s http://localhost:8080/ready    # 200 когда бот авторизован, иначе 503
```

`/health` — живость процесса, `/ready` — реальная готовность (WebSocket
подключён и бот авторизован). Для мониторинга самого бота используйте `/ready`.

## Без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
$EDITOR .env

python bot_multy.py
```

Проверить окружение до запуска:

```bash
python check_stack.py
```

Скрипт проверяет версию Python, наличие SDK нужной версии, зависимости и
корректность настроек авторизации.

## Параметры окружения

Полный список — в [.env.example](../.env.example). Ключевые группы:

### Подключение к TrueConf

| Переменная | Описание |
|---|---|
| `TRUECONF_SERVER` | адрес сервера, например `trueconf.example.com` |
| `TRUECONF_USERNAME` / `TRUECONF_PASSWORD` | сервисная учётная запись |
| `VERIFY_SSL` | `true` / `false` / путь к CA-бандлу |
| `GROUP_CHAT_ID` | чат по умолчанию (можно задать позже командой `/default`) |

### Поведение при обрыве

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `HEARTBEAT_MODE` | `smart` | `off` / `smart` (3 неудачи) / `strict` (сразу) |
| `RECONNECT_FAST_WINDOW` | `600` | сколько секунд держать частые попытки |
| `RECONNECT_MAX_DELAY` | `1800` | потолок паузы между попытками |
| `QUIET_AFTER` | `600` | после какого простоя перестать писать в `error.log` |

### Очередь недоставленных

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `OUTBOX_MAX_SIZE` | `5000` | сколько сообщений хранить |
| `OUTBOX_TTL_HOURS` | `48` | сколько часов хранить |
| `OUTBOX_COLLAPSE` | `true` | оставлять последнее состояние по триггеру |

## TLS-сертификат

Если в логах появляется `[SSL: CERTIFICATE_VERIFY_FAILED]`, значит сертификат
сервера TrueConf не проходит проверку. Три варианта:

**1. Указать CA-бандл (рекомендуется)**

```
VERIFY_SSL=/etc/ssl/certs/corp-ca.pem
```

В Docker смонтируйте файл в контейнер:

```yaml
volumes:
  - ./corp-ca.pem:/etc/ssl/certs/corp-ca.pem:ro
environment:
  VERIFY_SSL: /etc/ssl/certs/corp-ca.pem
```

**2. Установить CA в систему**

```bash
sudo cp corp-ca.crt /usr/local/share/ca-certificates/corp-ca.crt
sudo update-ca-certificates
```

**3. Отключить проверку** (только в доверенной сети)

```
VERIFY_SSL=false
```

При старте бот проверяет TLS заранее и пишет результат в лог:

```
🔒 Проверка TLS: по системному хранилищу (truststore)
🔒 TLS-соединение с сервером проверено
```

## systemd

`/etc/systemd/system/tcbot.service`:

```ini
[Unit]
Description=TrueConf Zabbix Relay Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tcbot
WorkingDirectory=/opt/tcbot
EnvironmentFile=/opt/tcbot/.env
ExecStart=/opt/tcbot/.venv/bin/python bot_multy.py
Restart=always
RestartSec=5

# Логи пишутся в файлы приложения
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tcbot
sudo journalctl -u tcbot -f
```

## Обновление

### Docker

```bash
git pull
docker compose up -d --build
```

### Без Docker

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart tcbot
```

Состояние и очередь хранятся отдельно от кода и при обновлении не теряются.
