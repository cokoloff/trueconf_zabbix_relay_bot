"""
TRUECONF ZABBIX RELAY BOT - ФИНАЛЬНАЯ ВЕРСИЯ 10.0
═══════════════════════════════════════════════════════════════════════════════

.. module:: trueconf_zabbix_bot
   :platform: Unix, Windows
   :synopsis: Бот-ретранслятор уведомлений из Zabbix в TrueConf

.. moduleauthor:: Your Name <email@example.com>
.. version:: 10.0
.. date:: 2024


📋 ОГЛАВЛЕНИЕ

1. ОПИСАНИЕ
2. БЫСТРЫЙ СТАРТ
3. КОМАНДЫ БОТА
4. ВЕБХУКИ
5. КАНАЛЫ
6. АДМИНИСТРИРОВАНИЕ
7. ПРИМЕРЫ
8. КОНФИГУРАЦИЯ
9. УСТРАНЕНИЕ ПРОБЛЕМ
10. API REFERENCE



1. ОПИСАНИЕ


TrueConf Zabbix Relay Bot - это минималистичный бот-ретранслятор для отправки 
уведомлений из систем мониторинга (Zabbix, Nagios, Prometheus) в чаты TrueConf.

✨ ОСНОВНЫЕ ВОЗМОЖНОСТИ:
    • Минимализм - отправляет ТОЛЬКО то, что получил (никаких лишних данных)
    • Каналы - разные чаты для разных типов уведомлений
    • Простота - всего 3 параметра: channel, subject, message
    • Безопасность - гибкая система прав доступа
    • Надежность - автоматический контроль соединения (heartbeat)
    • Персистентность - сохранение состояния в JSON

🔧 ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ:
    • Версия: 10.0
    • Python: 3.8+
    • Зависимости: trueconf, aiohttp
    • Протоколы: WebSocket, HTTP
    • Форматы: JSON, form-data


2. БЫСТРЫЙ СТАРТ


🚀 УСТАНОВКА:

    .. code-block:: bash

        # 1. Клонирование репозитория
        git clone https://github.com/cokoloff/trueconf_zabbix_relay_bot.git
        cd trueconf_zabbix_relay_bot

        # 2. Установка зависимостей
        pip install trueconf aiohttp

        # 3. Создание конфигурации
        cat > config.py << EOF
        TRUECONF_SERVER = "wss://your-server.trueconf.com"
        TRUECONF_TOKEN = "your-bot-token-here"
        WEB_SERVER_HOST = "0.0.0.0"
        WEB_SERVER_PORT = 8080
        HEARTBEAT_MODE = "smart"
        LOG_LEVEL = "INFO"
        ADMIN_MODE = "strict"
        ADMIN_IDS = ""
        EOF

        # 4. Запуск
        python3 bot.py

🤖 ПЕРВЫЕ ШАГИ:

    1. Напишите боту команду /start
    2. Узнайте свой ID: /whoami
    3. Добавьте себя в администраторы (в config.py ADMIN_IDS)
    4. Создайте канал: /register critical
    5. Установите канал по умолчанию: /default


3. КОМАНДЫ БОТА


👥 ПУБЛИЧНЫЕ КОМАНДЫ (доступны всем):

    ============== ==========================================
    Команда        Описание
    ============== ==========================================
    /help          Показать справку
    /start         Начало работы
    /info          Информация о боте
    /health        Проверка состояния соединения
    /ping          Проверка связи
    /whoami        Информация о пользователе
    ============== ==========================================

👑 КОМАНДЫ АДМИНИСТРАТОРА:

    =================== ======================================
    Команда             Описание
    =================== ======================================
    /register <имя>     Создать новый канал
    /unregister <имя>   Удалить канал
    /channels           Список всех каналов
    /default            Установить текущий чат как канал по умолчанию
    /admins             Список администраторов
    /admin_add <id>     Добавить администратора
    /admin_remove <id>  Удалить администратора
    =================== ======================================

📝 ПРИМЕРЫ КОМАНД:

    .. code-block:: text

        /register critical
        /register warning
        /channels
        /unregister warning
        /admin_add user123
        /admins


4. ВЕБХУКИ


📦 ФОРМАТ ЗАПРОСА:

    Бот принимает ТОЛЬКО три параметра в формате JSON или form-data:

    .. code-block:: json

        {
            "channel": "critical",     // опционально, имя канала
            "subject": "❗ Авария",     // опционально, тема сообщения
            "message": "Текст..."       // обязательно, тело сообщения
        }

    ⚠️ ВАЖНО: Бот НЕ добавляет время, ID или другую информацию - отправляет 
       только то, что получил!

🌐 ENDPOINTS:

    ===================== ======== ==================================
    URL                    Метод    Описание
    ===================== ======== ==================================
    /webhook               POST     Основной вебхук для уведомлений
    /zabbix-webhook        POST     Альтернативный (для Zabbix)
    /                      GET      Информация о боте
    /live                  GET      Проверка живости сервера
    /ready                 GET      Проверка готовности бота
    /health                GET      Подробный health check
    ===================== ======== ==================================

📤 ПРИМЕРЫ ОТПРАВКИ:

    .. code-block:: bash

        # Простой запрос
        curl -X POST http://localhost:8080/webhook \\
          -H "Content-Type: application/json" \\
          -d '{"message": "Тест"}'

        # Полный формат
        curl -X POST http://localhost:8080/webhook \\
          -H "Content-Type: application/json" \\
          -d '{
            "channel": "critical",
            "subject": "🚨 Критическая ошибка",
            "message": "Сервер базы данных недоступен"
          }'

        # Form-data
        curl -X POST http://localhost:8080/webhook \\
          -d "channel=warning" \\
          -d "subject=⚠️ Внимание" \\
          -d "message=Высокая нагрузка CPU"

    .. code-block:: python

        import requests

        response = requests.post(
            "http://localhost:8080/webhook",
            json={
                "channel": "deploy",
                "subject": "🚀 Деплой успешен",
                "message": "Версия 2.1.0 установлена"
            }
        )
        print(response.json())


5. КАНАЛЫ


📢 ЧТО ТАКОЕ КАНАЛЫ?

    Каналы - это именованные маршруты для разных типов уведомлений. 
    Каждый канал привязан к конкретному чату TrueConf.

    .. code-block:: text

        Каналы → Чаты
        ─────────────────
        critical → Чат поддержки
        warning  → Чат разработки
        info     → Общий чат
        deploy   → Чат DevOps

🔧 УПРАВЛЕНИЕ КАНАЛАМИ:

    .. code-block:: text

        /register critical     # создать канал в текущем чате
        /register warning      # создать еще один
        /channels              # посмотреть все каналы
        /unregister warning    # удалить канал
        /default               # сделать текущий чат каналом по умолчанию

🎨 АВТОМАТИЧЕСКИЕ ИКОНКИ:

    ========== ====== ========== ======
    Канал      Иконка Канал      Иконка
    ========== ====== ========== ======
    critical   🚨     database   🗄️
    warning    ⚠️     network    🌐
    info       ℹ️     cpu        ⚡
    error      ❌     memory     💾
    success    ✅     disk       💿
    alert      🔔     security   🔒
    debug      🔍     zabbix     📈
    monitor    📊     service    🎯
    deploy     🚀     backup     💽
    ========== ====== ========== ======

📋 ПРИМЕР ИСПОЛЬЗОВАНИЯ КАНАЛОВ:

    .. code-block:: json

        // Критические ошибки
        {
            "channel": "critical",
            "subject": "❗ СЕРВЕР НЕДОСТУПЕН",
            "message": "Хост: db-01\nСтатус: DOWN"
        }

        // Предупреждения
        {
            "channel": "warning",
            "subject": "⚠️ Высокая нагрузка",
            "message": "CPU: 95%\nMemory: 87%"
        }

        // Информация
        {
            "channel": "info",
            "subject": "ℹ️ Плановое обслуживание",
            "message": "Сервер будет перезагружен в 23:00"
        }


6. АДМИНИСТРИРОВАНИЕ


🔐 НАСТРОЙКА ПРАВ (config.py):

    .. code-block:: python

        # Строгий режим (только указанные администраторы) - РЕКОМЕНДУЕТСЯ
        ADMIN_MODE = "strict"
        ADMIN_IDS = "user123,user456,admin"

        # Открытый режим (все пользователи - администраторы) - ТОЛЬКО ДЛЯ ТЕСТА!
        ADMIN_MODE = "open"
        ADMIN_IDS = ""

👑 УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ:

    .. code-block:: text

        /whoami                    # узнать свой ID
        /admin_add user123         # добавить администратора
        /admin_remove user123      # удалить администратора
        /admins                    # список администраторов

    ⚠️ ВАЖНО: Нельзя удалить самого себя из администраторов!

🛡️ РЕКОМЕНДАЦИИ ПО БЕЗОПАСНОСТИ:

    1. Всегда используйте strict режим в production
    2. Регулярно проверяйте список администраторов
    3. Ограничьте доступ к вебхуку (firewall, VPN)
    4. Используйте HTTPS для вебхуков (reverse proxy)
    5. Не используйте open режим вне тестовой среды


7. ПРИМЕРЫ


📌 ПРИМЕР 1: Простое уведомление

    .. code-block:: json

        {"message": "Тестовое уведомление"}

    Результат в чате:
        📢 Тестовое уведомление

📌 ПРИМЕР 2: С темой

    .. code-block:: json

        {
            "subject": "Плановое обслуживание",
            "message": "Сервер будет перезагружен через 5 минут"
        }

    Результат в чате:
        📌 Плановое обслуживание
        Сервер будет перезагружен через 5 минут

📌 ПРИМЕР 3: Критическое уведомление

    .. code-block:: json

        {
            "channel": "critical",
            "subject": "❗ АВАРИЯ",
            "message": "Отказ основного сервера БД"
        }

    Результат в чате:
        🚨 ❗ АВАРИЯ
        Отказ основного сервера БД

📌 ПРИМЕР 4: Мониторинг нагрузки

    .. code-block:: json

        {
            "channel": "warning",
            "subject": "⚠️ Высокая нагрузка",
            "message": "CPU: 95%\nMemory: 87%\nDisk: 92%"
        }

    Результат в чате:
        ⚠️ ⚠️ Высокая нагрузка
        CPU: 95%
        Memory: 87%
        Disk: 92%

📌 ПРИМЕР 5: Интеграция с Zabbix

    В настройках медиатипа Zabbix:

    .. code-block:: text

        URL: http://bot-server:8080/webhook
        Method: POST
        Content-Type: application/json
        Body:
        {
            "channel": "{TRIGGER.SEVERITY}",
            "subject": "{TRIGGER.NAME}",
            "message": "{TRIGGER.NAME}\\nХост: {HOST.NAME}\\nЗначение: {ITEM.VALUE}"
        }


8. КОНФИГУРАЦИЯ


⚙️ ПАРАМЕТРЫ КОНФИГУРАЦИИ (config.py):

    .. code-block:: python

        # =========================================================================
        # ОСНОВНЫЕ НАСТРОЙКИ TRUECONF
        # =========================================================================
        
        TRUECONF_SERVER = "wss://your-server.trueconf.com"  # WebSocket URL
        TRUECONF_TOKEN = "your-bot-token-here"              # Токен бота

        # =========================================================================
        # НАСТРОЙКИ ВЕБ-СЕРВЕРА
        # =========================================================================
        
        WEB_SERVER_HOST = "0.0.0.0"      # Хост (0.0.0.0 - все интерфейсы)
        WEB_SERVER_PORT = 8080            # Порт для вебхуков

        # =========================================================================
        # НАСТРОЙКИ HEARTBEAT
        # =========================================================================
        
        HEARTBEAT_MODE = "smart"          # smart, strict, off
        HEARTBEAT_INTERVAL = 30           # Интервал проверки (сек)

        # =========================================================================
        # НАСТРОЙКИ ЛОГИРОВАНИЯ
        # =========================================================================
        
        LOG_LEVEL = "INFO"                 # DEBUG, INFO, WARNING, ERROR
        WEBSOCKET_DEBUG = False            # Детальное логирование WebSocket

        # =========================================================================
        # НАСТРОЙКИ АДМИНИСТРИРОВАНИЯ
        # =========================================================================
        
        ADMIN_IDS = ""                      # ID через запятую: "user1,user2"
        ADMIN_MODE = "strict"                # strict, open, whitelist

📊 РЕЖИМЫ HEARTBEAT:

    ======== ==========================================
    Режим    Описание
    ======== ==========================================
    off      Heartbeat отключен
    smart    Умный режим (адаптивная проверка)
    strict   Строгий режим (постоянная проверка)
    ======== ==========================================

🔐 РЕЖИМЫ АДМИНИСТРИРОВАНИЯ:

    ========== ==========================================
    Режим      Описание
    ========== ==========================================
    strict     Только указанные в ADMIN_IDS
    open       Все пользователи - администраторы
    whitelist  То же что strict
    ========== ==========================================


9. УСТРАНЕНИЕ ПРОБЛЕМ


🔍 БОТ НЕ ОТВЕЧАЕТ:

    .. code-block:: bash

        # Проверьте логи
        tail -f logs/bot.log

        # Проверьте процесс
        ps aux | grep bot.py

        # Проверьте порт
        netstat -tlnp | grep 8080

        # Проверьте соединение с TrueConf
        curl -I wss://your-server.trueconf.com

🔍 ВЕБХУКИ НЕ ДОХОДЯТ:

    .. code-block:: bash

        # Проверьте доступность бота
        curl http://localhost:8080/health

        # Проверьте, существует ли канал
        curl http://localhost:8080/channels

        # Проверьте формат запроса
        curl -X POST http://localhost:8080/webhook \\
          -H "Content-Type: application/json" \\
          -d '{"message": "test"}'

🔍 WEBSOCKET ОТВАЛИВАЕТСЯ:

    .. code-block:: python

        # В config.py включите строгий heartbeat
        HEARTBEAT_MODE = "strict"
        HEARTBEAT_INTERVAL = 15

🔍 НЕ СОХРАНЯЕТСЯ КАНАЛ ПО УМОЛЧАНИЮ:

    .. code-block:: python

        # Временно: добавьте в config.py
        # DEFAULT_CHAT = "id_чата"

        # Или используйте команду /default и проверьте файл:
        cat bot_state.json | grep default_chat

🔍 ОШИБКИ В ЛОГАХ:

    ===================================== ==================================
    Ошибка                               Решение
    ===================================== ==================================
    "Connection refused"                  Проверьте TrueConf Server
    "Invalid token"                       Проверьте TRUECONF_TOKEN
    "Channel not found"                   Создайте канал /register
    "Missing required field: message"     Добавьте message в вебхук
    "Access denied"                       Проверьте права администратора
    ===================================== ==================================


10. API REFERENCE


📚 КЛАССЫ:

    .. class:: StateManager(file_path="bot_state.json")
        
        Менеджер состояния бота.
        
        :param file_path: путь к файлу состояния
        :type file_path: str
        
        .. method:: add_channel(name, chat_id, created_by=None)
            
            Добавить новый канал.
            
            :param name: имя канала
            :param chat_id: ID чата
            :param created_by: ID создателя
            :type name: str
            :type chat_id: str
            :type created_by: str, optional

        .. method:: remove_channel(name)
            
            Удалить канал.
            
            :param name: имя канала
            :type name: str
            :returns: True если успешно
            :rtype: bool

        .. method:: get_channel_chat_id(name)
            
            Получить ID чата по имени канала.
            
            :param name: имя канала
            :type name: str
            :returns: ID чата или None
            :rtype: str, optional

    .. class:: AdminManager()
        
        Менеджер администраторов.
        
        .. method:: is_admin(user_id)
            
            Проверить, является ли пользователь администратором.
            
            :param user_id: ID пользователя
            :type user_id: str
            :returns: True если администратор
            :rtype: bool

        .. method:: add_admin(user_id)
            
            Добавить администратора.
            
            :param user_id: ID пользователя
            :type user_id: str
            :returns: True если добавлен
            :rtype: bool

    .. class:: BotKeepAlive(bot)
        
        Heartbeat для контроля соединения.
        
        :param bot: экземпляр бота
        :type bot: Bot
        
        .. method:: get_stats()
            
            Получить статистику heartbeat.
            
            :returns: словарь со статистикой
            :rtype: dict

📡 WEBHOOK HANDLER:

    .. function:: handle_webhook(request)
        
        Обработчик вебхуков.
        
        :param request: HTTP запрос
        :type request: aiohttp.web.Request
        :returns: HTTP ответ
        :rtype: aiohttp.web.Response
        
        **Формат запроса:**
        
        .. code-block:: json
        
            {
                "channel": "имя_канала",    // опционально
                "subject": "тема",           // опционально
                "message": "текст"           // обязательно
            }
        
        **Коды ответа:**
        
        * 200 - успешно отправлено
        * 400 - ошибка в запросе (нет message)
        * 404 - канал не найден
        * 500 - внутренняя ошибка

🤖 COMMAND HANDLERS:

    .. function:: cmd_help(msg, args)
        
        Показать справку.
        
        :param msg: сообщение
        :param args: аргументы команды
        :type msg: Message
        :type args: list

    .. function:: cmd_register(msg, args)
        
        Зарегистрировать канал.
        
        :param msg: сообщение
        :param args: аргументы команды ['/register', 'имя']
        :type msg: Message
        :type args: list

    .. function:: cmd_default(msg, args)
        
        Установить чат по умолчанию.
        
        :param msg: сообщение
        :param args: аргументы команды
        :type msg: Message
        :type args: list

📁 ФАЙЛЫ:

    ===================== ================================================
    Файл                   Назначение
    ===================== ================================================
    bot.py                Основной исполняемый файл
    config.py             Конфигурационный файл
    logs/bot.log          Файл логов (ротация 50MB, 10 файлов)
    bot_state.json        Состояние бота (каналы, настройки)
    ===================== ================================================


ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ


📞 ПОДДЕРЖКА:

    При возникновении проблем:
    
    1. Проверьте логи: ``tail -f logs/bot.log``
    2. Увеличьте уровень логирования: ``LOG_LEVEL = "DEBUG"``
    3. Сохраните вывод ошибок
    4. Создайте issue с:
        * Версией бота (/info)
        * Конфигурацией (без токена)
        * Логами с ошибкой
        * Примером запроса

📄 ЛИЦЕНЗИЯ:

        MIT License

        Copyright (c) 2026 cokoloff

        Permission is hereby granted, free of charge, to any person obtaining a copy
        of this software and associated documentation files (the "Software"), to deal
        in the Software without restriction, including without limitation the rights
        to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
        copies of the Software, and to permit persons to whom the Software is
        furnished to do so, subject to the following conditions:

        The above copyright notice and this permission notice shall be included in all
        copies or substantial portions of the Software.

        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
        IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
        FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
        AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
        LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
        OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
        SOFTWARE.

📌 ВЕРСИЯ:

    Текущая версия: 10.0
    Последнее обновление: 2026
    Статус: Production Ready
