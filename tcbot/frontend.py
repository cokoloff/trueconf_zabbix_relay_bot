# -*- coding: utf-8 -*-
"""
HTML админ-панели бота.

Оформление перенесено из проекта NextCloud Admin:
    * та же палитра Aquarius и переменные тем (см. tcbot/theme.py);
    * шапка со «значком» логотипа и круглым аватаром с выпадающим меню;
    * карточки с линией под заголовком, плитки состояния, панель фильтров;
    * подвал с диагностикой (TTFB, DOM, размер, время);
    * переключатель светлой и тёмной темы внутри меню пользователя.

Разметка отдаётся одним документом; стили подключаются отдельным маршрутом
/static/style.css, скрипты — /static/app.js.
"""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{app_title} — панель управления</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/style.css">
<script>
(function () {{
  /* По умолчанию — светлая тема; тёмная включается вручную и запоминается. */
  try {{
    var t = localStorage.getItem('tcbot-theme');
    document.documentElement.setAttribute('data-theme', (t === 'dark') ? 'dark' : 'light');
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
      <img class="brand-logo" src="/static/logo.svg" alt="Логотип"
           onerror="this.style.display='none';">
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
          <a class="ua-item" href="/diagnostics"><span class="ua-ico">🔬</span>Диагностика</a>
        </div>

        <div class="ua-group ua-group-static"><span class="ua-group-name">Служебные</span></div>
        <div class="ua-section">
          <button type="button" class="ua-item" id="menu-reconnect">
            <span class="ua-ico">♻️</span>Перезапустить связь
          </button>
          <button type="button" class="ua-item" id="menu-ready">
            <span class="ua-ico">🩺</span>Проверить готовность
          </button>
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

<!-- ==================== Компактное состояние ==================== -->
<section class="status-hero sh-warn" id="card-status">
  <div class="sh-state">
    <span class="sh-dot" id="sh-dot"></span>
    <div>
      <div class="sh-title" id="sh-title">Проверка…</div>
      <div class="sh-sub" id="sh-sub">загрузка данных</div>
    </div>
  </div>

  <div class="sh-divider"></div>

  <div class="sh-metrics" id="sh-metrics">
    <div class="metric">
      <span class="metric-value" id="m-uptime">—</span>
      <span class="metric-label">Uptime</span>
    </div>
    <div class="metric">
      <span class="metric-value" id="m-sent">—</span>
      <span class="metric-label">Отправлено</span>
    </div>
    <div class="metric">
      <span class="metric-value" id="m-channels">—</span>
      <span class="metric-label">Каналов</span>
    </div>
    <div class="metric">
      <span class="metric-value" id="m-queue">—</span>
      <span class="metric-label">В очереди</span>
    </div>
    <div class="metric">
      <span class="metric-value" id="m-token">—</span>
      <span class="metric-label">Токен</span>
    </div>
  </div>

  <div class="activity-week" id="activity-week"></div>

  <div class="sh-actions">
    <span class="dim fs-11" id="dashboard-status-text"></span>
    <span class="dash-spinner" id="dashboard-spinner"></span>
    <button type="button" class="secondary small" id="btn-refresh">Обновить</button>
  </div>

  <details class="details-box" style="flex:1 1 100%;">
    <summary>Подробности и события соединения</summary>
    <div class="details-body grid-2">
      <div id="health-rows"></div>
      <div>
        <div class="dim fs-11" style="text-transform:uppercase; letter-spacing:.04em; margin-bottom:6px;">
          События
        </div>
        <div class="events-list" id="events"><span class="dim">нет данных</span></div>
      </div>
    </div>
  </details>
</section>

<!-- ==================== Графики ==================== -->
<section class="card" id="card-charts">
  <h2>
    <span>Динамика</span>
    <span class="h2-right">
      <select id="charts-hours" style="padding:3px 8px; font-size:12px; width:auto;">
        <option value="6">6 часов</option>
        <option value="24" selected>сутки</option>
        <option value="72">3 суток</option>
        <option value="168">неделя</option>
      </select>
      <span id="charts-status" class="dim fs-11"></span>
    </span>
  </h2>

  <div class="charts-grid">
    <div class="chart-box">
      <div class="chart-title"><span>Отправлено</span><span class="chart-value" id="cv-sent">—</span></div>
      <canvas id="chart-sent"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-title"><span>Очередь</span><span class="chart-value" id="cv-queue">—</span></div>
      <canvas id="chart-queue"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-title"><span>Связь</span><span class="chart-value" id="cv-ws">—</span></div>
      <canvas id="chart-ws"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-title"><span>Перезапуски</span><span class="chart-value" id="cv-restarts">—</span></div>
      <canvas id="chart-restarts"></canvas>
    </div>
  </div>
  <div id="charts-empty" class="dim fs-12" style="display:none; padding:8px 0;">
    История ещё не накоплена: точки появляются по мере работы бота.
  </div>
</section>

<!-- ==================== Логи ==================== -->
<div class="card" id="card-logs">
  <h2>
    <span>Логи</span>
    <span class="h2-right">
      <label class="sel fs-13" style="font-weight:normal;">
        <input type="checkbox" id="log-auto" checked style="width:auto;"> авто
      </label>
    </span>
  </h2>

  <div class="filter-bar">
    <div class="fb-field">
      <span class="fb-label">Файл</span>
      <select id="log-file">
        <option value="bot.log">bot.log</option>
        <option value="chat.log">chat.log</option>
        <option value="webhook.log">webhook.log</option>
        <option value="error.log">error.log</option>
        <option value="delete.log">delete.log</option>
        <option value="error_history.log">error_history.log</option>
      </select>
    </div>
    <div class="fb-field">
      <span class="fb-label">Строк</span>
      <select id="log-lines">
        <option value="100">100</option>
        <option value="300" selected>300</option>
        <option value="1000">1000</option>
      </select>
    </div>
    <div class="fb-field fb-search">
      <span class="fb-label">Фильтр</span>
      <input type="search" id="log-filter" placeholder="подстрока…">
    </div>
    <div class="fb-actions">
      <button type="button" class="secondary" id="log-reload">Обновить</button>
    </div>
  </div>

  <pre class="log-view" id="log-view">…</pre>
</div>

<footer class="diag-footer">
  <span class="ft-item" title="Время до первого байта"><span class="ft-key">TTFB</span> <span id="ft-ttfb">—</span></span>
  <span class="ft-sep">·</span>
  <span class="ft-item" title="DOMContentLoaded"><span class="ft-key">DOM</span> <span id="ft-dcl">—</span></span>
  <span class="ft-sep">·</span>
  <span class="ft-item" title="Полная загрузка"><span class="ft-key">load</span> <span id="ft-load">—</span></span>
  <span class="ft-sep">·</span>
  <span class="ft-item" title="Размер HTML"><span class="ft-key">размер</span> <span id="ft-size">—</span></span>
  <span class="ft-sep">·</span>
  <span class="ft-item" title="Версия"><span class="ft-key">версия</span> <span id="ft-version">—</span></span>
  <span class="ft-spacer"></span>
  <span class="ft-item" title="Обновлено"><span id="ft-updated">—</span></span>
</footer>

<div class="copy-toast" id="toast"></div>

<script src="/static/app.js"></script>
</body>
</html>
"""


def render_index(app_title: str = "TrueConf Zabbix Relay Bot",
                 app_subtitle: str = "Relay уведомлений Zabbix в чаты TrueConf") -> str:
    """Подставляет название и подзаголовок в шаблон панели."""
    return INDEX_HTML.format(app_title=app_title, app_subtitle=app_subtitle)


# Значок вкладки: простая «молния» в цветах панели
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#1f4e8c"/>
  <path d="M18 6 L9 18 h6 l-1 8 9-12 h-6 z" fill="#ffffff"/>
</svg>"""

# Логотип в шапке
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 40" height="36">
  <rect x="1" y="4" width="32" height="32" rx="7" fill="#1f4e8c"/>
  <path d="M19 10 L12 21 h5 l-1 7 8-11 h-5 z" fill="#ffffff"/>
  <text x="42" y="20" font-family="Arial, Helvetica, sans-serif" font-size="13"
        font-weight="bold" fill="#1a2b4a">TrueConf</text>
  <text x="42" y="33" font-family="Arial, Helvetica, sans-serif" font-size="10"
        fill="#5a6a7a">Zabbix Relay</text>
</svg>"""