# -*- coding: utf-8 -*-
"""
Страницы разделов панели.

На главной остаются только состояние сервиса и логи — самое нужное в работе.
Всё остальное вынесено в отдельные страницы, доступные из меню аватара:

    /channels    — каналы уведомлений
    /outbox      — очередь недоставленных
    /send        — ручная отправка сообщения
    /settings    — параметры бота
    /admins      — администраторы бота
    /local-admin — локальная учётная запись
"""

from __future__ import annotations

from typing import Any, Callable, Dict

# ============================================================================
# ФРАГМЕНТЫ РАЗМЕТКИ
# ============================================================================

CHANNELS_CARD = r"""<div class="card" id="card-channels">
  <h2>
    <span>Каналы уведомлений <span class="badge badge-count" id="ch-count">0</span></span>
    <span class="h2-right">
      <button type="button" class="secondary small" id="ch-refresh">Обновить</button>
      <button type="button" class="secondary small" id="ch-copy">JSON</button>
      <button type="button" class="small" id="ch-add-toggle">+ Добавить</button>
    </span>
  </h2>

  <div class="filter-bar">
    <div class="fb-field fb-search">
      <span class="fb-label">Поиск</span>
      <input type="search" id="ch-search" placeholder="Имя, chat_id, автор, название чата">
    </div>
    <div class="fb-field">
      <span class="fb-label">Сортировка</span>
      <select id="ch-sort">
        <option value="name">по имени</option>
        <option value="created">по дате</option>
        <option value="chat_id">по chat_id</option>
        <option value="updated">по изменению</option>
      </select>
    </div>
    <div class="fb-field">
      <span class="fb-label">Показывать</span>
      <select id="ch-page-size">
        <option value="10">10</option>
        <option value="20" selected>20</option>
        <option value="50">50</option>
        <option value="0">все</option>
      </select>
    </div>
    <div class="fb-actions">
      <span class="dim fs-12" id="ch-filtered"></span>
    </div>
  </div>

  <div class="filter-bar hidden" id="ch-add-form">
    <div class="fb-field fb-search">
      <span class="fb-label">Имя канала</span>
      <input type="text" id="ch-name" placeholder="network">
    </div>
    <div class="fb-field">
      <span class="fb-label">chat_id</span>
      <input type="text" id="ch-id" placeholder="например 3f8a2b1c…">
    </div>
    <div class="fb-field">
      <span class="fb-label">Название чата</span>
      <input type="text" id="ch-title" placeholder="необязательно">
    </div>
    <div class="fb-actions">
      <button type="button" id="ch-add">Сохранить</button>
      <button type="button" class="secondary" id="ch-add-cancel">Отмена</button>
    </div>
  </div>

  <!-- Форма редактирования: раскрывается в строке таблицы -->
  <div class="filter-bar hidden" id="ch-edit-form">
    <div class="fb-field">
      <span class="fb-label">Имя канала</span>
      <input type="text" id="edit-name">
    </div>
    <div class="fb-field fb-search">
      <span class="fb-label">chat_id</span>
      <input type="text" id="edit-chat-id">
    </div>
    <div class="fb-field fb-search">
      <span class="fb-label">Название чата</span>
      <input type="text" id="edit-chat-title" placeholder="необязательно">
    </div>
    <div class="fb-actions">
      <button type="button" id="edit-save">Сохранить</button>
      <button type="button" class="secondary" id="edit-cancel">Отмена</button>
    </div>
  </div>

  <div class="table-scroll">
    <table class="data-table channels-table">
      <thead>
        <tr>
          <th data-sort="name" style="width:26%;">Канал</th>
          <th data-sort="chat_id" style="width:30%;">Chat ID</th>
          <th data-sort="created" style="width:14%;">Создан</th>
          <th style="width:18%;">Кем</th>
          <th style="width:12%;"></th>
        </tr>
      </thead>
      <tbody id="channels"></tbody>
    </table>
  </div>

  <div class="pager hidden" id="ch-pager">
    <button type="button" class="secondary small" id="ch-prev">← Назад</button>
    <span class="dim fs-12" id="ch-page-info">—</span>
    <button type="button" class="secondary small" id="ch-next">Вперёд →</button>
  </div>

  <p class="dim fs-12" style="margin:10px 0 0;">
    Чат по умолчанию: <code id="default-chat">—</code>
  </p>
</div>"""


OUTBOX_CARD = r"""<div class="card" id="card-outbox">
    <h2>
      <span>Очередь недоставленных <span class="badge badge-count" id="ob-count">0</span></span>
      <span class="h2-right">
        <button type="button" class="secondary small" id="outbox-flush">Выгрузить</button>
        <button type="button" class="danger small" id="outbox-clear">Очистить</button>
      </span>
    </h2>
    <p class="dim fs-12" id="outbox-summary" style="margin:0 0 12px;">—</p>
    <div class="table-scroll" style="max-height:300px;">
      <table class="data-table">
        <thead><tr><th>Канал</th><th>Статус</th><th>Ожидает</th><th>Текст</th></tr></thead>
        <tbody id="outbox"></tbody>
      </table>
    </div>
  </div>"""

ADMINS_CARD = r"""<div class="card">
    <h2>
      <span>Администраторы бота</span>
      <span class="h2-right"><span class="dim fs-12" id="adm-mode"></span></span>
    </h2>
    <div class="filter-bar">
      <div class="fb-field fb-search">
        <span class="fb-label">Новый администратор</span>
        <input type="text" id="adm-id" placeholder="user@domain">
      </div>
      <div class="fb-actions">
        <button type="button" id="adm-add">Добавить</button>
      </div>
    </div>
    <div class="table-scroll" style="max-height:260px;">
      <table class="data-table">
        <thead><tr><th>ID</th><th style="width:80px;">Тип</th><th style="width:90px;"></th></tr></thead>
        <tbody id="admins"></tbody>
      </table>
    </div>
  </div>"""

SEND_CARD = r"""<div class="card">
    <h2>Отправка сообщения</h2>
    <div class="fb-field" style="margin-bottom:10px;">
      <span class="fb-label">Канал</span>
      <input type="text" id="msg-channel" placeholder="пусто = по умолчанию">
    </div>
    <div class="fb-field">
      <span class="fb-label">Текст (Markdown)</span>
      <textarea id="msg-text" placeholder="Текст сообщения"></textarea>
    </div>
    <div class="actions">
      <button type="button" id="msg-send">Отправить</button>
    </div>
  </div>"""

SETTINGS_CARD = r"""<div class="card">
    <h2>Настройки</h2>
    <div class="row"><span class="label">Удалять при восстановлении</span>
      <select id="set-delete"><option value="false">нет</option><option value="true">да</option></select></div>
    <div class="row"><span class="label">Порог удаления, ч</span>
      <input id="set-delete-hours" type="number" min="0"></div>
    <div class="row"><span class="label">Хранение истории, дней</span>
      <input id="set-retention" type="number" min="1"></div>
    <div class="row"><span class="label">Макс. длина сообщения</span>
      <input id="set-maxlen" type="number" min="100"></div>
    <div class="row"><span class="label">Повторы отправки</span>
      <input id="set-retries" type="number" min="0"></div>
    <div class="actions"><button type="button" id="set-save">Сохранить</button></div>
  </div>"""

LOCAL_ADMIN_CARD = r"""<div class="card">
    <h2>Локальный администратор</h2>
    <div id="local-admin-rows"></div>
    <div class="row"><span class="label">Текущий пароль</span>
      <input id="la-current" type="password" autocomplete="current-password"></div>
    <div class="row"><span class="label">Новый пароль</span>
      <input id="la-new" type="password" autocomplete="new-password" placeholder="мин. 12 символов"></div>
    <div class="row"><span class="label">Повтор</span>
      <input id="la-new2" type="password" autocomplete="new-password"></div>
    <div class="actions"><button type="button" id="la-save">Сменить пароль</button></div>
  </div>"""

# ============================================================================
# ОПИСАНИЕ СТРАНИЦ
# ============================================================================

PAGES: Dict[str, Dict[str, Any]] = {
    "channels": {
        "title": "Каналы уведомлений",
        "icon": "📢",
        "description": "Куда бот отправляет уведомления Zabbix. Каждый канал — отдельный чат TrueConf.",
        "content": CHANNELS_CARD,
        "scripts": ["channels"],
    },
    "outbox": {
        "title": "Очередь недоставленных",
        "icon": "📦",
        "description": "Сообщения, которые не удалось доставить: сохраняются на диск и уходят после восстановления связи.",
        "content": OUTBOX_CARD,
        "scripts": ["outbox"],
    },
    "send": {
        "title": "Отправка сообщения",
        "icon": "✉️",
        "description": "Ручная отправка сообщения в канал — для проверки и служебных объявлений.",
        "content": SEND_CARD,
        "scripts": ["send"],
    },
    "settings": {
        "title": "Параметры бота",
        "icon": "⚙️",
        "description": "Поведение при восстановлении связи и ограничения отправки.",
        "content": SETTINGS_CARD,
        "scripts": ["settings"],
    },
    "admins": {
        "title": "Администраторы бота",
        "icon": "👑",
        "description": "Кто может управлять ботом командами в чате. Записи из config.py удалить нельзя.",
        "content": ADMINS_CARD,
        "scripts": ["admins"],
    },
    "local-admin": {
        "title": "Локальный администратор",
        "icon": "🔑",
        "description": "Резервный вход в панель, работает даже когда Keycloak недоступен.",
        "content": LOCAL_ADMIN_CARD,
        "scripts": ["local-admin"],
    },
}

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {app_title}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/style.css">
<script>
(function () {{
  try {{
    var t = localStorage.getItem('tcbot-theme');
    if (t === 'light' || t === 'dark') {{ document.documentElement.setAttribute('data-theme', t); return; }}
    document.documentElement.setAttribute('data-theme', 'light');
  }} catch (e) {{
    document.documentElement.setAttribute('data-theme', 'light');
  }}
}})();
</script>
</head>
<body>
<header>
  <a class="brand" href="/">
    <span class="brand-logo-badge">
      <img class="brand-logo" src="/static/logo.svg" alt="Логотип" onerror="this.style.display='none';">
    </span>
    <div>
      <div class="brand-title">{app_title}</div>
      <div class="brand-sub">{app_subtitle}</div>
    </div>
  </a>

  <div class="user">
    <div class="user-menu" id="user-menu">
      <button type="button" class="user-avatar" id="user-avatar"
              title="Меню пользователя" aria-haspopup="true" aria-expanded="false">?</button>

      <div class="user-dropdown" id="user-dropdown" role="menu">
        <div class="ua-head">
          <span class="ua-name" id="ua-name">—</span>
          <button type="button" class="ua-theme-btn" id="theme-toggle" title="Переключить тему">
            <span class="ua-theme-icon">🌙</span>
          </button>
          <span class="badge badge-admin hidden" id="ua-badge-admin">admin</span>
          <span class="badge badge-local hidden" id="ua-badge-local">local</span>
        </div>

        <a class="ua-group" href="/">
          <span class="ua-group-name">Обзор</span>
          <span class="ua-group-arrow">→</span>
        </a>
        <div class="ua-section">
          <a class="ua-item" href="/"><span class="ua-ico">📊</span>Состояние и логи</a>
        </div>

        <div class="ua-group ua-group-static"><span class="ua-group-name">Управление</span></div>
        <div class="ua-section">
          <a class="ua-item" href="/channels"><span class="ua-ico">📢</span>Каналы</a>
          <a class="ua-item" href="/outbox"><span class="ua-ico">📦</span>Очередь</a>
          <a class="ua-item" href="/send"><span class="ua-ico">✉️</span>Отправка</a>
        </div>

        <div class="ua-group ua-group-static"><span class="ua-group-name">Настройки</span></div>
        <div class="ua-section">
          <a class="ua-item" href="/settings"><span class="ua-ico">⚙️</span>Параметры</a>
          <a class="ua-item" href="/admins"><span class="ua-ico">👑</span>Администраторы</a>
          <a class="ua-item" href="/local-admin"><span class="ua-ico">🔑</span>Локальный вход</a>
        </div>

        <div class="ua-section ua-foot">
          <a class="ua-item ua-logout" href="/auth/logout">
            <span class="ua-ico">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2" stroke-linecap="round"
                   stroke-linejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <polyline points="16 17 21 12 16 7"/>
                <line x1="21" y1="12" x2="9" y2="12"/>
              </svg>
            </span>Выйти
          </a>
        </div>
      </div>
    </div>
  </div>
</header>

<div id="flash-area"></div>

<div class="page-head">
  <a class="back-link" href="/">← Обзор</a>
  <h1 class="page-title">{icon} {title}</h1>
  <p class="page-desc">{description}</p>
</div>

{content}

<footer class="diag-footer">
  <span class="ft-item"><span class="ft-key">страница</span> {title}</span>
  <span class="ft-sep">·</span>
  <span class="ft-item"><span class="ft-key">версия</span> <span id="ft-version">—</span></span>
  <span class="ft-spacer"></span>
  <span class="ft-item" id="ft-updated">—</span>
</footer>

<div class="copy-toast" id="toast"></div>

<script>window.__PAGE__ = "{key}";</script>
<script src="/static/app.js"></script>
</body>
</html>
"""


def render_page(key: str, app_title: str = "TrueConf Zabbix Relay Bot",
                app_subtitle: str = "Relay уведомлений Zabbix в чаты TrueConf") -> str:
    """Собирает страницу раздела по ключу."""
    page = PAGES.get(key)
    if page is None:
        raise KeyError(f"неизвестная страница: {key}")
    return PAGE_TEMPLATE.format(
        key=key,
        title=page["title"],
        icon=page["icon"],
        description=page["description"],
        content=page["content"],
        app_title=app_title,
        app_subtitle=app_subtitle,
    )