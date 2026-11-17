# -*- coding: utf-8 -*-
"""Клиентский скрипт панели (отдаётся по /static/app.js)."""

APP_JS = r"""
/* ============================================================
   TrueConf Zabbix Relay Bot - панель управления
   Поведение в духе NextCloud Admin: тема в меню аватара,
   тосты, сортировка таблиц, живые плитки.
   ============================================================ */

(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var THEME_KEY = 'tcbot-theme';
  var currentUser = null;
  var channelsData = {};
  var sortKey = 'name';
  var sortDir = 1;
  var logTimer = null;

  function escapeHtml(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var toastTimer = null;
  function toast(msg, isError) {
    var el = $('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('error', !!isError);
    el.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('show'); }, 2600);
  }

  function fmtDuration(seconds) {
    if (seconds == null) return '-';
    seconds = Math.floor(seconds);
    var d = Math.floor(seconds / 86400);
    var h = Math.floor((seconds % 86400) / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    if (d) return d + ' д ' + h + ' ч';
    if (h) return h + ' ч ' + m + ' мин';
    if (m) return m + ' мин ' + s + ' с';
    return s + ' с';
  }

  function rows(container, pairs) {
    if (!container) return;
    container.innerHTML = pairs.map(function (p) {
      return '<div class="row"><span class="label">' + p[0] + '</span><span>' + p[1] + '</span></div>';
    }).join('');
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    return fetch(path, options).then(function (resp) {
      if (resp.status === 401) {
        var loginPath = '/login';
        return resp.clone().json().catch(function () { return {}; }).then(function (payload) {
          if (payload && payload.login) loginPath = payload.login;
          window.location.href = loginPath + '?next=' + encodeURIComponent(window.location.pathname);
          throw new Error('требуется вход');
        });
      }
      return resp.json().catch(function () { return null; }).then(function (data) {
        if (!resp.ok) {
          throw new Error((data && (data.error || data.detail || data.message)) || ('HTTP ' + resp.status));
        }
        return data;
      });
    });
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}
    updateThemeIcon();
  }

  function updateThemeIcon() {
    var btn = $('theme-toggle');
    if (!btn) return;
    var icon = btn.querySelector('.ua-theme-icon');
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (icon) icon.textContent = dark ? '☀' : '🌙';
    btn.title = dark ? 'Включить светлую тему' : 'Включить тёмную тему';
  }

  function initUserMenu() {
    var menu = $('user-menu');
    var avatar = $('user-avatar');
    var themeBtn = $('theme-toggle');
    if (!menu || !avatar) return;

    avatar.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = menu.classList.toggle('is-open');
      avatar.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    document.addEventListener('click', function (e) {
      if (!menu.contains(e.target)) {
        menu.classList.remove('is-open');
        avatar.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        menu.classList.remove('is-open');
        avatar.setAttribute('aria-expanded', 'false');
      }
    });

    if (themeBtn) {
      themeBtn.addEventListener('click', function () {
        applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
      });
    }

    var reconnect = $('menu-reconnect');
    if (reconnect) {
      reconnect.addEventListener('click', function () {
        menu.classList.remove('is-open');
        api('/api/reconnect', { method: 'POST' })
          .then(function () { toast('Перезапуск связи инициирован'); })
          .catch(function (e) { toast(e.message, true); });
      });
    }

    var ready = $('menu-ready');
    if (ready) {
      ready.addEventListener('click', function () {
        menu.classList.remove('is-open');
        fetch('/ready').then(function (r) {
          return r.json().then(function (d) {
            toast(r.ok ? 'Готов: связь и авторизация в порядке'
                       : 'Не готов: ' + (d.state || '-'), !r.ok);
          });
        }).catch(function (e) { toast('Ошибка: ' + e.message, true); });
      });
    }
  }

  function loadMe() {
    return api('/api/me').then(function (data) {
      currentUser = data.user || null;
      if (!currentUser) return;
      var name = currentUser.name || currentUser.username || '?';
      var avatar = $('user-avatar');
      if (avatar) avatar.textContent = name.charAt(0).toUpperCase();
      var uaName = $('ua-name');
      if (uaName) uaName.textContent = name;

      var badgeAdmin = $('ua-badge-admin');
      var badgeLocal = $('ua-badge-local');
      if (badgeAdmin && currentUser.is_admin) badgeAdmin.classList.remove('hidden');
      if (badgeLocal && currentUser.via === 'local') badgeLocal.classList.remove('hidden');
      if (badgeLocal && currentUser.via === 'keycloak') {
        badgeLocal.textContent = 'sso';
        badgeLocal.classList.remove('hidden');
      }

      if (!currentUser.is_admin) {
        ['ch-add-toggle', 'ch-add', 'adm-add', 'msg-send', 'set-save',
         'la-save', 'outbox-flush', 'outbox-clear'].forEach(function (id) {
          var b = $(id);
          if (b) {
            b.disabled = true;
            b.title = 'Только просмотр: нужны права администратора';
          }
        });
      }
    }).catch(function () {});
  }

  function setMetric(id, value, kind) {
    var el = $(id);
    if (!el) return;
    el.textContent = value;
    el.className = 'metric-value' + (kind ? ' is-' + kind : '');
  }

  function loadStatusCompact(data) {
    var h = data.health || {};
    var st = data.stats || {};
    var token = data.token || {};
    var ob = data.outbox || {};

    var hero = $('card-status');
    var ready = !!h.ready;
    var ws = !!h.ws_connected;
    var kind = ready ? 'ok' : (ws ? 'warn' : 'err');

    if (hero) hero.className = 'status-hero sh-' + kind;

    var title = $('sh-title');
    var sub = $('sh-sub');
    if (title) {
      title.textContent = ready ? 'Работает' : (ws ? 'Подключён, без авторизации' : 'Нет связи');
    }
    if (sub) {
      sub.textContent = escapeHtml(h.server || '') +
        (h.last_error ? ' · ' + escapeHtml(String(h.last_error).slice(0, 70)) : '');
    }

    setMetric('m-uptime', fmtDuration(h.uptime_seconds));
    setMetric('m-sent', String(st.messages_sent || 0),
              (st.messages_failed ? 'warn' : null));
    setMetric('m-channels', String(st.channels || 0));
    setMetric('m-queue', String(ob.size || 0), (ob.size ? 'warn' : 'ok'));
    setMetric('m-token',
              token.valid ? Math.round(token.remaining_hours || 0) + 'ч' : 'истёк',
              token.valid ? null : 'warn');

    rows($('health-rows'), [
      ['WebSocket', h.ws_connected ? '<span class="ok">подключён</span>' : '<span class="err">нет</span>'],
      ['Авторизация', h.authorized ? '<span class="ok">да</span>' : '<span class="err">нет</span>'],
      ['Состояние', escapeHtml(h.state || '—')],
      ['Heartbeat', escapeHtml(h.heartbeat_mode + ' / ' + h.heartbeat_interval + ' с')],
      ['Простой связи', h.outage_seconds != null ? fmtDuration(h.outage_seconds) : '—'],
      ['Следующая попытка', h.next_retry_in_seconds != null ? 'через ' + fmtDuration(h.next_retry_in_seconds) : '—'],
      ['Перезапусков', (h.restarts || 0) + ' (потерь: ' + (h.disconnects || 0) + ')'],
      ['Проверок heartbeat', (h.probes || 0) + ' (сбоев: ' + (h.probe_failures || 0) + ')'],
      ['Вебхуков принято', st.webhooks_received || 0],
      ['Отложено в очередь', st.webhooks_queued || 0],
      ['Ошибок отправки', st.messages_failed || 0],
      ['Токен истекает', token.expires_at ? escapeHtml(String(token.expires_at).slice(0, 16).replace('T', ' ')) : '—'],
      ['Старт процесса', escapeHtml(st.process_started || '—')],
      ['Последняя ошибка', h.last_error ? '<span class="err">' + escapeHtml(h.last_error) + '</span>' : '—'],
    ]);

    var version = $('ft-version');
    if (version) version.textContent = 'v' + (data.version || '?');

    var events = $('events');
    var list = data.events || [];
    if (events) {
      events.innerHTML = list.length ? list.map(function (e) {
        return '<div><time>' + escapeHtml(String(e.ts).slice(11)) + '</time>' +
          '<span>' + escapeHtml(e.kind) + ': ' + escapeHtml(String(e.value)) + '</span></div>';
      }).join('') : '<span class="dim">нет данных</span>';
    }
  }

  function loadStatus() {
    return api('/api/status').then(function (data) {
      var spinner = $('dashboard-spinner');
      if (spinner) spinner.classList.add('hidden');
      var statusText = $('dashboard-status-text');
      if (statusText) statusText.textContent = new Date().toLocaleTimeString('ru-RU');

      var footer = $('ft-updated');
      if (footer) footer.textContent = new Date().toLocaleTimeString('ru-RU');

      loadStatusCompact(data);
      loadOutboxCounters(data.outbox);
    }).catch(function () {
      var hero = $('card-status');
      if (hero) hero.className = 'status-hero sh-err';
      var title = $('sh-title');
      if (title) title.textContent = 'Нет ответа от бота';
      var sub = $('sh-sub');
      if (sub) sub.textContent = 'проверьте, запущен ли процесс';
      var spinner = $('dashboard-spinner');
      if (spinner) spinner.classList.add('hidden');
    });
  }

  function loadOutboxCounters(outbox) {
    var count = $('ob-count');
    if (count && outbox) count.textContent = outbox.size || 0;
  }

  function sortChannels(entries) {
    return entries.slice().sort(function (a, b) {
      var va, vb;
      if (sortKey === 'created') { va = a[1].created_at || ''; vb = b[1].created_at || ''; }
      else if (sortKey === 'chat_id') { va = a[1].chat_id || ''; vb = b[1].chat_id || ''; }
      else { va = a[0]; vb = b[0]; }
      return String(va).localeCompare(String(vb)) * sortDir;
    });
  }

  var chPage = 0;

  function filteredChannels() {
    var query = (($('ch-search') || {}).value || '').trim().toLowerCase();
    var entries = Object.entries(channelsData);
    if (query) {
      entries = entries.filter(function (e) {
        var name = e[0], info = e[1];
        return name.toLowerCase().indexOf(query) >= 0 ||
          String(info.chat_id || '').toLowerCase().indexOf(query) >= 0 ||
          String(info.created_by || '').toLowerCase().indexOf(query) >= 0 ||
          String(info.chat_title || '').toLowerCase().indexOf(query) >= 0;
      });
    }
    return sortChannels(entries);
  }

  function renderChannels() {
    var entries = filteredChannels();
    var sizeSel = $('ch-page-size');
    var pageSize = sizeSel ? Number(sizeSel.value) || 0 : 20;

    var pages = (pageSize > 0) ? Math.max(1, Math.ceil(entries.length / pageSize)) : 1;
    if (chPage >= pages) chPage = pages - 1;
    if (chPage < 0) chPage = 0;

    var visible = (pageSize > 0)
      ? entries.slice(chPage * pageSize, (chPage + 1) * pageSize)
      : entries;

    var count = $('ch-count');
    if (count) count.textContent = entries.length;
    var filtered = $('ch-filtered');
    if (filtered) {
      var q = (($('ch-search') || {}).value || '').trim();
      filtered.textContent = q ? 'найдено: ' + entries.length : '';
    }

    var body = $('channels');
    if (!body) return;
    body.innerHTML = visible.length ? visible.map(function (e) {
      var name = e[0], info = e[1];
      var chatId = String(info.chat_id || '');
      var short = chatId.length > 18 ? chatId.slice(0, 18) + '…' : chatId;
      return '<tr data-channel="' + escapeHtml(name) + '">' +
        '<td>' +
          '<div class="ch-name">' + escapeHtml(name) + '</div>' +
          (info.chat_title ? '<div class="ch-title" title="' + escapeHtml(info.chat_title) + '">' +
            escapeHtml(info.chat_title) + '</div>' : '') +
        '</td>' +
        '<td><span class="ch-id" data-copy="' + escapeHtml(chatId) + '" ' +
          'title="Нажмите, чтобы скопировать">' + escapeHtml(short) + '</span></td>' +
        '<td class="ch-date">' + escapeHtml(String(info.created_at || '').slice(0, 10)) +
          (info.updated_at ? '<div class="dim fs-11">изм. ' +
            escapeHtml(String(info.updated_at).slice(5, 10)) + '</div>' : '') + '</td>' +
        '<td class="ch-author" title="' + escapeHtml(info.created_by || '') + '">' +
          escapeHtml(info.created_by || '—') + '</td>' +
        '<td class="row-actions">' +
          '<button class="secondary" data-edit-channel="' + escapeHtml(name) + '">✎</button>' +
          '<button class="danger" data-del-channel="' + escapeHtml(name) + '">✕</button>' +
        '</td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="5"><div class="empty-cell">' +
        (entries.length ? 'нет данных' : 'каналов нет — добавьте первый') + '</div></td></tr>';

    var pager = $('ch-pager');
    if (pager) {
      if (pageSize > 0 && pages > 1) {
        pager.classList.remove('hidden');
        $('ch-page-info').textContent = 'стр. ' + (chPage + 1) + ' из ' + pages +
          ' · записей ' + entries.length;
        $('ch-prev').disabled = chPage <= 0;
        $('ch-next').disabled = chPage >= pages - 1;
      } else {
        pager.classList.add('hidden');
      }
    }
  }

  function loadChannels() {
    return api('/api/channels').then(function (data) {
      channelsData = data.channels || {};
      var def = $('default-chat');
      if (def) def.textContent = data.default_chat || '-';
      renderChannels();
    });
  }

  function loadOutbox() {
    return api('/api/outbox?limit=20').then(function (data) {
      var s = data.stats || {};
      var count = $('ob-count');
      if (count) count.textContent = s.size || 0;
      var summary = $('outbox-summary');
      if (summary) {
        summary.textContent = 'в очереди: ' + (s.size || 0) + ' из ' + (s.max_size || 0) +
          ' | TTL ' + (s.ttl_hours || 0) + ' ч' +
          (s.oldest_age_seconds ? ' | старейшее ' + fmtDuration(s.oldest_age_seconds) : '') +
          ' | доставлено: ' + (s.sent_total || 0) +
          (s.dropped_total ? ' | потеряно: ' + s.dropped_total : '');
      }
      var body = $('outbox');
      if (!body) return;
      var items = data.items || [];
      body.innerHTML = items.length ? items.map(function (item) {
        return '<tr><td><strong>' + escapeHtml(item.channel || '-') + '</strong></td>' +
          '<td class="fs-12">' + escapeHtml(item.status || '-') + '</td>' +
          '<td class="dim fs-12">' + fmtDuration(item.age_seconds) + '</td>' +
          '<td class="dim fs-12 mono">' + escapeHtml(String(item.text || '').slice(0, 80)) + '</td></tr>';
      }).join('') : '<tr><td colspan="4"><div class="empty-cell">очередь пуста</div></td></tr>';
    }).catch(function (e) {
      var summary = $('outbox-summary');
      if (summary) summary.textContent = 'ошибка: ' + e.message;
    });
  }

  function loadAdmins() {
    return api('/api/admins').then(function (data) {
      var mode = $('adm-mode');
      if (mode) mode.textContent = 'режим: ' + (data.mode || '-');
      var body = $('admins');
      if (!body) return;
      var list = data.admins || [];
      body.innerHTML = list.length ? list.map(function (a) {
        return '<tr><td class="mono">' + escapeHtml(a.id) + '</td>' +
          '<td><span class="badge">' + (a.static ? 'config' : 'state') + '</span></td>' +
          '<td class="actions-cell">' + (a.static ? '<span class="dim">-</span>' :
            '<button class="danger" data-del-admin="' + escapeHtml(a.id) + '">удалить</button>') +
          '</td></tr>';
      }).join('') : '<tr><td colspan="3"><div class="empty-cell">нет администраторов</div></td></tr>';
    });
  }

  function loadSettings() {
    return api('/api/settings').then(function (data) {
      var s = data.settings || {};
      if ($('set-delete')) $('set-delete').value = String(!!s.delete_messages_enabled);
      if ($('set-delete-hours')) $('set-delete-hours').value = s.error_delete_threshold_hours;
      if ($('set-retention')) $('set-retention').value = s.error_history_retention_days;
      if ($('set-maxlen')) $('set-maxlen').value = s.max_message_length;
      if ($('set-retries')) $('set-retries').value = s.max_retries;
    });
  }

  function loadLocalAdmin() {
    return api('/api/local-admin').then(function (data) {
      var s = data.local_admin || {};
      rows($('local-admin-rows'), [
        ['Логин', '<code>' + escapeHtml(s.username || '-') + '</code>'],
        ['Пароль задан', s.has_password ? '<span class="ok">да</span>' : '<span class="err">нет</span>'],
        ['Вход включён', s.enabled ? '<span class="ok">да</span>' : '<span class="err">нет</span>'],
        ['Изменён', escapeHtml(String(s.updated_at || '-').replace('T', ' '))],
        ['Стартовый пароль', s.initial_password_file
          ? '<span class="warn">файл ещё существует - смените пароль</span>'
          : '<span class="ok">файл удалён</span>'],
      ]);
    }).catch(function (e) {
      rows($('local-admin-rows'), [['Ошибка', escapeHtml(e.message)]]);
    });
  }

  function loadLogs() {
    var file = $('log-file').value;
    var lines = $('log-lines').value;
    var filter = ($('log-filter').value || '').trim().toLowerCase();
    return api('/api/logs?file=' + encodeURIComponent(file) + '&lines=' + lines).then(function (data) {
      var view = $('log-view');
      if (!view) return;
      var text = data.content || '(пусто)';
      if (filter) {
        var kept = text.split('\n').filter(function (line) {
          return line.toLowerCase().indexOf(filter) >= 0;
        });
        text = kept.length ? kept.join('\n') : '(нет совпадений)';
      }
      var atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 60;
      view.textContent = text;
      if (atBottom) view.scrollTop = view.scrollHeight;
    }).catch(function (e) {
      var view = $('log-view');
      if (view) view.textContent = 'Ошибка загрузки: ' + e.message;
    });
  }

  function initFooter() {
    try {
      var nav = performance.getEntriesByType('navigation')[0];
      if (nav) {
        $('ft-ttfb').textContent = Math.round(nav.responseStart) + ' мс';
        $('ft-dcl').textContent = Math.round(nav.domContentLoadedEventEnd) + ' мс';
        $('ft-load').textContent = Math.round(nav.loadEventEnd || nav.duration) + ' мс';
      }
      $('ft-size').textContent = Math.round(document.documentElement.outerHTML.length / 1024) + ' КБ';
      var stamp = function () {
        $('ft-updated').textContent = new Date().toLocaleTimeString('ru-RU');
      };
      stamp();
      setInterval(stamp, 30000);
    } catch (e) {}
  }

  /* Обработчики разбиты по страницам: каждый вешается только там,
     где его элементы реально есть в разметке. */

  function bindDeleteButtons() {
    document.addEventListener('click', function (event) {
      var t = event.target;
      if (t.dataset && t.dataset.editChannel) {
        openChannelEditor(t.dataset.editChannel);
        return;
      }
      if (t.dataset && t.dataset.delChannel) {
        if (!confirm('Удалить канал ' + t.dataset.delChannel + '?')) return;
        api('/api/channels/' + encodeURIComponent(t.dataset.delChannel), { method: 'DELETE' })
          .then(function () { toast('Канал удалён'); return loadChannels(); })
          .catch(function (e) { toast(e.message, true); });
      }
      if (t.dataset && t.dataset.delAdmin) {
        if (!confirm('Удалить администратора ' + t.dataset.delAdmin + '?')) return;
        api('/api/admins/' + encodeURIComponent(t.dataset.delAdmin), { method: 'DELETE' })
          .then(function () { toast('Администратор удалён'); return loadAdmins(); })
          .catch(function (e) { toast(e.message, true); });
      }
      if (t.dataset && t.dataset.sort) {
        var key = t.dataset.sort;
        if (sortKey === key) sortDir = -sortDir; else { sortKey = key; sortDir = 1; }
        renderChannels();
      }
    });
  }

  function on(id, event, handler) {
    var el = $(id);
    if (el) el.addEventListener(event, handler);
  }

  var editingChannel = null;

  function openChannelEditor(name) {
    var info = channelsData[name];
    if (!info) return;
    editingChannel = name;
    $('edit-name').value = name;
    $('edit-chat-id').value = info.chat_id || '';
    $('edit-chat-title').value = info.chat_title || '';
    $('ch-edit-form').classList.remove('hidden');
    $('ch-add-form').classList.add('hidden');
    $('edit-name').focus();

    var rows = document.querySelectorAll('.channels-table tbody tr');
    rows.forEach(function (tr) {
      tr.classList.toggle('is-editing', tr.dataset.channel === name);
    });
  }

  function closeChannelEditor() {
    editingChannel = null;
    var form = $('ch-edit-form');
    if (form) form.classList.add('hidden');
    document.querySelectorAll('.channels-table tbody tr').forEach(function (tr) {
      tr.classList.remove('is-editing');
    });
  }

  function initChannelHandlers() {
    on('ch-search', 'input', function () { chPage = 0; renderChannels(); });
    on('ch-sort', 'change', function () {
      sortKey = $('ch-sort').value; chPage = 0; renderChannels();
    });
    on('ch-page-size', 'change', function () { chPage = 0; renderChannels(); });
    on('ch-prev', 'click', function () { chPage--; renderChannels(); });
    on('ch-next', 'click', function () { chPage++; renderChannels(); });

    on('ch-refresh', 'click', function () {
      loadChannels().then(function () { toast('Список обновлён'); })
        .catch(function (e) { toast(e.message, true); });
    });

    on('ch-copy', 'click', function () {
      var data = JSON.stringify(channelsData, null, 2);
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(data)
          .then(function () { toast('JSON скопирован'); })
          .catch(function () { toast('Не удалось скопировать', true); });
      } else {
        toast('Копирование доступно только по HTTPS', true);
      }
    });

    on('ch-add-toggle', 'click', function () {
      var form = $('ch-add-form');
      closeChannelEditor();
      form.classList.toggle('hidden');
      if (!form.classList.contains('hidden')) $('ch-name').focus();
    });
    on('ch-add-cancel', 'click', function () { $('ch-add-form').classList.add('hidden'); });

    on('ch-add', 'click', function () {
      var name = $('ch-name').value.trim().toLowerCase();
      var chatId = $('ch-id').value.trim();
      var title = $('ch-title').value.trim();
      if (!name || !chatId) { toast('Укажите имя канала и chat_id', true); return; }
      api('/api/channels', {
        method: 'POST',
        body: JSON.stringify({ name: name, chat_id: chatId, chat_title: title })
      }).then(function () {
        $('ch-name').value = ''; $('ch-id').value = ''; $('ch-title').value = '';
        $('ch-add-form').classList.add('hidden');
        toast('Канал добавлен');
        return loadChannels();
      }).catch(function (e) { toast(e.message, true); });
    });

    on('edit-cancel', 'click', closeChannelEditor);
    on('edit-save', 'click', function () {
      if (!editingChannel) return;
      var newName = $('edit-name').value.trim().toLowerCase();
      var chatId = $('edit-chat-id').value.trim();
      var title = $('edit-chat-title').value.trim();
      if (!newName || !chatId) { toast('Имя и chat_id обязательны', true); return; }

      var payload = { chat_id: chatId, chat_title: title };
      if (newName !== editingChannel) payload.new_name = newName;

      api('/api/channels/' + encodeURIComponent(editingChannel), {
        method: 'PUT',
        body: JSON.stringify(payload)
      }).then(function () {
        closeChannelEditor();
        toast('Канал сохранён');
        return loadChannels();
      }).catch(function (e) { toast(e.message, true); });
    });

    /* клик по chat_id — копирование в буфер */
    document.addEventListener('click', function (event) {
      var el = event.target.closest && event.target.closest('[data-copy]');
      if (!el) return;
      var value = el.getAttribute('data-copy');
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(value)
          .then(function () { toast('chat_id скопирован'); })
          .catch(function () { toast('Не удалось скопировать', true); });
      } else {
        toast(value, true);
      }
    });
  }

  function initOutboxHandlers() {
    on('outbox-flush', 'click', function () {
      api('/api/outbox?action=flush', { method: 'POST' })
        .then(function (d) {
          toast('Доставлено: ' + d.delivered + ', осталось: ' + d.left);
          return loadOutbox();
        }).catch(function (e) { toast(e.message, true); });
    });
    on('outbox-clear', 'click', function () {
      if (!confirm('Удалить все недоставленные сообщения без отправки?')) return;
      api('/api/outbox?action=clear', { method: 'POST' })
        .then(function (d) { toast('Очередь очищена: ' + d.cleared); return loadOutbox(); })
        .catch(function (e) { toast(e.message, true); });
    });
  }

  function initSendHandlers() {
    on('msg-send', 'click', function () {
      var text = $('msg-text').value.trim();
      if (!text) { toast('Введите текст', true); return; }
      api('/api/send', {
        method: 'POST',
        body: JSON.stringify({ channel: $('msg-channel').value.trim() || null, text: text })
      }).then(function (data) {
        toast('Отправлено (' + (data.latency_ms || 0) + ' мс)');
        $('msg-text').value = '';
      }).catch(function (e) { toast(e.message, true); });
    });
  }

  function initSettingsHandlers() {
    on('set-save', 'click', function () {
      api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({
          delete_messages_enabled: $('set-delete').value === 'true',
          error_delete_threshold_hours: Number($('set-delete-hours').value),
          error_history_retention_days: Number($('set-retention').value),
          max_message_length: Number($('set-maxlen').value),
          max_retries: Number($('set-retries').value)
        })
      }).then(function () { toast('Настройки сохранены'); })
        .catch(function (e) { toast(e.message, true); });
    });
  }

  function initAdminHandlers() {
    on('adm-add', 'click', function () {
      var id = $('adm-id').value.trim();
      if (!id) { toast('Укажите ID', true); return; }
      api('/api/admins', { method: 'POST', body: JSON.stringify({ user_id: id }) })
        .then(function () { $('adm-id').value = ''; toast('Администратор добавлен'); return loadAdmins(); })
        .catch(function (e) { toast(e.message, true); });
    });
  }

  function initLocalAdminHandlers() {
    on('la-save', 'click', function () {
      var current = $('la-current').value;
      var next = $('la-new').value;
      var repeat = $('la-new2').value;
      if (!current || !next) { toast('Заполните все поля', true); return; }
      if (next !== repeat) { toast('Пароли не совпадают', true); return; }
      api('/api/local-admin', {
        method: 'POST',
        body: JSON.stringify({ current_password: current, new_password: next })
      }).then(function () {
        $('la-current').value = ''; $('la-new').value = ''; $('la-new2').value = '';
        toast('Пароль изменён');
        return loadLocalAdmin();
      }).catch(function (e) { toast(e.message, true); });
    });
  }

  function initLogHandlers() {
    on('log-reload', 'click', loadLogs);
    on('log-file', 'change', loadLogs);
    on('log-lines', 'change', loadLogs);
    var filterTimer = null;
    on('log-filter', 'input', function () {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(loadLogs, 250);
    });
    on('log-auto', 'change', function () {
      if (logTimer) { clearInterval(logTimer); logTimer = null; }
      if ($('log-auto').checked) logTimer = setInterval(loadLogs, 5000);
    });
  }

  /* Какие разделы инициализировать: главная — состояние и логи,
     остальные страницы объявляют себя через window.__PAGE__. */
  function pageTasks() {
    var page = window.__PAGE__ || 'index';
    if (page === 'channels') return { channels: true };
    if (page === 'outbox') return { outbox: true };
    if (page === 'send') return { send: true };
    if (page === 'settings') return { settings: true };
    if (page === 'admins') return { admins: true };
    if (page === 'local-admin') return { localAdmin: true };
    return { status: true, logs: true };
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(document.documentElement.getAttribute('data-theme') || 'light');
    initUserMenu();
    initFooter();
    bindDeleteButtons();

    var tasks = pageTasks();

    on('btn-refresh', 'click', function () {
      var spinner = $('dashboard-spinner');
      if (spinner) spinner.classList.remove('hidden');
      loadStatus();
    });

    loadMe().then(function () {
      if (tasks.status) {
        loadStatus();
        setInterval(loadStatus, 5000);
      }
      if (tasks.logs) {
        loadLogs();
        logTimer = setInterval(loadLogs, 5000);
      }
      if (tasks.channels) {
        initChannelHandlers();
        loadChannels().catch(function () {});
      }
      if (tasks.outbox) {
        initOutboxHandlers();
        loadOutbox().catch(function () {});
        setInterval(loadOutbox, 5000);
      }
      if (tasks.send) initSendHandlers();
      if (tasks.settings) {
        initSettingsHandlers();
        loadSettings().catch(function () {});
      }
      if (tasks.admins) {
        initAdminHandlers();
        loadAdmins().catch(function () {});
      }
      if (tasks.localAdmin) {
        initLocalAdminHandlers();
        loadLocalAdmin().catch(function () {});
      }
      if (tasks.logs) initLogHandlers();
    });
  });
})();
"""