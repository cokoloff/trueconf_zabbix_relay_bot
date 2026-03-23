# TrueConf Zabbix Relay Bot

Бот-реле для отправки уведомлений из Zabbix и других систем мониторинга в TrueConf. Получает вебхуки и пересылает сообщения в указанные чаты TrueConf.

## 🚀 Особенности

- **Минималистичный** - отправляет только то, что получил, без добавления времени, ID и служебной информации
- **Автоматическое получение токена** - бот сам получает и обновляет токен через API
- **Мультиканальность** - поддержка нескольких каналов для разных типов уведомлений
- **Администрирование** - управление каналами и правами доступа через команды бота
- **Heartbeat** - мониторинг состояния соединения
- **Автосохранение** - состояние бота сохраняется при перезапуске

## 📋 Требования

- Python 3.8+
- TrueConf Server (версия с поддержкой Bot API)
- Доступ к API TrueConf для получения токена

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
git clone https://github.com/yourusername/trueconf-zabbix-bot.git
cd trueconf-zabbix-bot

# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Установка зависимостей
pip install -r requirements.txt

# Просто запускаем
python bot.py

# Или с ENV переменными
export TRUECONF_PASSWORD="your_password"
export ADMIN_IDS="admin1@domain.ru,admin2@domain.ru"
python bot.py

# Или создаем config.local.py для локальных настроек
cat > config.local.py << EOF
TRUECONF_PASSWORD = "your_password"
ADMIN_IDS = ["admin1@domain.ru", "admin2@domain.ru"]
EOF
python bot.py
```

### 2. Настройка конфигурации
```python
# TrueConf настройки
TRUECONF_SERVER = "vcs.your-domain.ru"

# Настройки для получения токена
TRUECONF_TOKEN_URL = "https://vcs.your-domain.ru/bridge/api/client/v1/oauth/token"
TRUECONF_CLIENT_ID = "chat_bot"
TRUECONF_USERNAME = "your-bot-username"
TRUECONF_PASSWORD = "your-bot-password"

# Веб-сервер
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = 8080

# Администрирование
ADMIN_MODE = "strict"  # open, strict
ADMIN_IDS = "user1@domain.ru,user2@domain.ru"  # ID администраторов
```
### 3. Запуск бота
```bash
python bot.py
```

## 🤖 Команды бота

### Публичные команды

| Команда | Описание |
|---------|----------|
| `/help` | Показать справку по командам |
| `/info` | Информация о боте и статистика |
| `/health` | Состояние WebSocket соединения |
| `/ping` | Проверка доступности бота |
| `/whoami` | ID пользователя и чата |

### Команды администратора

| Команда | Описание | Пример |
|---------|----------|--------|
| `/register <имя>` | Создать канал в текущем чате | `/register alerts` |
| `/unregister <имя>` | Удалить канал | `/unregister alerts` |
| `/channels` | Список всех каналов | `/channels` |
| `/default` | Установить чат по умолчанию | `/default` |
| `/admins` | Список администраторов | `/admins` |
| `/admin_add <id>` | Добавить администратора | `/admin_add user@domain.ru` |
| `/admin_remove <id>` | Удалить администратора | `/admin_remove user@domain.ru` |
| `/token_info` | Информация о токене | `/token_info` |

### Пример использования

```bash
# Регистрация канала
/register critical

# Отправка уведомления
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "critical",
    "subject": "⚠️ ПРОБЛЕМА",
    "message": "Сервер не отвечает"
  }'
```

## 📝 Примеры интеграции

### Zabbix

**1. Создайте медиа тип "Webhook" в Zabbix**

**2. Параметры медиа типа:**

| Параметр | Значение |
|----------|----------|
| Тип | Webhook |
| URL | `http://your-bot-server:8080/webhook` |
| HTTP метод | POST |
| Content-Type | application/json |

**3. Шаблон сообщения:**

```json
{
  "channel": "alerts",
  "subject": "{TRIGGER.NAME}",
  "message": "Статус: {TRIGGER.STATUS}\nСервер: {HOST.NAME}\nIP: {HOST.IP}\nВремя: {EVENT.DATE} {EVENT.TIME}\n\n{TRIGGER.DESCRIPTION}"
}
```
### Архитектура
```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│                 │     │                  │     │                 │
│  Zabbix         │───▶│  Web Server      │────▶│  Bot            │
│  Prometheus     │     │  (aiohttp)       │     │  (trueconf)     │
│  Custom Scripts │     │  Port: 8080      │     │                 │
│                 │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                  │                        │
                                  ▼                        ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │                  │     │                 │
                        │  StateManager    │     │  TokenManager   │
                        │  (bot_state.json)│     │  (token API)    │
                        │                  │     │                 │
                        └──────────────────┘     └─────────────────┘
```


### Сборка и запуск в Docker
```bash
# С ENV переменными
docker run -d \
  --name trueconf-bot \
  -p 8080:8080 \
  -e TRUECONF_PASSWORD="your_password" \
  -e ADMIN_IDS="admin1@domain.ru,admin2@domain.ru" \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  trueconf-bot

# С .env файлом
docker run -d \
  --name trueconf-bot \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  trueconf-bot

# Проверка статуса контейнера
docker ps | grep trueconf-bot

# Проверка логов
docker-compose logs trueconf-bot

# Проверка healthcheck
docker inspect --format='{{.State.Health.Status}}' trueconf-zabbix-bot

# Отправка тестового вебхука
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "test",
    "subject": "Docker Test",
    "message": "Бот работает в контейнере!"
  }'
```
## 🤝 Вклад в проект

Мы приветствуем любой вклад в развитие проекта! Вот как вы можете помочь:

### Способы участия

- 🐛 **Сообщение об ошибках** - создавайте Issue с подробным описанием проблемы
- 💡 **Предложение идей** - делитесь идеями по улучшению функциональности
- 📝 **Улучшение документации** - исправляйте опечатки, дополняйте примеры
- 🔧 **Pull Request** - отправляйте исправления и новые функции
