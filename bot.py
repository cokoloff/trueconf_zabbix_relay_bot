#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import json
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps, lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple, Callable, Set
from collections import deque

import aiohttp
from aiohttp import web
from trueconf import Bot, Dispatcher, Router, Message, ParseMode
import config

# ============================================================================
# КОНСТАНТЫ И НАСТРОЙКИ
# ============================================================================

VERSION = "10.1"

# Кэшируем настройки
_CONFIG_CACHE = {
    'LOG_LEVEL': getattr(config, 'LOG_LEVEL', 'INFO'),
    'WEBSOCKET_DEBUG': getattr(config, 'WEBSOCKET_DEBUG', False),
    'HEARTBEAT_MODE': getattr(config, 'HEARTBEAT_MODE', 'smart'),
    'ADMIN_IDS': getattr(config, 'ADMIN_IDS', '').split(',') if getattr(config, 'ADMIN_IDS', '') else [],
    'ADMIN_MODE': getattr(config, 'ADMIN_MODE', 'strict')
}

# Настройки для получения токена
TOKEN_CONFIG = {
    'token_url': getattr(config, 'TRUECONF_TOKEN_URL', 'https://vcs.your-domain.ru/bridge/api/client/v1/oauth/token'),
    'client_id': getattr(config, 'TRUECONF_CLIENT_ID', 'chat_bot'),
    'username': getattr(config, 'TRUECONF_USERNAME', 'your-bot-usernam'),
    'password': getattr(config, 'TRUECONF_PASSWORD', 'your-bot-password'),
    'server': getattr(config, 'TRUECONF_SERVER', 'vcs.your-domain.ru'),
    'token_file': getattr(config, 'TOKEN_FILE', 'bot_token.json')
}

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ ГЛОБАЛЬНЫХ ОБЪЕКТОВ
# ============================================================================

router = Router()
dp = Dispatcher()
dp.include_router(router)

# Глобальные переменные
bot = None
bot_keepalive = None
state_manager = None
admin_manager = None
token_manager = None
start_time = None
bot_task = None
web_runner = None
bot_ready = False
is_shutting_down = False

# ============================================================================
# УТИЛИТЫ
# ============================================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

class ContextLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self._context = {}
    
    def set_context(self, **kwargs):
        self._context.update(kwargs)
        return self
    
    def _log(self, level, msg, *args, **kwargs):
        if self._context:
            context_str = ' '.join(f'[{k}={v}]' for k, v in self._context.items())
            msg = f"{context_str} {msg}"
        self.logger.log(level, msg, *args, **kwargs)
    
    def debug(self, msg, *args, **kwargs): 
        self._log(logging.DEBUG, msg, *args, **kwargs)
    
    def info(self, msg, *args, **kwargs): 
        self._log(logging.INFO, msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs): 
        self._log(logging.WARNING, msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs): 
        self._log(logging.ERROR, msg, *args, **kwargs)
    
    def critical(self, msg, *args, **kwargs): 
        self._log(logging.CRITICAL, msg, *args, **kwargs)

def setup_logging() -> ContextLogger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_format = '%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(log_format, date_format)
    
    log_level = getattr(logging, _CONFIG_CACHE['LOG_LEVEL'])
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    
    file_handler = RotatingFileHandler(
        filename=log_dir / 'bot.log',
        maxBytes=50 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    websockets_logger = logging.getLogger('websockets.client')
    websockets_logger.setLevel(logging.WARNING if not _CONFIG_CACHE['WEBSOCKET_DEBUG'] else logging.DEBUG)
    
    return ContextLogger('bot')

logger = setup_logging()

# ============================================================================
# МЕНЕДЖЕР ТОКЕНОВ (ИСПРАВЛЕННАЯ ВЕРСИЯ)
# ============================================================================

class TokenManager:
    """Управление получением и обновлением токена"""
    
    def __init__(self):
        self.token = None
        self.expires_at = None
        self.token_file = Path(TOKEN_CONFIG['token_file'])
        self._lock = asyncio.Lock()
        self._refresh_task = None
        
        # Загружаем сохраненный токен
        self._load_token()
    
    def _load_token(self):
        """Загружает токен из файла"""
        try:
            if self.token_file.exists():
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    self.token = data.get('token')
                    expires_at_str = data.get('expires_at')
                    if expires_at_str:
                        self.expires_at = datetime.fromisoformat(expires_at_str)
                    
                    if self.token and self.expires_at:
                        remaining = (self.expires_at - datetime.now()).total_seconds()
                        if remaining > 3600:
                            logger.info(f"✅ Загружен токен из файла (действителен {remaining/3600:.1f} ч)")
                            return
                        else:
                            logger.info(f"⚠️ Токен истекает через {remaining/60:.0f} мин")
            else:
                logger.info("📁 Файл с токеном не найден")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка загрузки токена: {e}")
        
        self.token = None
        self.expires_at = None
    
    def _save_token(self):
        """Сохраняет токен в файл"""
        try:
            data = {
                'token': self.token,
                'expires_at': self.expires_at.isoformat() if self.expires_at else None,
                'updated_at': datetime.now().isoformat()
            }
            with open(self.token_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug("💾 Токен сохранен в файл")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения токена: {e}")
    
    def is_token_valid(self) -> bool:
        """Проверяет, действителен ли токен"""
        if not self.token or not self.expires_at:
            return False
        
        # Считаем токен действительным, если до истечения > 5 минут
        remaining = (self.expires_at - datetime.now()).total_seconds()
        return remaining > 300  # 5 минут
    
    async def get_token(self, force_refresh: bool = False) -> Optional[str]:
        """Получает токен, обновляя если нужно"""
        async with self._lock:
            # Если не принудительное обновление и токен действителен - возвращаем
            if not force_refresh and self.is_token_valid():
                return self.token
            
            # Получаем новый токен
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "client_id": TOKEN_CONFIG['client_id'],
                        "grant_type": "password",
                        "username": TOKEN_CONFIG['username'],
                        "password": TOKEN_CONFIG['password']
                    }
                    
                    logger.info(f"🔑 Запрос токена для {TOKEN_CONFIG['username']}...")
                    
                    async with session.post(
                        TOKEN_CONFIG['token_url'],
                        json=payload,
                        headers={'Content-Type': 'application/json'}
                    ) as response:
                        if response.status in (200, 201):
                            data = await response.json()
                            self.token = data.get('access_token')
                            
                            # Получаем expires_at
                            expires_at_value = data.get('expires_at')
                            if expires_at_value:
                                if isinstance(expires_at_value, (int, float)):
                                    self.expires_at = datetime.fromtimestamp(expires_at_value)
                                else:
                                    try:
                                        self.expires_at = datetime.fromisoformat(expires_at_value)
                                    except:
                                        self.expires_at = datetime.now() + timedelta(days=30)
                            else:
                                self.expires_at = datetime.now() + timedelta(days=30)
                            
                            self._save_token()
                            
                            expires_days = (self.expires_at - datetime.now()).total_seconds() / 86400
                            logger.info(f"✅ Токен получен (действителен {expires_days:.0f} дней)")
                            return self.token
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ Ошибка получения токена: {response.status} - {error_text[:200]}")
                            return None
                            
            except Exception as e:
                logger.error(f"❌ Ошибка запроса токена: {e}")
                return None
    
    def start_auto_refresh(self):
        """Запускает фоновую проверку токена (только для логирования)"""
        async def monitor_loop():
            while True:
                try:
                    await asyncio.sleep(3600)  # Проверяем раз в час
                    
                    if not self.is_token_valid():
                        logger.warning("⚠️ Токен истекает или недействителен, обновляем...")
                        await self.get_token(force_refresh=True)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка мониторинга токена: {e}")
        
        self._refresh_task = asyncio.create_task(monitor_loop())
        logger.info("🔄 Запущен мониторинг токена (проверка раз в час)")
    
    async def stop(self):
        """Останавливает мониторинг"""
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except:
                pass

# ============================================================================
# СИСТЕМА АДМИНИСТРИРОВАНИЯ
# ============================================================================

class AdminManager:
    def __init__(self):
        self.admin_ids = set(_CONFIG_CACHE['ADMIN_IDS'])
        self.mode = _CONFIG_CACHE['ADMIN_MODE']
        self.public_commands = {'/help', '/start', '/info', '/health', '/ping', '/whoami'}
        self._cache = {}
        
        logger.info(f"🔐 Режим администрирования: {self.mode}")
        logger.info(f"🔐 Администраторы ({len(self.admin_ids)}): {', '.join(self.admin_ids) if self.admin_ids else 'не заданы'}")
    
    def is_admin(self, user_id: str) -> bool:
        if not user_id:
            return False
        if user_id in self._cache:
            return self._cache[user_id]
        
        result = False
        if self.mode == 'open':
            result = True
        elif self.mode == 'strict' or self.mode == 'whitelist':
            result = user_id in self.admin_ids
        
        self._cache[user_id] = result
        return result
    
    def can_execute_command(self, user_id: str, command: str) -> Tuple[bool, str]:
        if not user_id:
            return False, "Неизвестный пользователь"
        
        if command in self.public_commands:
            return True, "OK"
        
        if self.is_admin(user_id):
            return True, "OK"
        
        return False, "Доступ запрещен"
    
    def add_admin(self, user_id: str) -> bool:
        if user_id in self.admin_ids:
            return False
        self.admin_ids.add(user_id)
        self._cache.pop(user_id, None)
        logger.info(f"🔐 Добавлен администратор: {user_id}")
        return True
    
    def remove_admin(self, user_id: str) -> bool:
        if user_id not in self.admin_ids:
            return False
        self.admin_ids.remove(user_id)
        self._cache.pop(user_id, None)
        logger.info(f"🔐 Удален администратор: {user_id}")
        return True
    
    def get_admins(self) -> List[str]:
        return list(self.admin_ids)

# ============================================================================
# ПРОСТОЙ МЕНЕДЖЕР СОСТОЯНИЯ
# ============================================================================

class StateManager:
    def __init__(self, file_path: str = "bot_state.json"):
        self.file_path = Path(file_path)
        self.lock = asyncio.Lock()
        self._state = None
        self._dirty = False
        
        self._state = self._load()
        self._start_auto_save()
    
    def _load(self) -> dict:
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки: {e}")
        return self._create_default()
    
    def _create_default(self) -> dict:
        return {
            'version': VERSION,
            'notification_channels': {},
            'default_chat': None,
            'metadata': {
                'messages_sent': 0,
                'started_at': utc_now_iso()
            }
        }
    
    def _start_auto_save(self):
        async def auto_save():
            while True:
                await asyncio.sleep(60)
                if self._dirty:
                    await self.save()
                    self._dirty = False
        asyncio.create_task(auto_save())
    
    async def save(self) -> bool:
        async with self.lock:
            try:
                temp_path = self.file_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(self._state, f, ensure_ascii=False)
                temp_path.replace(self.file_path)
                self._dirty = False
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения: {e}")
                return False
    
    @property
    def notification_channels(self) -> dict:
        return self._state['notification_channels']
    
    @property
    def default_chat(self) -> Optional[str]:
        return self._state.get('default_chat')
    
    @default_chat.setter
    def default_chat(self, value: Optional[str]):
        self._state['default_chat'] = value
        self._dirty = True
    
    async def add_channel(self, name: str, chat_id: str, created_by: str = None):
        async with self.lock:
            self._state['notification_channels'][name] = {
                'chat_id': chat_id,
                'created_at': utc_now_iso(),
                'created_by': created_by
            }
            self._dirty = True
            logger.info(f"📢 Канал '{name}' создан")
    
    async def remove_channel(self, name: str) -> bool:
        async with self.lock:
            if name in self._state['notification_channels']:
                del self._state['notification_channels'][name]
                self._dirty = True
                logger.info(f"🗑️ Канал '{name}' удален")
                return True
        return False
    
    def get_channel_chat_id(self, name: str) -> Optional[str]:
        channel = self._state['notification_channels'].get(name)
        return channel.get('chat_id') if channel else None
    
    async def increment_messages_sent(self):
        async with self.lock:
            self._state['metadata']['messages_sent'] = \
                self._state['metadata'].get('messages_sent', 0) + 1
            self._dirty = True

# ============================================================================
# ПРОСТОЙ HEARTBEAT
# ============================================================================

class HeartbeatMode(Enum):
    OFF = "off"
    SMART = "smart"
    STRICT = "strict"

class BotKeepAlive:
    def __init__(self, bot):
        self.bot = bot
        mode_value = _CONFIG_CACHE['HEARTBEAT_MODE']
        
        if isinstance(mode_value, bool):
            self.mode = HeartbeatMode.OFF if not mode_value else HeartbeatMode.SMART
        else:
            try:
                self.mode = HeartbeatMode(mode_value)
            except ValueError:
                self.mode = HeartbeatMode.SMART
        
        self.check_interval = getattr(config, 'HEARTBEAT_INTERVAL', 30)
        self.failures = 0
        self.max_failures = 3
        self.reconnects = 0
        self.checks = 0
        self._task = None
        self._reconnect_lock = asyncio.Lock()
        self._is_connected = False
        self._is_authenticated = False
        self._last_activity = datetime.now()
    
    async def start(self):
        if self.mode == HeartbeatMode.OFF:
            logger.info("💓 Heartbeat отключен")
            return
        self._task = asyncio.create_task(self._run())
        logger.info(f"💓 Heartbeat запущен (mode={self.mode.value})")
    
    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except:
                pass
    
    async def _run(self):
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                self.checks += 1
                
                ws = getattr(self.bot, '_websocket', None)
                is_alive = ws is not None and not ws.closed
                
                if is_alive:
                    self.failures = 0
                    self._is_connected = True
                else:
                    self.failures += 1
                    self._is_connected = False
                    
                    if self.failures >= self.max_failures:
                        logger.warning(f"🔄 Heartbeat: переподключение")
                        asyncio.create_task(self._reconnect())
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Heartbeat ошибка: {e}")
    
    async def _reconnect(self):
        async with self._reconnect_lock:
            self.reconnects += 1
            logger.info(f"🔄 Переподключение #{self.reconnects}...")
            await asyncio.sleep(2)
    
    def set_authenticated(self):
        self._is_authenticated = True
        self._is_connected = True
        self._last_activity = datetime.now()
    
    def update_activity(self):
        """Обновление времени последней активности"""
        self._last_activity = datetime.now()
    
    def get_stats(self) -> dict:
        idle_time = (datetime.now() - self._last_activity).total_seconds()
        
        return {
            'connected': self._is_connected,
            'authenticated': self._is_authenticated,
            'checks': self.checks,
            'failures': self.failures,
            'reconnects': self.reconnects,
            'idle_seconds': int(idle_time)
        }

# ============================================================================
# СОЗДАНИЕ БОТА С ТОКЕНОМ
# ============================================================================

async def create_bot_with_token():
    """Создает бота, получая токен через API"""
    global token_manager
    
    token = await token_manager.get_token()
    if not token:
        logger.error("❌ Не удалось получить токен")
        return None
    
    try:
        bot = Bot(
            server=TOKEN_CONFIG['server'],
            token=token,
            dispatcher=dp
        )
        
        # Патчим бота
        original_send = bot.send_message
        
        async def patched_send(*args, **kwargs):
            try:
                return await original_send(*args, **kwargs)
            except Exception as e:
                if 'token' in str(e).lower() or 'unauthorized' in str(e).lower():
                    logger.warning("⚠️ Ошибка авторизации, обновляем токен...")
                    new_token = await token_manager.get_token(force_refresh=True)
                    if new_token:
                        # Обновляем токен в боте
                        bot._token = new_token
                        return await original_send(*args, **kwargs)
                raise
        
        bot.send_message = patched_send
        return bot
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания бота: {e}")
        return None

# ============================================================================
# ИКОНКИ ДЛЯ КАНАЛОВ
# ============================================================================

@lru_cache(maxsize=20)
def get_channel_icon(channel: str) -> str:
    if not channel:
        return ''
    
    icons = {
        'default': '📌', 'critical': '🚨', 'warning': '⚠️',
        'info': 'ℹ️', 'database': '🗄️', 'network': '🌐',
        '1c': '📦', 'cpu': '⚡', 'memory': '💾',
        'disk': '💿', 'security': '🔒', 'app': '📱',
        'monitoring': '📊', 'alerts': '🔔', 'zabbix': '📈',
        'service': '🎯', 'sla': '📊'
    }
    return icons.get(channel.lower(), '📢')

# ============================================================================
# ОТПРАВКА УВЕДОМЛЕНИЙ
# ============================================================================

async def send_notification(chat_id: str, subject: str, message: str, channel: str = None) -> bool:
    """Отправка уведомления - только subject и message, БЕЗ добавления времени и ID"""
    
    if not chat_id or not message:
        return False
    
    # Добавляем только иконку канала если есть
    channel_icon = get_channel_icon(channel) if channel else ''
    channel_prefix = f"{channel_icon} " if channel_icon else ''
    
    # Формируем сообщение
    if subject:
        final_message = f"{channel_prefix}{subject}\n{message}"
    else:
        final_message = f"{channel_prefix}{message}"
    
    try:
        result = await bot.send_message(
            chat_id=chat_id,
            text=final_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if result:
            logger.info(f"✅ Отправлено в канал {channel or 'default'}")
            await state_manager.increment_messages_sent()
            return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
    
    return False

# ============================================================================
# ВЕБХУК ОБРАБОТЧИК
# ============================================================================

async def handle_webhook(request):
    """Принимает только channel, subject, message - ничего не добавляет"""
    
    try:
        # Получаем данные
        if request.content_type == 'application/json':
            data = await request.json()
        else:
            data = dict(await request.post())
        
        logger.info(f"📩 Получен вебхук: {json.dumps(data, ensure_ascii=False)}")
        
        # Извлекаем параметры
        channel = data.get('channel') or data.get('Channel') or data.get('CHANNEL')
        subject = data.get('subject') or data.get('Subject') or data.get('SUBJECT') or data.get('trigger') or ''
        message = data.get('message') or data.get('Message') or data.get('MESSAGE')
        
        if not message:
            return web.json_response({"error": "Missing required field: message"}, status=400)
        
        # Определяем целевой чат
        target_chat_id = None
        
        if channel:
            target_chat_id = state_manager.get_channel_chat_id(channel)
            if not target_chat_id:
                logger.warning(f"⚠️ Канал '{channel}' не найден")
                return web.json_response({"error": f"Channel '{channel}' not found"}, status=404)
        elif state_manager.default_chat:
            target_chat_id = state_manager.default_chat
            channel = "default"
        else:
            return web.json_response({"error": "No target channel"}, status=400)
        
        # Отправляем уведомление
        success = await send_notification(
            chat_id=target_chat_id,
            subject=subject,
            message=message,
            channel=channel
        )
        
        return web.json_response({
            "status": "ok" if success else "error",
            "channel": channel
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка вебхука: {e}")
        logger.error(traceback.format_exc())
        return web.json_response({"error": str(e)}, status=500)

# ============================================================================
# КОМАНДЫ БОТА
# ============================================================================

def admin_required(func):
    @wraps(func)
    async def wrapper(msg, args):
        author_id = getattr(msg.author, 'id', None) if hasattr(msg, 'author') else None
        command = args[0] if args else ''
        
        if not author_id:
            await msg.answer("❌ Не удалось определить пользователя")
            return
        
        allowed, reason = admin_manager.can_execute_command(author_id, command)
        
        if not allowed:
            logger.warning(f"🚫 Несанкционированная команда {command} от {author_id}")
            await msg.answer(f"🚫 **Доступ запрещен**\n\n{reason}", parse_mode=ParseMode.MARKDOWN)
            return
        
        return await func(msg, args)
    return wrapper

async def cmd_help(msg, args):
    author_id = getattr(msg.author, 'id', None) if hasattr(msg, 'author') else 'unknown'
    
    text = f"👋 **TrueConf Zabbix Bot v{VERSION}**\n\n"
    text += f"**Ваш ID:** `{author_id}`\n"
    text += f"**Статус:** {'Администратор' if admin_manager.is_admin(author_id) else 'Пользователь'}\n\n"
    
    text += "**Публичные команды:**\n"
    text += "• `/help` - эта справка\n"
    text += "• `/info` - информация\n"
    text += "• `/health` - состояние\n"
    text += "• `/ping` - проверка связи\n"
    text += "• `/whoami` - информация о себе\n\n"
    
    if admin_manager.is_admin(author_id):
        text += "**🔐 Команды администратора:**\n"
        text += "• `/register имя` - создать канал\n"
        text += "• `/unregister имя` - удалить канал\n"
        text += "• `/channels` - список каналов\n"
        text += "• `/default` - чат по умолчанию\n"
        text += "• `/admins` - список администраторов\n"
        text += "• `/admin_add <id>` - добавить админа\n"
        text += "• `/admin_remove <id>` - удалить админа\n"
        text += "• `/token_info` - информация о токене\n\n"
        
        text += "**📝 Формат вебхука:**\n"
        text += "Бот принимает три параметра:\n"
        text += "• `channel` - имя канала (опционально)\n"
        text += "• `subject` - тема сообщения (опционально)\n"
        text += "• `message` - текст сообщения (обязательно)\n\n"
        
        text += "**⚠️ Важно:**\n"
        text += "Бот НЕ добавляет время и ID события - отправляет только то, что получил"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_whoami(msg, args):
    author_id = getattr(msg.author, 'id', None) if hasattr(msg, 'author') else 'unknown'
    chat_id = getattr(msg, 'chat_id', 'unknown')
    
    text = f"**👤 Информация о пользователе**\n\n"
    text += f"**ID пользователя:** `{author_id}`\n"
    text += f"**ID чата:** `{chat_id[:8]}...`\n"
    text += f"**Статус:** {'👑 Администратор' if admin_manager.is_admin(author_id) else '👤 Пользователь'}"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_info(msg, args):
    uptime = datetime.now() - start_time
    metadata = state_manager._state['metadata']
    
    # Информация о токене
    token_status = "✅ Активен" if token_manager.token else "❌ Не получен"
    if token_manager.token and token_manager.expires_at:
        remaining = (token_manager.expires_at - datetime.now()).total_seconds()
        if remaining > 0:
            token_status = f"✅ Действителен {remaining/86400:.0f} дней"
        else:
            token_status = "⚠️ Истек"
    
    text = f"**🤖 TrueConf Zabbix Bot v{VERSION}**\n\n"
    text += f"**Статус:** {'✅ Активен' if bot_ready else '⚠️ Неактивен'}\n"
    text += f"**⏱️ Uptime:** {str(uptime).split('.')[0]}\n"
    text += f"**🌐 Сервер:** {TOKEN_CONFIG['server']}\n\n"
    
    text += f"**🔑 Токен:** {token_status}\n"
    if token_manager.expires_at:
        expires_in = (token_manager.expires_at - datetime.now()).total_seconds()
        text += f"**📅 Истекает:** {token_manager.expires_at.strftime('%Y-%m-%d %H:%M:%S')} (через {expires_in/86400:.0f} дн)\n\n"
    
    text += f"**📊 Статистика:**\n"
    text += f"• Каналов: {len(state_manager.notification_channels)}\n"
    text += f"• Отправлено: {metadata.get('messages_sent', 0)}\n\n"
    
    text += f"**💓 Heartbeat:** {_CONFIG_CACHE['HEARTBEAT_MODE']}\n"
    text += f"**📋 Логи:** {_CONFIG_CACHE['LOG_LEVEL']}\n"
    text += f"**🔐 Режим доступа:** {admin_manager.mode}\n\n"
    
    text += "**📝 Режим работы:**\n"
    text += "Бот отправляет ТОЛЬКО то, что получил - без добавления времени и ID"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_token_info(msg, args):
    """Информация о токене"""
    if not admin_manager.is_admin(getattr(msg.author, 'id', None)):
        await msg.answer("🚫 Доступ запрещен", parse_mode=ParseMode.MARKDOWN)
        return
    
    if token_manager.token and token_manager.expires_at:
        remaining = (token_manager.expires_at - datetime.now()).total_seconds()
        text = f"**🔑 Информация о токене**\n\n"
        text += f"**Статус:** ✅ Активен\n"
        text += f"**Истекает:** {token_manager.expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        text += f"**Осталось:** {remaining/86400:.1f} дней ({remaining/3600:.1f} часов)\n"
        text += f"**Токен:** `{token_manager.token[:20]}...{token_manager.token[-10:]}`\n\n"
        
        text += f"**Автообновление:** ✅ активно (проверка каждые 6 часов)"
    else:
        text = "❌ **Токен не получен**"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_health(msg, args):
    stats = bot_keepalive.get_stats() if bot_keepalive else {}
    
    status_icon = "✅" if stats.get('connected') else "⚠️"
    
    text = f"**🩺 Health Check**\n\n"
    text += f"**WebSocket:** {status_icon}\n"
    text += f"**Авторизация:** {'✅' if stats.get('authenticated') else '❌'}\n"
    text += f"**Проверок:** {stats.get('checks', 0)}\n"
    text += f"**Ошибок:** {stats.get('failures', 0)}\n"
    text += f"**Переподключений:** {stats.get('reconnects', 0)}\n"
    text += f"**Бездействие:** {stats.get('idle_seconds', 0)}с"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_ping(msg, args):
    await msg.answer("🏓 **Pong!**", parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_register(msg, args):
    if len(args) < 2:
        await msg.answer("❌ Укажите имя канала", parse_mode=ParseMode.MARKDOWN)
        return
    
    channel_name = args[1].lower()
    
    if channel_name in state_manager.notification_channels:
        await msg.answer(f"❌ Канал `{channel_name}` уже существует", parse_mode=ParseMode.MARKDOWN)
        return
    
    author_id = getattr(msg.author, 'id', None) if hasattr(msg, 'author') else None
    await state_manager.add_channel(channel_name, msg.chat_id, author_id)
    await msg.answer(f"✅ **Канал `{channel_name}` зарегистрирован**\n\nТеперь в вебхуках можно указывать: `channel: {channel_name}`", parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_unregister(msg, args):
    if len(args) < 2:
        await msg.answer("❌ Укажите имя канала", parse_mode=ParseMode.MARKDOWN)
        return
    
    channel_name = args[1].lower()
    
    if await state_manager.remove_channel(channel_name):
        await msg.answer(f"✅ **Канал `{channel_name}` удален**", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer(f"❌ Канал `{channel_name}` не найден", parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_channels(msg, args):
    channels = state_manager.notification_channels
    
    if not channels:
        await msg.answer("❌ Нет каналов", parse_mode=ParseMode.MARKDOWN)
        return
    
    text = "**📢 Каналы:**\n\n"
    for name, info in channels.items():
        text += f"• {get_channel_icon(name)} `{name}` → `{info['chat_id'][:8]}...`\n"
        if info.get('created_by'):
            text += f"  👤 создан: `{info['created_by'][:8]}...`\n"
        text += f"  📅 {info.get('created_at', '')[:10]}\n\n"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_default(msg, args):
    state_manager.default_chat = msg.chat_id
    await state_manager.save()
    await msg.answer(f"📌 **✅ Чат по умолчанию установлен**\n\nТеперь вебхуки без указания канала будут приходить сюда", parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_admins(msg, args):
    admins = admin_manager.get_admins()
    
    text = "**👑 Администраторы**\n\n"
    if admins:
        for i, admin_id in enumerate(admins, 1):
            text += f"{i}. `{admin_id}`\n"
    else:
        text += "Нет администраторов\n"
    
    text += f"\n**Режим доступа:** {admin_manager.mode}"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_admin_add(msg, args):
    if len(args) < 2:
        await msg.answer("❌ Укажите ID пользователя", parse_mode=ParseMode.MARKDOWN)
        return
    
    user_id = args[1]
    
    if admin_manager.add_admin(user_id):
        await msg.answer(f"✅ **Пользователь `{user_id}` добавлен в администраторы**", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer(f"❌ Пользователь `{user_id}` уже является администратором", parse_mode=ParseMode.MARKDOWN)

@admin_required
async def cmd_admin_remove(msg, args):
    if len(args) < 2:
        await msg.answer("❌ Укажите ID пользователя", parse_mode=ParseMode.MARKDOWN)
        return
    
    user_id = args[1]
    
    author_id = getattr(msg.author, 'id', None) if hasattr(msg, 'author') else None
    if user_id == author_id:
        await msg.answer("❌ Нельзя удалить самого себя из администраторов", parse_mode=ParseMode.MARKDOWN)
        return
    
    if admin_manager.remove_admin(user_id):
        await msg.answer(f"✅ **Пользователь `{user_id}` удален из администраторов**", parse_mode=ParseMode.MARKDOWN)
    else:
        await msg.answer(f"❌ Пользователь `{user_id}` не является администратором", parse_mode=ParseMode.MARKDOWN)

# ============================================================================
# ДИСПЕТЧЕР КОМАНД
# ============================================================================

_COMMAND_HANDLERS = {
    '/help': cmd_help,
    '/start': cmd_help,
    '/info': cmd_info,
    '/health': cmd_health,
    '/ping': cmd_ping,
    '/whoami': cmd_whoami,
    '/token_info': cmd_token_info,
    '/register': cmd_register,
    '/unregister': cmd_unregister,
    '/channels': cmd_channels,
    '/default': cmd_default,
    '/admins': cmd_admins,
    '/admin_add': cmd_admin_add,
    '/admin_remove': cmd_admin_remove
}

_processed_commands = deque(maxlen=100)

@router.message()
async def handle_messages(msg: Message):
    global bot_ready
    
    message_id = getattr(msg, 'message_id', None)
    if not message_id or message_id in _processed_commands:
        return
    
    _processed_commands.append(message_id)
    
    if bot_keepalive:
        try:
            bot_keepalive.update_activity()
        except Exception as e:
            logger.debug(f"⚠️ Ошибка обновления активности: {e}")
    
    chat_id = getattr(msg, 'chat_id', None)
    if not chat_id:
        return
    
    text = getattr(msg.content, 'text', '')
    
    if not bot_ready and chat_id and text:
        bot_ready = True
        if bot_keepalive:
            try:
                bot_keepalive.set_authenticated()
            except Exception as e:
                logger.debug(f"⚠️ Ошибка установки авторизации: {e}")
        logger.info(f"✅ Бот готов, чат {chat_id[:8]}...")
    
    if text and text.startswith('/'):
        args = text.strip().split()
        command = args[0].lower()
        
        logger.info(f"🎯 Команда: {command}")
        
        handler = _COMMAND_HANDLERS.get(command)
        if handler:
            try:
                await handler(msg, args)
            except Exception as e:
                logger.error(f"❌ Ошибка команды {command}: {e}")
                await msg.answer(f"❌ Ошибка: {str(e)[:100]}", parse_mode=ParseMode.MARKDOWN)

# ============================================================================
# ВЕБ-СЕРВЕР
# ============================================================================

async def start_web_server():
    app = web.Application()
    
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_post('/zabbix-webhook', handle_webhook)
    
    app.router.add_get('/live', lambda _: web.Response(text="OK"))
    app.router.add_get('/ready', lambda _: web.Response(text="OK" if bot_ready else "NOT READY", status=200 if bot_ready else 503))
    app.router.add_get('/health', lambda _: web.Response(text="OK"))
    
    async def handle_root(request):
        token_status = "active" if token_manager.token else "inactive"
        if token_manager.token and token_manager.expires_at:
            remaining = (token_manager.expires_at - datetime.now()).total_seconds()
            if remaining > 0:
                token_status = f"valid for {remaining/86400:.0f} days"
            else:
                token_status = "expired"
        
        return web.json_response({
            "name": "TrueConf Zabbix Relay Bot",
            "version": VERSION,
            "status": "running",
            "bot_ready": bot_ready,
            "mode": "minimal",
            "token_status": token_status,
            "description": "Бот отправляет ТОЛЬКО то, что получил - без добавления времени и ID",
            "webhook_format": {
                "required": ["message"],
                "optional": ["channel", "subject"],
                "example": {
                    "channel": "critical",
                    "subject": "❗ КРИТИЧЕСКАЯ ПРОБЛЕМА",
                    "message": "Текст уведомления"
                }
            }
        })
    
    app.router.add_get('/', handle_root)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.WEB_SERVER_HOST, config.WEB_SERVER_PORT)
    await site.start()
    
    logger.info(f"🌐 Веб-сервер: {config.WEB_SERVER_HOST}:{config.WEB_SERVER_PORT}")
    return runner

# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

async def main():
    global bot, bot_keepalive, state_manager, admin_manager, token_manager
    global start_time, bot_task, web_runner, bot_ready, is_shutting_down
    
    start_time = datetime.now()
    bot_ready = False
    is_shutting_down = False
    
    # Инициализация менеджеров
    token_manager = TokenManager()
    state_manager = StateManager()
    admin_manager = AdminManager()
    
    logger.info("=" * 60)
    logger.info(f"🚀 TrueConf Zabbix Bot v{VERSION} - С АВТО-ТОКЕНОМ")
    logger.info("=" * 60)
    logger.info(f"⚙️  Настройки:")
    logger.info(f"   🌐 Сервер: {TOKEN_CONFIG['server']}")
    logger.info(f"   🔑 URL токена: {TOKEN_CONFIG['token_url']}")
    logger.info(f"   👤 Пользователь: {TOKEN_CONFIG['username']}")
    logger.info(f"   💓 Heartbeat: {_CONFIG_CACHE['HEARTBEAT_MODE']}")
    logger.info(f"   📋 LOG_LEVEL: {_CONFIG_CACHE['LOG_LEVEL']}")
    logger.info(f"   🔐 ADMIN_MODE: {admin_manager.mode}")
    logger.info(f"   👑 Администраторов: {len(admin_manager.admin_ids)}")
    logger.info("=" * 60)
    
    # Получаем токен
    token = await token_manager.get_token()
    if not token:
        logger.error("❌ Не удалось получить токен. Бот не будет запущен.")
        return
    
    # Запускаем автообновление токена
    token_manager.start_auto_refresh()
    
    logger.info("=" * 60)
    logger.info("📝 Формат вебхука:")
    logger.info("   {")
    logger.info('     "channel": "имя_канала",  // опционально')
    logger.info('     "subject": "Тема сообщения",  // опционально')
    logger.info('     "message": "Текст сообщения"  // обязательно')
    logger.info("   }")
    logger.info("⚠️  ВАЖНО: Бот НЕ добавляет время и ID события!")
    logger.info("=" * 60)
    
    try:
        # Создаем бота
        bot = Bot(
            server=TOKEN_CONFIG['server'],
            token=token,
            dispatcher=dp
        )
        
        # Патчим бота для автоматического обновления токена
        original_send = bot.send_message
        
        async def patched_send(*args, **kwargs):
            try:
                return await original_send(*args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                if 'token' in error_msg or 'unauthorized' in error_msg or 'auth' in error_msg:
                    logger.warning("⚠️ Ошибка авторизации, обновляем токен...")
                    new_token = await token_manager.get_token(force_refresh=True)
                    if new_token:
                        bot._token = new_token
                        return await original_send(*args, **kwargs)
                raise
        
        bot.send_message = patched_send
        
        bot_keepalive = BotKeepAlive(bot)
        await bot_keepalive.start()
        
        web_runner = await start_web_server()
        
        logger.info("🔄 Запуск бота...")
        bot_task = asyncio.create_task(bot.run())
        
        await bot_task
        
    except asyncio.CancelledError:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        logger.error(traceback.format_exc())
    finally:
        is_shutting_down = True
        
        if bot_keepalive:
            await bot_keepalive.stop()
        
        if token_manager:
            await token_manager.stop()
        
        if web_runner:
            await web_runner.cleanup()
        
        await state_manager.save()
        logger.info("👋 Завершение работы")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Программа завершена пользователем")
    except Exception as e:
        logger.critical(f"💥 Необработанная ошибка: {e}")
        logger.critical(traceback.format_exc())