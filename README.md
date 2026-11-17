<div align="center">

# TrueConf Zabbix Relay Bot

**Ретранслятор уведомлений Zabbix / Grafana / Alertmanager в чаты TrueConf**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![python-trueconf-bot](https://img.shields.io/badge/python--trueconf--bot-1.5.5%2B-green.svg)](https://pypi.org/project/python-trueconf-bot/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

</div>

---

Бот принимает вебхуки от систем мониторинга и доставляет их в чаты TrueConf.
Устойчив к обрывам связи: пока сервер недоступен, сообщения копятся в
durable-очереди на диске и уходят после восстановления. Управляется командами
в чате и через веб-панель.

## Возможности

- **Приём вебхуков** — Zabbix, Grafana, Alertmanager; канал задаётся в URL
  или в теле запроса.
- **Не теряет уведомления** — при недоступности TrueConf сообщение получает
  ответ `202`, пишется на диск и доставляется позже. Очередь переживает
  перезапуск.
- **Сам восстанавливает связь** — супервизор пересоздаёт соединение, следит за
  heartbeat, экспоненциально снижает частоту попыток при долгом простое.
- **Веб-панель** — состояние, каналы, очередь, логи, настройки, администраторы.
- **Два способа входа** — SSO через Keycloak и локальный администратор
  (работает, даже когда Keycloak недоступен).
- **Раздельные логи** — `bot`, `chat`, `webhook`, `error`, `delete`,
  `error_history` с ротацией.
- **Готов к контейнеру** — `Dockerfile` и `docker-compose.yml` в комплекте.

## Быстрый старт

### Docker (рекомендуется)

```bash
git clone https://github.com/cokoloff/trueconf_zabbix_relay_bot.git
cd trueconf_zabbix_relay_bot

cp .env.example .env
# отредактируйте .env: TRUECONF_SERVER, TRUECONF_PASSWORD, ADMIN_IDS

docker compose up -d --build
docker compose logs -f tcbot
```

Панель управления: `http://<host>:8080/`

### Без Docker

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# заполните .env

python bot_multy.py
```

## Настройка вебхуков

В Zabbix укажите media type **Webhook**:

| Параметр | Значение |
|---|---|
| URL | `http://<host>:8080/webhook?channel=<имя>` |
| Метод | POST |
| Тело | `{"subject": "{ALERT.SUBJECT}", "message": "{ALERT.MESSAGE}"}` |

Для Grafana / Alertmanager достаточно указать тот же URL — бот понимает формат
`{"alerts": [...]}`.

**Каналы** создаются командой `/register <имя>` в нужном чате TrueConf либо
в панели на странице «Каналы». Если канал не указан, уведомление уходит в чат
по умолчанию.

### Коды ответа

| Код | Значение |
|---|---|
| 200 | доставлено |
| 202 | TrueConf недоступен — принято в очередь, будет доставлено позже |
| 400 | нет сообщения или не задан канал |
| 404 | канал не найден |
| 503 | недоставлено и не удалось поставить в очередь |

## Команды в чате

Публичные: `/help`, `/info`, `/health`, `/ping`, `/whoami`.

Для администраторов: `/register`, `/unregister`, `/channels [стр]`,
`/channel_edit`, `/default`, `/admins`, `/admin_add`, `/admin_remove`,
`/token_info`.

## Документация

- [Установка и настройка](docs/installation.md) — параметры окружения, systemd, Docker
- [Веб-панель и SSO](docs/web-panel.md) — вход через Keycloak, роли, локальный администратор
- [Устройство и отказоустойчивость](docs/architecture.md) — супервизор, очередь, разметка сообщений
- [Разработка и тесты](docs/development.md) — запуск тестов, структура проекта

## Требования

- **TrueConf Server 5.5.x** (проверено на 5.5.8)
- `python-trueconf-bot >= 1.5.5`
- Python 3.10+ (в контейнере 3.12)

## Лицензия

MIT — см. [LICENSE](LICENSE).
