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
      <input type="text" id="ch-id" placeholder="3f8a2b1c…">
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
    <div class="fb-field">
      <span class="fb-label">При восстановлении</span>
      <select id="edit-incident-mode">
        <option value="">как в настройках</option>
        <option value="notify">только учесть</option>
        <option value="delete">удалить проблему</option>
        <option value="resolve">прислать «решено»</option>
        <option value="both">удалить и прислать</option>
      </select>
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
          <th data-sort="name" style="width:22%;">Канал</th>
          <th data-sort="chat_id" style="width:26%;">Chat ID</th>
          <th style="width:16%;">При восстановлении</th>
          <th data-sort="created" style="width:12%;">Создан</th>
          <th style="width:12%;">Кем</th>
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

  <div class="default-chat-block">
    <div class="dc-head">
      <span class="dc-title">Чат по умолчанию</span>
      <span class="dim fs-11">куда уходят уведомления без указания канала</span>
      <span class="spacer"></span>
      <button type="button" class="secondary small" id="dc-edit">Изменить</button>
    </div>

    <div class="dc-view" id="dc-view">
      <code id="default-chat">—</code>
      <span class="dim fs-11" id="dc-usage"></span>
    </div>

    <div class="dc-form hidden" id="dc-form">
      <div class="fb-field" style="flex:1 1 340px;">
        <span class="fb-label">Чат из списка каналов</span>
        <select id="dc-select" style="width:100%;">
          <option value="">— выберите канал —</option>
        </select>
      </div>
      <div class="fb-actions">
        <button type="button" class="small" id="dc-apply">Сделать основным</button>
        <button type="button" class="secondary small" id="dc-cancel">Отмена</button>
        <button type="button" class="danger small" id="dc-clear">Очистить</button>
      </div>

      <details class="dc-manual">
        <summary>Ввести chat_id вручную</summary>
        <div class="dc-form">
          <div class="fb-field fb-search">
            <span class="fb-label">chat_id</span>
            <input type="text" id="dc-chat-id" placeholder="например 3f8a2b1c…"
                   autocomplete="off">
          </div>
          <div class="fb-field">
            <span class="fb-label">Название (необязательно)</span>
            <input type="text" id="dc-chat-title" placeholder="Общий чат" autocomplete="off">
          </div>
          <div class="fb-actions">
            <button type="button" class="small" id="dc-save-manual">Сохранить</button>
          </div>
        </div>
      </details>
    </div>

    <div class="dc-hint dim fs-11 hidden" id="dc-hint"></div>
  </div>
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

    <div class="row row-wide">
      <span class="label">Что делать при восстановлении</span>
      <select id="set-incident-mode">
        <option value="notify">ничего — только записать в историю</option>
        <option value="delete">удалить сообщение о проблеме</option>
        <option value="resolve">отправить сообщение «восстановлено»</option>
        <option value="both">удалить и отправить «восстановлено»</option>
      </select>
    </div>
    <p class="dim fs-12" id="set-mode-hint" style="margin:-4px 0 12px;"></p>

    <div class="row"><span class="label">Разрешить удаление сообщений</span>
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

DIAGNOSTICS_CARD = r"""<div class="card" id="card-diag">
  <h2>
    <span>Диагностика через SDK</span>
    <span class="h2-right">
      <button type="button" class="secondary small" id="diag-refresh">Обновить</button>
    </span>
  </h2>
  <p class="dim fs-12" style="margin:0 0 14px;">
    Данные, которые бот получает от сервера TrueConf: сведения о боте, чаты,
    состояние каналов, ограничения на файлы.
  </p>

  <div class="diag-grid">
    <div>
      <h3 class="diag-h">Бот и сервер</h3>
      <div id="diag-identity"></div>
    </div>
    <div>
      <h3 class="diag-h">Ограничения сервера</h3>
      <div id="diag-limits"></div>
    </div>
  </div>

  <h3 class="diag-h" style="margin-top:18px;">
    Состояние каналов
    <span class="badge badge-count" id="diag-ch-problems">0</span>
    <span class="dim fs-11" id="diag-ch-summary"></span>
    <span class="spacer"></span>
    <button type="button" class="secondary small" id="diag-recheck">Проверить заново</button>
  </h3>
  <p class="dim fs-12" style="margin:0 0 10px;">
    Проверяется, что чат канала существует, сколько в нём участников и состоит
    ли там бот. Каналы с ошибкой выделены красным.
  </p>
  <div class="table-scroll" style="max-height:340px;">
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:24%;">Канал</th>
          <th style="width:26%;">Чат</th>
          <th style="width:13%;">Тип</th>
          <th style="width:11%;">Участников</th>
          <th style="width:12%;">Бот</th>
          <th>Примечание</th>
        </tr>
      </thead>
      <tbody id="diag-channels"></tbody>
    </table>
  </div>

  <h3 class="diag-h" style="margin-top:18px;">
    Чаты бота <span class="badge badge-count" id="diag-chats-count">0</span>
  </h3>
  <div class="table-scroll" style="max-height:280px;">
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:40%;">Название</th>
          <th style="width:30%;">chat_id</th>
          <th style="width:16%;">Тип</th>
          <th style="width:14%;">Непрочитанных</th>
        </tr>
      </thead>
      <tbody id="diag-chats"></tbody>
    </table>
  </div>
</div>"""

CHANNEL_STATS_CARD = r"""<div class="card" id="card-channel-charts">
  <h2>
    <span>Динамика</span>
    <span class="h2-right">
      <span id="cs-charts-status" class="dim fs-11"></span>
    </span>
  </h2>

  <div class="chart-box" style="margin-bottom:14px;">
    <div class="chart-title">
      <span>Временная шкала — что и когда уходило</span>
      <span class="h2-right" style="gap:8px;">
        <select id="tl-bucket" style="padding:3px 8px; font-size:12px; width:auto;">
          <option value="auto" selected>шаг: авто</option>
          <option value="1">1 минута</option>
          <option value="5">5 минут</option>
          <option value="15">15 минут</option>
          <option value="30">30 минут</option>
          <option value="60">1 час</option>
          <option value="180">3 часа</option>
        </select>
        <span class="chart-value" id="tl-status">—</span>
      </span>
    </div>
    <div class="timeline-wrap">
      <canvas id="chart-timeline"></canvas>
    </div>
    <div class="timeline-legend" id="tl-legend"></div>
  </div>

  <div class="chart-box" style="margin-bottom:14px;">
    <div class="chart-title">
      <span>Отправлено по каналам</span>
      <span class="chart-value" id="cv-total">—</span>
    </div>
    <canvas id="chart-channels"></canvas>
    <div class="timeline-legend" style="margin-top:6px;">
      <span class="tl-item"><i class="tl-dot" style="background:var(--err);border-radius:2px;"></i>проблемы</span>
      <span class="tl-item"><i class="tl-dot" style="background:var(--ok);border-radius:2px;"></i>решения</span>
      <span class="tl-item" style="opacity:.7;">высота — всего сообщений</span>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-box">
      <div class="chart-title">
        <span>Строгость Zabbix</span><span class="chart-value" id="cv-severity">—</span>
      </div>
      <div class="chart-body"><div id="severity-bars" class="hbars"></div></div>
    </div>
    <div class="chart-box">
      <div class="chart-title">
        <span>Статусы</span><span class="chart-value" id="cv-statuses-2">—</span>
      </div>
      <div class="chart-body"><div id="status-bars-2" class="hbars"></div></div>
    </div>
    <div class="chart-box">
      <div class="chart-title">
        <span>Отправлено и отказы</span><span class="chart-value" id="cv-sent-2">—</span>
      </div>
      <canvas id="chart-sent-2"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-title">
        <span>Задержка доставки</span><span class="chart-value" id="cv-latency-2">—</span>
      </div>
      <canvas id="chart-latency-2"></canvas>
    </div>
  </div>
</div>

<div class="card" id="card-channel-stats">
  <h2>
    <span>Статистика каналов <span class="badge badge-count" id="cs-count">0</span></span>
    <span class="h2-right">
      <select id="cs-hours" style="padding:3px 8px; font-size:12px; width:auto;">
        <option value="6">6 часов</option>
        <option value="24" selected>сутки</option>
        <option value="72">3 суток</option>
        <option value="168">неделя</option>
      </select>
      <button type="button" class="secondary small" id="cs-refresh">Обновить</button>
    </span>
  </h2>

  <div class="cs-totals" id="cs-totals"></div>

  <div class="filter-bar">
    <div class="fb-field fb-search">
      <span class="fb-label">Поиск</span>
      <input type="search" id="cs-search" placeholder="Имя канала">
    </div>
    <div class="fb-field">
      <span class="fb-label">Сортировка</span>
      <select id="cs-sort">
        <option value="total">по количеству</option>
        <option value="name">по имени</option>
        <option value="failed">по отказам</option>
        <option value="latency">по задержке</option>
        <option value="last">по последней отправке</option>
      </select>
    </div>
    <div class="fb-actions">
      <span class="dim fs-12" id="cs-filtered"></span>
    </div>
  </div>

  <div class="table-scroll" style="max-height:none;">
    <table class="data-table cs-table">
      <thead>
        <tr>
          <th style="width:22%;">Канал</th>
          <th data-sort="total" style="width:11%;">Отправлено</th>
          <th style="width:10%;">Отказы</th>
          <th style="width:12%;">Успех</th>
          <th style="width:12%;">Ср. задержка</th>
          <th style="width:18%;">Статусы</th>
          <th style="width:15%;">Последняя</th>
        </tr>
      </thead>
      <tbody id="cs-rows"></tbody>
    </table>
  </div>

  <p class="dim fs-12" style="margin:10px 0 0;">
    <span class="cs-legend">
      <i class="cs-legend-dot" style="background:var(--err)"></i> проблемы
      <i class="cs-legend-dot" style="background:var(--ok)"></i> решения
    </span>
    — в столбике видно соотношение; под ним числа «проблем / решено».
    Данные накапливаются с момента запуска бота. Период переключается сверху.
  </p>
</div>"""

BACKUPS_CARD = r"""<div class="card" id="card-backups">
  <h2>
    <span>Резервные копии <span class="badge badge-count" id="bk-count">0</span></span>
    <span class="h2-right">
      <button type="button" class="secondary small" id="bk-create">Создать копию</button>
      <button type="button" class="secondary small" id="bk-refresh">Обновить</button>
    </span>
  </h2>

  <div class="cs-totals" id="bk-totals"></div>

  <div class="table-scroll" style="max-height:none;">
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:40%;">Копия</th>
          <th style="width:12%;">Размер</th>
          <th style="width:18%;">Создана</th>
          <th style="width:15%;">Содержимое</th>
          <th style="width:15%;"></th>
        </tr>
      </thead>
      <tbody id="bk-rows"></tbody>
    </table>
  </div>

  <p class="dim fs-12" style="margin:10px 0 0;">
    Копии создаются автоматически раз в сутки и вручную.
    Хранятся последние <span id="bk-keep">20</span>.
    Восстановление сохраняет текущее состояние перед заменой — откатиться можно всегда.
  </p>
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
    "channel-stats": {
        "title": "Статистика каналов",
        "icon": "📊",
        "description": "Подробности по каждому каналу: сколько отправлено, отказы, задержка и статусы.",
        "content": CHANNEL_STATS_CARD,
        "scripts": ["channel-stats"],
    },
    "backups": {
        "title": "Резервные копии",
        "icon": "💾",
        "description": "Копии состояния бота: каналы, администраторы, настройки, история.",
        "content": BACKUPS_CARD,
        "scripts": ["backups"],
    },
    "diagnostics": {
        "title": "Диагностика",
        "icon": "🔬",
        "description": "Данные от сервера TrueConf: сведения о боте, состояние каналов, чаты и ограничения.",
        "content": DIAGNOSTICS_CARD,
        "scripts": ["diagnostics"],
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
          <a class="ua-item" href="/channel-stats"><span class="ua-ico">📊</span>Статистика</a>
          <a class="ua-item" href="/backups"><span class="ua-ico">💾</span>Резервные копии</a>
          <a class="ua-item" href="/outbox"><span class="ua-ico">📦</span>Очередь</a>
          <a class="ua-item" href="/send"><span class="ua-ico">✉️</span>Отправка</a>
        </div>

        <div class="ua-group ua-group-static"><span class="ua-group-name">Настройки</span></div>
        <div class="ua-section">
          <a class="ua-item" href="/settings"><span class="ua-ico">⚙️</span>Параметры</a>
          <a class="ua-item" href="/admins"><span class="ua-ico">👑</span>Администраторы</a>
          <a class="ua-item" href="/local-admin"><span class="ua-ico">🔑</span>Локальный вход</a>
          <a class="ua-item" href="/diagnostics"><span class="ua-ico">🔬</span>Диагностика</a>
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