# -*- coding: utf-8 -*-
"""
Дизайн-система панели (перенесена из проекта NextCloud Admin).

Источник: C:/gitea/AQ ansible/NextCloud/dsh_NextCloud/static/style.css
Сохраняем токены, типографику и компоненты один-в-один, добавляя только
то, что нужно этому боту (плитки состояния, просмотр логов, очередь).

Палитра Aquarius: тёмно-синий #1a2b4a, основной #1f4e8c, фон #f4f6f9.
Тёмная тема — через атрибут [data-theme="dark"] на <html>.
"""

STYLE_CSS = r"""
/* ============================================================
   TrueConf Zabbix Relay Bot — оформление в стиле NextCloud Admin
   ============================================================ */

:root,
[data-theme="light"] {
  --aq-dark-blue:    #1a2b4a;
  --aq-black:        #111111;
  --aq-white:        #ffffff;
  --aq-primary:      #1f4e8c;
  --aq-primary-dark: #163a68;
  --aq-primary-soft: #e8eef6;
  --bg-page:         #f4f6f9;
  --bg-card:         #ffffff;
  --bg-tile:         #f8f9fb;
  --bg-input:        #ffffff;
  --border-light:    #dde3ea;
  --border-row:      #edf0f4;
  --text-main:       #1a1a1a;
  --text-muted:      #5a6a7a;
  --text-dim:        #8a96a3;
  --heading-color:   #1a2b4a;
  --row-hover-bg:    #f0f5fb;
  --row-selected-bg: #e3edf8;
  --row-stripe-bg:   #fafbfd;
  --thead-bg:        #eef2f7;
  --thead-text:      #33465c;
  --thead-hover-bg:  #e3eaf2;
  --ok:              #2e7d32;
  --ok-bg:           #e8f5e9;
  --warn:            #b26a00;
  --warn-bg:         #fff8e1;
  --err:             #c62828;
  --err-bg:          #ffebee;
  --info:            #1565c0;
  --info-bg:         #e3f2fd;
  --shadow-card:     0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.03);
  --shadow-focus:    0 0 0 2px rgba(31, 78, 140, 0.2);
  --font-sans: Arial, "Helvetica Neue", Helvetica, sans-serif;
  --link-accent:      #0082c9;
  --ok-strong:        #2e7d32;
  --err-strong:       #a02020;
  --warn-strong:      #e65100;
  --warn-border:      #f0d58a;
  --warn-text:        #8a6d00;
  --warn-row-bg:      #fffbea;
  --warn-row-hover:   #fff3cd;
  --warn-soft-bg:     #fff3e0;
  --warn-soft-border: #f5c47c;
  --warn-soft-text:   #8a4b00;
  --toast-bg:         #2e7d32;
  --toast-error-bg:   #c62828;
  --toast-fg:         #ffffff;
  --tooltip-bg:       #1a1a1a;
  --tooltip-fg:       #ffffff;
  --code-bg:          rgba(0, 0, 0, 0.05);
  --btn-neutral-bg:     #607d8b;
  --btn-neutral-hover:  #546e7a;
  --btn-neutral-fg:     #ffffff;
  --log-bg:           #0d1117;
  --log-fg:           #c9d7e6;
}

[data-theme="dark"] {
  --aq-dark-blue:    #0d1626;
  --aq-black:        #f0f2f5;
  --aq-white:        #1a1f2a;
  --aq-primary:      #4a8fd4;
  --aq-primary-dark: #3a7ab8;
  --aq-primary-soft: #1e2a3a;
  --bg-page:         #0f141a;
  --bg-card:         #1a212b;
  --bg-tile:         #222b37;
  --bg-input:        #1e2733;
  --border-light:    #2a3542;
  --border-row:      #2f3d4f;
  --text-main:       #e6eaf0;
  --text-muted:      #9aa8b8;
  --text-dim:        #6b7889;
  --heading-color:   #e6eaf0;
  --row-hover-bg:    #232e3c;
  --row-selected-bg: #2a3a4d;
  --row-stripe-bg:   #1f2734;
  --thead-bg:        #232d3b;
  --thead-text:      #c8d3e0;
  --thead-hover-bg:  #2c3a4c;
  --ok:              #6bcb77;
  --ok-bg:           #1a2e1f;
  --warn:            #ffb74d;
  --warn-bg:         #2e2618;
  --err:             #ef6b6b;
  --err-bg:          #2a1a1a;
  --info:            #64b5f6;
  --info-bg:         #1a2636;
  --shadow-card:     0 1px 2px rgba(0,0,0,0.3), 0 2px 8px rgba(0,0,0,0.2);
  --shadow-focus:    0 0 0 2px rgba(74, 143, 212, 0.35);
  --link-accent:      #64b5f6;
  --ok-strong:        #6bcb77;
  --err-strong:       #d94a4a;
  --warn-strong:      #ffa726;
  --warn-border:      #5a4a24;
  --warn-text:        #ffcc80;
  --warn-row-bg:      #2b2618;
  --warn-row-hover:   #3a3220;
  --warn-soft-bg:     #2e2618;
  --warn-soft-border: #5a4a24;
  --warn-soft-text:   #ffcc80;
  --toast-bg:         #2e7d32;
  --toast-error-bg:   #b33a3a;
  --toast-fg:         #ffffff;
  --tooltip-bg:       #0b0f14;
  --tooltip-fg:       #e6eaf0;
  --code-bg:          rgba(255, 255, 255, 0.08);
  --btn-neutral-bg:     #3d4a57;
  --btn-neutral-hover:  #4a5a69;
  --btn-neutral-fg:     #e6eaf0;
  --log-bg:           #0b1016;
  --log-fg:           #c9d7e6;
}

* { box-sizing: border-box; }

body {
  font-family: var(--font-sans);
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
  color: var(--text-main);
  background: var(--bg-page);
  line-height: 1.45;
  transition: background 0.2s ease, color 0.2s ease;
}

a { color: var(--aq-primary); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------------- Header ---------------- */
header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24px; padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}
header .brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: inherit; }
header .brand-logo-badge {
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--aq-white); border: 1px solid var(--border-light);
  border-radius: 10px; padding: 6px 10px; box-shadow: var(--shadow-card);
  height: 52px; min-width: 52px;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}
header .brand:hover .brand-logo-badge { box-shadow: 0 2px 6px rgba(0,0,0,0.1); border-color: var(--aq-primary); }
header .brand-logo { height: 36px; width: auto; max-width: 160px; object-fit: contain; display: block; }
header .brand-title { font-size: 22px; font-weight: bold; margin: 0; color: var(--heading-color); }
header .brand-sub { font-size: 12px; color: var(--text-dim); margin-top: 2px; }

@media (max-width: 600px) {
  header .brand-logo-badge { height: 44px; padding: 4px 8px; }
  header .brand-logo { height: 28px; max-width: 110px; }
  header .brand-title { font-size: 18px; }
  header .brand-sub { display: none; }
}

/* ---------------- Cards ---------------- */
.card {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: 8px; padding: 20px; margin-bottom: 16px;
  box-shadow: var(--shadow-card);
  transition: background 0.2s ease, border-color 0.2s ease;
}
.card h2 {
  margin: 0 0 16px; font-size: 18px; color: var(--heading-color);
  border-bottom: 1px solid var(--border-light); padding-bottom: 10px;
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px;
}
.card h2 .h2-right {
  font-size: 12px; color: var(--text-dim); font-weight: normal;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}

/* ---------------- Rows / key-value ---------------- */
.row { display: grid; grid-template-columns: 200px 1fr; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border-row); }
.row:last-child { border-bottom: none; }
.label { color: var(--text-muted); font-size: 14px; }
@media (max-width: 600px) { .row { grid-template-columns: 1fr; gap: 2px; } }

/* ---------------- Badges ---------------- */
.badge {
  display: inline-block; background: var(--aq-primary-soft); color: var(--aq-primary);
  padding: 2px 8px; border-radius: 10px; font-size: 12px; margin: 2px;
}
.badge-admin { background: #2f6fd0; color: #ffffff; font-weight: 600; }
[data-theme="dark"] .badge-admin { background: #4c8dff; color: #0b1220; }
.badge-local { background: var(--warn-bg); color: var(--warn); }
.badge-ok { background: var(--ok-bg); color: var(--ok); }
.badge-err { background: var(--err-bg); color: var(--err); }
.badge-count { background: var(--thead-bg); color: var(--thead-text); font-weight: 600; }

/* ---------------- Statuses & Flash ---------------- */
.ok { color: var(--ok); font-weight: bold; }
.err { color: var(--err); }
.warn { color: var(--warn); }
.muted { color: var(--text-muted); }
.dim { color: var(--text-dim); }
.fs-13 { font-size: 13px; }
.fs-12 { font-size: 12px; }
.fs-11 { font-size: 11px; }

.flash { padding: 10px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; }
.flash.success { background: var(--ok-bg); color: var(--ok); }
.flash.error { background: var(--err-bg); color: var(--err); }
.flash.warning { background: var(--warn-bg); color: var(--warn); }
.flash.info { background: var(--info-bg); color: var(--info); }

/* ---------------- Forms & Buttons ---------------- */
input[type="text"], input[type="email"], input[type="search"], input[type="password"],
input[type="number"], select, textarea {
  padding: 8px 12px; font-size: 14px; border: 1px solid var(--border-light);
  border-radius: 6px; width: 100%; font-family: inherit;
  background: var(--bg-input); color: var(--text-main);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
input:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--aq-primary); box-shadow: var(--shadow-focus);
}
select option { background: var(--bg-card); color: var(--text-main); }
textarea { resize: vertical; min-height: 78px; }

button {
  padding: 8px 16px; font-size: 14px; background: var(--aq-primary); color: #ffffff;
  border: none; border-radius: 6px; cursor: pointer; font-family: inherit;
  transition: background 0.15s ease;
}
button:hover { background: var(--aq-primary-dark); }
button.danger { background: var(--err); }
button.danger:hover { background: var(--err-strong); }
button.warning { background: var(--warn-strong); }
button.secondary { background: transparent; color: var(--aq-primary); border: 1px solid var(--aq-primary); }
button.secondary:hover { background: var(--aq-primary-soft); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.small { padding: 5px 11px; font-size: 12.5px; border-radius: 5px; }

.actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.search-form { display: flex; gap: 8px; margin-bottom: 20px; }
.search-form input { flex: 1; }

/* ---------------- Filter bar (из NextCloud) ---------------- */
.filter-bar {
  display: flex; flex-wrap: wrap; align-items: flex-end;
  gap: 10px 14px; padding: 12px 14px; margin-bottom: 14px;
  background: var(--bg-tile); border: 1px solid var(--border-light); border-radius: 8px;
}
.filter-bar .fb-search { flex: 1 1 240px; max-width: 420px; }
.fb-field { display: flex; flex-direction: column; gap: 3px; flex: 0 0 auto; }
.fb-label {
  font-size: 10px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--text-muted); padding-left: 2px;
}
.fb-field input[type=text], .fb-field input[type=search], .fb-field select {
  width: auto; min-width: 120px; padding: 6px 10px; font-size: 13px;
}
.filter-bar .fb-actions { display: flex; gap: 8px; align-items: center; margin-left: auto; }
.filter-bar .fb-actions button { padding: 6px 12px; font-size: 13px; }

@media (max-width: 720px) {
  .filter-bar { padding: 10px; gap: 8px 10px; }
  .filter-bar .fb-search { flex: 1 1 100%; max-width: none; }
  .fb-field { flex: 1 1 calc(50% - 5px); }
  .fb-field input[type=text], .fb-field input[type=search], .fb-field select { width: 100%; }
  .filter-bar .fb-actions { margin-left: 0; flex: 1 1 100%; }
}

.sel { color: var(--text-main); font-size: 14px; display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.sel select { padding: 6px 10px; font-size: 14px; width: auto; }

/* ---------------- Tables ---------------- */
table { width: 100%; border-collapse: collapse; }
table th, table td { text-align: left; padding: 8px; border-bottom: 1px solid var(--border-row); font-size: 14px; vertical-align: middle; }
table thead th {
  background: var(--thead-bg); color: var(--thead-text); font-weight: bold;
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.02em;
  border-bottom: 1px solid var(--border-row); padding: 10px 8px;
}
table thead th[data-sort] { user-select: none; cursor: pointer; transition: background-color 0.12s ease; }
table thead th[data-sort]:hover { background: var(--thead-hover-bg); }
table tbody tr:nth-child(even) { background: var(--row-stripe-bg); }
table tbody tr { transition: background-color 0.12s ease; }
table tbody tr:hover { background: var(--row-hover-bg); }
table td.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; color: var(--text-muted); word-break: break-all; }
.card table td button { padding: 4px 10px; font-size: 12px; border-radius: 4px; white-space: nowrap; }

.data-table th { white-space: nowrap; }
.data-table td { font-size: 13px; word-break: break-word; }
.data-table .actions-cell { text-align: right; white-space: nowrap; }
.data-table .actions-cell button { margin-left: 4px; }

/* Прокрутка длинных таблиц с липкой шапкой */
.table-scroll { max-height: 420px; overflow: auto; border: 1px solid var(--border-light); border-radius: 8px; }
.table-scroll table thead th { position: sticky; top: 0; z-index: 2; }

/* ---------------- Tiles (дашборд) ---------------- */
.dashboard-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px; margin-bottom: 16px;
}
.tile {
  background: var(--bg-tile); border-radius: 6px; padding: 10px 12px;
  border: 1px solid var(--border-light);
  display: flex; flex-direction: column; justify-content: flex-start;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.tile-value { font-size: 18px; font-weight: bold; color: var(--aq-primary); line-height: 1.1; margin-bottom: 2px; word-break: break-word; }
.tile-label { color: var(--text-muted); font-size: 12px; line-height: 1.2; }
.tile-sub { color: var(--text-dim); font-size: 11px; margin-top: 2px; line-height: 1.2; }
.tile.tile-ok { background-color: var(--ok-bg); border-color: var(--ok); }
.tile.tile-ok .tile-value { color: var(--ok); }
.tile.tile-warn { background-color: var(--warn-bg); border-color: var(--warn); }
.tile.tile-warn .tile-value { color: var(--warn); }
.tile.tile-err { background-color: var(--err-bg); border-color: var(--err); }
.tile.tile-err .tile-value { color: var(--err); }
@media (max-width: 600px) {
  .dashboard-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .tile { padding: 8px 10px; }
  .tile-value { font-size: 16px; }
  .tile-label { font-size: 11px; }
}

/* ---------------- Spinner / skeleton ---------------- */
.dash-spinner {
  display: inline-block; width: 12px; height: 12px; margin-left: 6px;
  border: 2px solid var(--border-light); border-top-color: var(--aq-primary);
  border-radius: 50%; animation: dash-spin 0.8s linear infinite; vertical-align: -2px;
}
@keyframes dash-spin { to { transform: rotate(360deg); } }
.dash-spinner.hidden { display: none; }

/* ---------------- Toast ---------------- */
.copy-toast, .toast {
  position: fixed; bottom: 24px; right: 24px; background: var(--toast-bg);
  color: var(--toast-fg); padding: 10px 16px; border-radius: 6px; font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15); opacity: 0; transform: translateY(8px);
  transition: opacity 0.2s ease, transform 0.2s ease; pointer-events: none;
  z-index: 9999; max-width: 480px; word-break: break-all;
}
.copy-toast.show, .toast.show { opacity: 1; transform: translateY(0); }
.copy-toast.error, .toast.error { background: var(--toast-error-bg); }

/* ---------------- Pre / код ---------------- */
pre {
  background: var(--bg-tile); padding: 12px; border-radius: 6px; overflow-x: auto;
  font-size: 12px; font-family: ui-monospace, Menlo, Consolas, monospace;
  border: 1px solid var(--border-light);
}
code {
  background: var(--code-bg); padding: 1px 5px; border-radius: 3px;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px;
}

/* Просмотр логов: тёмное полотно в обеих темах */
.log-view {
  background: var(--log-bg); color: var(--log-fg); border: 1px solid var(--border-light);
  border-radius: 8px; padding: 12px; margin: 0; max-height: 460px; overflow: auto;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 11.5px; line-height: 1.5; white-space: pre-wrap; word-break: break-word;
}

/* ---------------- Пользователь в шапке (аватар + меню) ---------------- */
.user-menu { position: relative; }
.user-avatar {
  width: 34px; height: 34px; border-radius: 50%;
  border: 2px solid var(--border-light); background: var(--aq-primary); color: #fff;
  font-size: 15px; font-weight: 600; text-transform: uppercase;
  display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer; padding: 0; transition: border-color .15s, transform .12s;
}
.user-avatar:hover { border-color: var(--aq-primary); }
.user-menu.is-open .user-avatar { border-color: var(--aq-primary); box-shadow: 0 0 0 3px var(--aq-primary-soft); }

.user-dropdown {
  position: absolute; top: calc(100% + 8px); right: 0; width: 248px;
  max-height: 70vh; overflow-y: auto;
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: 10px; box-shadow: 0 8px 28px rgba(0, 0, 0, .18);
  padding: 6px; z-index: 200; display: none;
}
.user-menu.is-open .user-dropdown { display: block; }

.ua-head {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 10px 12px; border-bottom: 1px solid var(--border-light); margin-bottom: 4px;
}
.ua-name {
  font-size: 14px; font-weight: 600; color: var(--text-main);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 auto; min-width: 0;
}
.ua-head .badge { flex: 0 0 auto; margin: 0; font-size: 10px; padding: 2px 7px; }

.ua-theme-btn {
  background: transparent; border: 1px solid var(--border-light); color: var(--text-muted);
  border-radius: 6px; padding: 3px 7px; font-size: 12px; line-height: 1; cursor: pointer;
  flex: 0 0 auto;
}
.ua-theme-btn:hover { border-color: var(--aq-primary); color: var(--aq-primary); background: transparent; }

.ua-group {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; margin-top: 4px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted);
  border-radius: 6px; cursor: pointer;
}
.ua-group:hover { color: var(--aq-primary); background: var(--aq-primary-soft); text-decoration: none; }
.ua-group-static { cursor: default; }
.ua-group-static:hover { color: var(--text-muted); background: none; }
.ua-group-arrow { font-size: 12px; opacity: .5; transition: transform .12s, opacity .12s; }
.ua-group:hover .ua-group-arrow { opacity: 1; transform: translateX(2px); }

.ua-section { padding: 0; }
.ua-item {
  display: flex; align-items: center; gap: 9px; padding: 7px 10px; border-radius: 6px;
  font-size: 13px; color: var(--text-main); background: none; border: 0; width: 100%;
  text-align: left; cursor: pointer; font-family: inherit; line-height: 1.3;
}
.ua-item:hover { background: var(--aq-primary-soft); color: var(--aq-primary); text-decoration: none; }
.ua-ico { font-size: 14px; line-height: 1; flex: 0 0 18px; text-align: center; }
.ua-logout { color: var(--err); }
.ua-logout:hover { background: var(--err-bg); color: var(--err); }

@media (max-width: 420px) {
  .user-dropdown { width: min(248px, calc(100vw - 24px)); }
}

/* ---------------- Компактная полоса состояния ---------------- */
.status-hero {
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  padding: 16px 18px; margin-bottom: 16px;
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: 10px; box-shadow: var(--shadow-card);
  transition: background 0.2s ease, border-color 0.2s ease;
}
.status-hero.sh-ok    { border-left: 4px solid var(--ok); }
.status-hero.sh-warn  { border-left: 4px solid var(--warn); }
.status-hero.sh-err   { border-left: 4px solid var(--err); }

.sh-state { display: flex; align-items: center; gap: 12px; min-width: 210px; }
.sh-dot {
  width: 14px; height: 14px; border-radius: 50%; flex: 0 0 auto;
  background: var(--text-dim);
}
.sh-ok   .sh-dot { background: var(--ok);   box-shadow: 0 0 0 4px var(--ok-bg); }
.sh-warn .sh-dot { background: var(--warn); box-shadow: 0 0 0 4px var(--warn-bg); }
.sh-err  .sh-dot { background: var(--err);  box-shadow: 0 0 0 4px var(--err-bg); }

.sh-title { font-size: 17px; font-weight: 700; line-height: 1.2; }
.sh-ok   .sh-title { color: var(--ok); }
.sh-warn .sh-title { color: var(--warn); }
.sh-err  .sh-title { color: var(--err); }
.sh-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

.sh-divider { width: 1px; align-self: stretch; background: var(--border-light); }
@media (max-width: 720px) { .sh-divider { display: none; } }

.sh-metrics {
  display: flex; gap: 22px; flex-wrap: wrap; flex: 1 1 auto; align-items: center;
}
.metric { display: flex; flex-direction: column; gap: 1px; min-width: 68px; }
.metric-value {
  font-size: 16px; font-weight: 700; color: var(--heading-color);
  line-height: 1.1; font-variant-numeric: tabular-nums;
}
.metric-value.is-ok   { color: var(--ok); }
.metric-value.is-warn { color: var(--warn); }
.metric-value.is-err  { color: var(--err); }
.metric-label {
  font-size: 10.5px; color: var(--text-dim); text-transform: uppercase;
  letter-spacing: .04em; white-space: nowrap;
}

.sh-actions { display: flex; gap: 8px; margin-left: auto; }

/* Свёрнутые подробности: не занимают место, пока не нужны */
.details-box {
  margin-top: 4px; border-top: 1px solid var(--border-row); padding-top: 10px;
}
.details-box > summary {
  cursor: pointer; user-select: none; font-size: 12.5px;
  color: var(--text-muted); padding: 4px 0; list-style: none;
}
.details-box > summary::-webkit-details-marker { display: none; }
.details-box > summary::before {
  content: "▸ "; color: var(--text-dim);
}
.details-box[open] > summary::before { content: "▾ "; }
.details-box > summary:hover { color: var(--aq-primary); }
.details-body { padding-top: 10px; }
.details-body .row { grid-template-columns: 190px 1fr; font-size: 13px; }

/* События: компактный список */
.events-list { max-height: 180px; overflow: auto; font-size: 12px; }
.events-list > div {
  display: flex; gap: 8px; padding: 3px 0;
  border-bottom: 1px solid var(--border-row);
}
.events-list time { color: var(--text-dim); flex: 0 0 auto; font-variant-numeric: tabular-nums; }

/* ---------------- Каналы: компактная таблица ---------------- */
.channels-table td { padding: 7px 8px; }
.channels-table .ch-name {
  font-weight: 600; color: var(--heading-color);
}
.channels-table .ch-title {
  font-size: 11.5px; color: var(--text-dim); margin-top: 1px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px;
}
.channels-table .ch-id {
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px;
  color: var(--text-muted); cursor: pointer;
  border-bottom: 1px dotted var(--border-light);
}
.channels-table .ch-id:hover { color: var(--aq-primary); border-bottom-color: var(--aq-primary); }
.channels-table .ch-date { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.channels-table .ch-author {
  font-size: 12px; color: var(--text-dim);
  max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.channels-table tr.is-editing { background: var(--row-selected-bg) !important; }
.channels-table .row-actions { white-space: nowrap; text-align: right; }
.channels-table .row-actions button {
  padding: 3px 9px; font-size: 11.5px; border-radius: 4px; margin-left: 4px;
}

/* Пагинация */
.pager {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  padding: 12px 0 2px;
}
.pager button { padding: 5px 12px; font-size: 12.5px; }
.pager button:disabled { opacity: .4; }

/* ---------------- Графики «Динамика» ---------------- */
/* Показатели состояния: цифры вместо почти всегда статичных графиков */
.stat-tiles {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}
@media (max-width: 1180px) {
  .stat-tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .stat-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.stat-tile {
  background: var(--bg-tile);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 10px 12px;
  min-width: 0;
}
.stat-value {
  font-size: 21px;
  font-weight: 700;
  line-height: 1.15;
  color: var(--aq-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-value.ok { color: var(--ok); }
.stat-value.err { color: var(--err); }
.stat-value.warn { color: var(--warn); }
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 3px;
  text-transform: uppercase;
  letter-spacing: .03em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Сетка графиков: все блоки одной высоты.
   Высота задаётся один раз через --chart-h, чтобы канвас и блок статусов
   не «плыли» друг относительно друга. */
.charts-grid {
  --chart-h: 110px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-top: 10px;
  align-items: stretch;
}
/* Четыре колонки держим только на широком экране, иначе подписи не читаются */
@media (max-width: 1280px) {
  .charts-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .charts-grid { grid-template-columns: minmax(0, 1fr); }
}

.chart-box {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 8px 10px 10px;
  min-width: 0;
  overflow: hidden;
  background: var(--bg-tile);
}
.chart-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  flex: 0 0 auto;
}
.chart-title .chart-value { color: var(--aq-primary); font-weight: 600; }

/* Канвас и блок статусов занимают одну и ту же высоту */
.chart-box canvas {
  display: block;
  width: 100% !important;
  height: var(--chart-h) !important;
}
.chart-body {
  height: var(--chart-h);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

/* Блок статусов: полосы распределяются по доступной высоте */
.chart-body .hbars {
  gap: 5px;
  padding: 0;
  justify-content: center;
}
.chart-body .hbar-row { font-size: 11px; }
.chart-body .hbar-name { flex: 0 0 78px; }
.chart-body .hbar-track { height: 6px; }
.chart-body .hbar-empty {
  display: flex; align-items: center; justify-content: center;
  height: 100%; padding: 0;
}

/* Горизонтальные полосы для разбивки по статусам */
.hbars { display: flex; flex-direction: column; gap: 7px; padding-top: 4px; }
.hbar-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.hbar-name {
  flex: 0 0 96px; color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.hbar-track {
  flex: 1 1 auto; height: 8px; background: var(--border-light);
  border-radius: 4px; overflow: hidden;
}
.hbar-fill { height: 100%; border-radius: 4px; transition: width .25s ease; }
.hbar-count {
  flex: 0 0 auto; color: var(--text-main); font-weight: 600;
  font-variant-numeric: tabular-nums; min-width: 34px; text-align: right;
}
.hbar-empty { color: var(--text-dim); font-size: 12px; padding: 6px 0; }

/* ---------------- Календарь недели ---------------- */
.activity-week {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.aw-chart {
  display: inline-flex;
  align-items: flex-end;
  gap: 4px;
  height: 40px;
}
.aw-col {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  gap: 2px;
  width: 10px;
  cursor: pointer;
}
.aw-lbl {
  font-size: 9px;
  font-style: normal;
  color: var(--text-muted);
  line-height: 1;
}
.aw-stack {
  display: flex;
  flex-direction: column-reverse;
  justify-content: flex-start;
  width: 10px;
  min-height: 3px;
  border-radius: 2px 2px 0 0;
  overflow: hidden;
}
.aw-seg { display: block; width: 100%; min-height: 1px; }
.aw-nav { display: inline-flex; align-items: center; gap: 6px; }
.aw-period {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  min-width: 84px;
  text-align: center;
}
.am-btn {
  border: 1px solid var(--border-light);
  background: transparent; color: var(--text-muted);
  border-radius: 3px; width: 18px; height: 18px;
  cursor: pointer; font-size: 12px; line-height: 1;
  padding: 0; flex: 0 0 auto;
}
.am-btn:hover:not(:disabled) { border-color: var(--aq-primary); color: var(--aq-primary); }
.am-btn:disabled { opacity: .3; cursor: default; }

/* Подсказка календаря */
.aw-tip {
  position: fixed;
  z-index: 1000;
  min-width: 150px;
  max-width: 280px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--bg-card);
  color: var(--text-main);
  border: 1px solid var(--border-light);
  box-shadow: 0 6px 22px rgba(0, 0, 0, .28);
  font-size: 12px;
  line-height: 1.45;
  pointer-events: none;
}
.aw-tip-head {
  color: var(--text-muted);
  font-size: 11px;
  padding-bottom: 6px;
  margin-bottom: 6px;
  border-bottom: 1px solid var(--border-light);
}
.aw-tip-head strong { color: var(--text-main); font-size: 13px; }
.aw-tip-list { display: flex; flex-direction: column; gap: 3px; }
.aw-tip-row { display: flex; align-items: center; gap: 6px; }
.aw-tip-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.aw-tip-uid {
  flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; color: var(--text-main);
}
.aw-tip-cnt { font-weight: 600; color: var(--text-muted); flex: 0 0 auto; }
.aw-tip-empty { color: var(--text-muted); font-size: 11px; }

/* Заголовок раздела с календарём справа */
.section-head {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  flex-wrap: nowrap;
  margin-bottom: 8px;
}
.section-head-text { flex: 1 1 auto; min-width: 0; }
.section-head .activity-week {
  flex: 0 0 auto;
  margin-left: auto;
  align-self: flex-start;
  padding-top: 2px;
}
@media (max-width: 760px) {
  .section-head { flex-wrap: wrap; gap: 10px; }
  .section-head .activity-week { margin-left: 0; }
}

/* Пункт меню с необратимым действием (перезапуск службы) */
.ua-item.ua-danger { color: var(--err); }
.ua-item.ua-danger:hover { background: var(--err-bg); }

/* Режим инцидентов в строке канала */
.ch-mode {
  display: inline-block;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  white-space: nowrap;
  line-height: 1.4;
}
.ch-mode.own {
  background: var(--aq-primary-light, rgba(31, 78, 140, .12));
  color: var(--aq-primary);
  font-weight: 600;
}
.ch-mode.inherits {
  color: var(--text-muted);
  background: var(--thead-bg);
}

/* ---------------- Чат по умолчанию ---------------- */
.default-chat-block {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
}
.dc-head {
  display: flex; align-items: center; gap: 8px;
  flex-wrap: wrap; margin-bottom: 8px;
}
.dc-head .spacer { flex: 1 1 auto; }
.dc-title {
  font-size: 12px; font-weight: 600; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .03em;
}
.dc-view { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.dc-view code {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12.5px; padding: 3px 8px; border-radius: 4px;
  background: var(--bg-tile); border: 1px solid var(--border-light);
  word-break: break-all;
}
.dc-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
.dc-form .fb-search { flex: 1 1 320px; }
.dc-form input {
  width: 100%; padding: 6px 9px; font-size: 13px;
  border: 1px solid var(--border-light); border-radius: 5px;
  background: var(--bg-card); color: var(--text-main);
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.dc-form input:focus {
  outline: none; border-color: var(--aq-primary);
  box-shadow: 0 0 0 2px rgba(31, 78, 140, .15);
}
.dc-hint {
  margin-top: 8px; padding: 6px 10px; border-radius: 5px;
  background: var(--warn-bg); color: var(--warn);
}
.dc-manual {
  flex: 1 1 100%;
  margin-top: 4px;
  border-top: 1px dashed var(--border-light);
  padding-top: 8px;
}
.dc-manual summary {
  cursor: pointer;
  font-size: 11.5px;
  color: var(--text-muted);
  user-select: none;
  padding: 2px 0;
}
.dc-manual summary:hover { color: var(--aq-primary); }
.dc-manual[open] summary { margin-bottom: 8px; }
#dc-select {
  width: 100%; padding: 6px 9px; font-size: 13px;
  border: 1px solid var(--border-light); border-radius: 5px;
  background: var(--bg-card); color: var(--text-main);
}
#dc-select:focus {
  outline: none; border-color: var(--aq-primary);
  box-shadow: 0 0 0 2px rgba(31, 78, 140, .15);
}

/* ---------------- Статистика каналов ---------------- */
/* Широкая строка настроек (селект режима) */
.row.row-wide { align-items: flex-start; }
.row.row-wide select { flex: 1 1 320px; max-width: 420px; }

/* Временная шкала: точки, размер зависит от числа сообщений */
.timeline-wrap { position: relative; }
.timeline-legend {
  display: flex; flex-wrap: wrap; gap: 10px;
  margin-top: 8px; font-size: 11.5px; color: var(--text-muted);
}
.timeline-legend .tl-item { display: inline-flex; align-items: center; gap: 5px; }
.timeline-legend .tl-dot {
  width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto;
}
.tl-tip {
  position: fixed;
  z-index: 1000;
  min-width: 190px;
  max-width: 320px;
  padding: 9px 11px;
  border-radius: 6px;
  background: var(--bg-card);
  color: var(--text-main);
  border: 1px solid var(--border-light);
  box-shadow: 0 6px 22px rgba(0, 0, 0, .28);
  font-size: 12px;
  line-height: 1.45;
  pointer-events: none;
}
.tl-tip-head {
  color: var(--text-muted); font-size: 11px;
  padding-bottom: 6px; margin-bottom: 6px;
  border-bottom: 1px solid var(--border-light);
}
.tl-tip-head strong { color: var(--text-main); font-size: 13px; }
.tl-tip-row { display: flex; align-items: center; gap: 6px; }
.tl-tip-dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
.tl-tip-name {
  flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.tl-tip-count {
  font-weight: 600; color: var(--text-muted); flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
}

.cs-totals {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.cs-total {
  background: var(--bg-tile); border: 1px solid var(--border-light);
  border-radius: 8px; padding: 10px 12px;
}
.cs-total-value {
  font-size: 19px; font-weight: 700; color: var(--aq-primary);
  line-height: 1.1; font-variant-numeric: tabular-nums;
}
.cs-total-value.ok { color: var(--ok); }
.cs-total-value.err { color: var(--err); }
.cs-total-label {
  font-size: 11px; color: var(--text-muted); margin-top: 2px;
  text-transform: uppercase; letter-spacing: .03em;
}

.cs-table td { vertical-align: middle; }
.cs-table .cs-name { font-weight: 600; color: var(--heading-color); }
.cs-table .cs-num { font-variant-numeric: tabular-nums; }
.cs-table .cs-num.err { color: var(--err); font-weight: 600; }

/* Мини-график распределения по часам в строке канала.
   Столбик делится на проблемы (красное) и решения (зелёное). */
.cs-spark-row {
  display: flex; align-items: center; gap: 8px;
  margin-top: 3px; min-height: 22px;
}
.cs-spark { display: flex; align-items: flex-end; gap: 1px; height: 22px; }
.cs-seg-stack {
  display: flex; flex-direction: column-reverse;
  width: 3px; border-radius: 1px; overflow: hidden;
  justify-content: flex-start;
}
.cs-spark i.cs-seg { display: block; width: 3px; border-radius: 0; }
.cs-spark i.cs-seg.zero {
  height: 2px; background: var(--border-light); border-radius: 1px;
}
.cs-spark-sum {
  font-size: 10.5px; color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap; flex: 0 0 auto;
}
.cs-spark-sum b { font-weight: 600; }

.cs-legend { display: inline-flex; align-items: center; gap: 4px; }
.cs-legend-dot {
  display: inline-block; width: 8px; height: 8px;
  border-radius: 2px; margin-left: 6px;
}
.cs-legend-dot:first-child { margin-left: 0; }

/* Полоса успешности */
.cs-rate { display: flex; align-items: center; gap: 7px; }
.cs-rate-track {
  flex: 1 1 auto; height: 6px; background: var(--border-light);
  border-radius: 3px; overflow: hidden; min-width: 40px;
}
.cs-rate-fill { height: 100%; border-radius: 3px; background: var(--ok); }
.cs-rate-fill.warn { background: var(--warn); }
.cs-rate-fill.err { background: var(--err); }
.cs-rate-text { font-size: 11.5px; font-variant-numeric: tabular-nums; }

.cs-badges { display: flex; gap: 4px; flex-wrap: wrap; }
.cs-badge {
  font-size: 10.5px; padding: 1px 6px; border-radius: 4px;
  background: var(--thead-bg); color: var(--thead-text); white-space: nowrap;
}
.cs-badge.problem { background: var(--err-bg); color: var(--err); }
.cs-badge.resolved { background: var(--ok-bg); color: var(--ok); }

/* ---------------- Диагностика ---------------- */
.diag-grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px; align-items: start;
}
@media (max-width: 900px) { .diag-grid { grid-template-columns: 1fr; } }
.diag-h {
  font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--text-muted); margin: 0 0 8px; font-weight: 600;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.diag-h .spacer { flex: 1 1 auto; }
.diag-h button { text-transform: none; letter-spacing: 0; }
.badge-warn { background: var(--warn-bg); color: var(--warn); font-weight: 600; }

/* ---------------- Заголовок страницы раздела ---------------- */
.page-head { margin-bottom: 18px; }
.back-link {
  display: inline-block; font-size: 12.5px; color: var(--text-muted);
  margin-bottom: 8px; text-decoration: none;
}
.back-link:hover { color: var(--aq-primary); text-decoration: none; }
.page-title {
  font-size: 20px; font-weight: 700; color: var(--heading-color);
  margin: 0 0 4px; line-height: 1.25;
  border-bottom: 1px solid var(--border-light); padding-bottom: 8px;
}
.page-desc {
  font-size: 13px; color: var(--text-muted); margin: 0;
  max-width: 820px; line-height: 1.45;
}

/* ---------------- Подвал с диагностикой ---------------- */
.diag-footer {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  margin-top: 24px; padding: 10px 12px; border-top: 1px solid var(--border-light);
  font-size: 11px; color: var(--text-dim);
  font-family: ui-monospace, Menlo, Consolas, monospace;
}
.diag-footer .ft-key { color: var(--text-muted); opacity: 0.8; }
.diag-footer .ft-sep { opacity: 0.4; }
.diag-footer .ft-spacer { flex: 1 1 auto; }
.diag-footer .ft-item { white-space: nowrap; }

/* ---------------- Страница входа ---------------- */
.login-wrap { display: flex; justify-content: center; padding-top: 40px; }
.login-card { max-width: 420px; width: 100%; }
.login-card h2 { justify-content: center; }
.login-form .row { grid-template-columns: 110px 1fr; align-items: center; }
.login-divider {
  display: flex; align-items: center; gap: 10px; margin: 18px 0;
  color: var(--text-dim); font-size: 12px;
}
.login-divider::before, .login-divider::after {
  content: ""; flex: 1; height: 1px; background: var(--border-light);
}
.login-hint { color: var(--text-dim); font-size: 12px; margin-top: 16px; line-height: 1.5; }
.btn-link { text-decoration: none; display: inline-flex; }
.btn-link:hover { text-decoration: none; }
.btn-link button { pointer-events: none; }

/* ---------------- Скелетоны ---------------- */
.skeleton-row {
  height: 22px; border-radius: 4px;
  background: linear-gradient(90deg, var(--bg-tile) 0%, var(--bg-card) 50%, var(--bg-tile) 100%);
  background-size: 200% 100%; animation: skeleton-move 1.4s linear infinite;
}
@keyframes skeleton-move { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
.fade-in { animation: dash-fade 0.35s ease-in; }
@keyframes dash-fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

/* ---------------- Утилиты раскладки ---------------- */
.grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
.grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; align-items: start; }
@media (max-width: 1100px) { .grid-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
.span-2 { grid-column: span 2; }
@media (max-width: 760px) { .span-2 { grid-column: span 1; } }
.hidden { display: none !important; }
form.hidden { display: none !important; }
.login-form .actions { margin-top: 16px; }
.login-form .actions button { width: 100%; }
.nowrap { white-space: nowrap; }
.center { text-align: center; }
.right { text-align: right; }
.empty-cell { padding: 18px; text-align: center; color: var(--text-dim); font-size: 13px; }
.card-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.card-actions .spacer { flex: 1; }
"""
