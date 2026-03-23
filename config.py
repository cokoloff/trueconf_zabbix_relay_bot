# config.py
# Универсальная конфигурация для работы на сервере и в контейнере
import os
import sys
from pathlib import Path

def load_config():
    """
    Загрузка конфигурации в порядке приоритета:
    1. Переменные окружения (ENV)
    2. Файл config.py (если есть)
    3. Значения по умолчанию
    """
    
    # Базовые значения по умолчанию
    defaults = {
        # TrueConf настройки
        'TRUECONF_SERVER': 'vcs.your-domain.ru',
        'TRUECONF_TOKEN_URL': 'https://vcs.your-domain.ru/bridge/api/client/v1/oauth/token',
        'TRUECONF_CLIENT_ID': 'chat_bot',
        'TRUECONF_USERNAME': 'your_username_here',
        'TRUECONF_PASSWORD': '',
        'TOKEN_FILE': 'bot_token.json',
        
        # Веб-сервер
        'WEB_SERVER_HOST': '0.0.0.0',
        'WEB_SERVER_PORT': 8080,
        
        # Логирование
        'LOG_LEVEL': 'INFO',
        'WEBSOCKET_DEBUG': False,
        
        # Heartbeat
        'HEARTBEAT_MODE': 'smart',
        'HEARTBEAT_INTERVAL': 30,
        
        # Администрирование
        'ADMIN_MODE': 'strict',
        'ADMIN_IDS': [],
    }
    
    # Пытаемся загрузить из файла config.local.py (если есть)
    local_config = {}
    config_file = Path(__file__).parent / 'config.local.py'
    if config_file.exists():
        try:
            # Выполняем файл как модуль
            import importlib.util
            spec = importlib.util.spec_from_file_location("local_config", config_file)
            local_config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(local_config_module)
            
            # Забираем все переменные в верхнем регистре
            for key, value in local_config_module.__dict__.items():
                if key.isupper():
                    local_config[key] = value
            print(f"✅ Загружена конфигурация из {config_file}")
        except Exception as e:
            print(f"⚠️ Ошибка загрузки {config_file}: {e}")
    
    # Формируем финальную конфигурацию
    config = {}
    for key, default_value in defaults.items():
        # 1. Проверяем ENV
        env_value = os.getenv(key)
        if env_value is not None:
            # Преобразуем типы
            if isinstance(default_value, bool):
                value = env_value.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(default_value, int):
                value = int(env_value)
            elif isinstance(default_value, list):
                value = [v.strip() for v in env_value.split(',') if v.strip()]
            else:
                value = env_value
            config[key] = value
            continue
        
        # 2. Проверяем local_config
        if key in local_config:
            config[key] = local_config[key]
            continue
        
        # 3. Используем значение по умолчанию
        config[key] = default_value
    
    return config

# Загружаем конфигурацию
_config = load_config()

# Экспортируем переменные для удобного импорта
TRUECONF_SERVER = _config['TRUECONF_SERVER']
TRUECONF_TOKEN_URL = _config['TRUECONF_TOKEN_URL']
TRUECONF_CLIENT_ID = _config['TRUECONF_CLIENT_ID']
TRUECONF_USERNAME = _config['TRUECONF_USERNAME']
TRUECONF_PASSWORD = _config['TRUECONF_PASSWORD']
TOKEN_FILE = _config['TOKEN_FILE']
WEB_SERVER_HOST = _config['WEB_SERVER_HOST']
WEB_SERVER_PORT = _config['WEB_SERVER_PORT']
LOG_LEVEL = _config['LOG_LEVEL']
WEBSOCKET_DEBUG = _config['WEBSOCKET_DEBUG']
HEARTBEAT_MODE = _config['HEARTBEAT_MODE']
HEARTBEAT_INTERVAL = _config['HEARTBEAT_INTERVAL']
ADMIN_MODE = _config['ADMIN_MODE']
ADMIN_IDS = _config['ADMIN_IDS']

# Вывод информации о загрузке
print("=" * 60)
print("🚀 TrueConf Zabbix Bot - Загрузка конфигурации")
print("=" * 60)
print(f"📁 Источники:")
if os.getenv('TRUECONF_SERVER'):
    print(f"   🌐 ENV переменные: активны")
if Path(__file__).parent / 'config.local.py':
    print(f"   📄 config.local.py: {'найден' if (Path(__file__).parent / 'config.local.py').exists() else 'не найден'}")
print(f"   ⚙️  Значения по умолчанию: активны")
print("-" * 60)
print(f"🌐 Сервер: {TRUECONF_SERVER}")
print(f"🔐 Режим администрирования: {ADMIN_MODE}")
print(f"👑 Администраторы: {len(ADMIN_IDS)}")
print(f"📋 Уровень логирования: {LOG_LEVEL}")
print("=" * 60)