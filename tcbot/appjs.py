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



  // ---------------------------------------------------------------- графики

  var ChartColors = {
    pad: { top: 12, right: 12, bottom: 20, left: 40 }
  };

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function hexToRgba(color, alpha) {
    var c = String(color).trim();
    if (c.charAt(0) === '#') {
      var hex = c.slice(1);
      if (hex.length === 3) {
        hex = hex.split('').map(function (ch) { return ch + ch; }).join('');
      }
      var num = parseInt(hex, 16);
      return 'rgba(' + ((num >> 16) & 255) + ',' + ((num >> 8) & 255) + ',' + (num & 255) + ',' + alpha + ')';
    }
    return c;
  }

  /* Рисует линейный график: без библиотек и CDN. */
  function drawLine(canvas, points, opts) {
    if (!canvas) return;
    var o = opts || {};
    var field = o.field;
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(120, rect.width || canvas.clientWidth || 300);
    var h = o.height || 110;

    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.height = h + 'px';

    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var values = (points || []).map(function (p) {
      return { ts: p.ts, label: p.label, v: p[field] };
    }).filter(function (p) {
      return typeof p.v === 'number' && isFinite(p.v);
    });

    var colorLine = o.color || cssVar('--aq-primary', '#1f4e8c');
    var colorGrid = cssVar('--border-light', '#dde3ea');
    var colorText = cssVar('--text-dim', '#8a96a3');
    var P = ChartColors.pad;
    var plotW = w - P.left - P.right;
    var plotH = h - P.top - P.bottom;

    if (!values.length) {
      ctx.fillStyle = colorText;
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(o.emptyText || 'Нет данных', w / 2, h / 2);
      return;
    }

    var nums = values.map(function (p) { return p.v; });
    var min = Math.min.apply(null, nums);
    var max = Math.max.apply(null, nums);
    if (min === max) { min = min - 1; max = max + 1; }
    var pad = (max - min) * 0.1;
    min -= pad; max += pad;
    if (min < 0 && nums.every(function (v) { return v >= 0; })) min = 0;

    function x(i) { return P.left + (values.length === 1 ? plotW / 2 : (i / (values.length - 1)) * plotW); }
    function y(v) { return P.top + plotH - ((v - min) / (max - min)) * plotH; }

    ctx.strokeStyle = colorGrid;
    ctx.fillStyle = colorText;
    ctx.font = '10px sans-serif';
    ctx.lineWidth = 1;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    var steps = 4;
    for (var s = 0; s <= steps; s++) {
      var val = min + ((max - min) * s) / steps;
      var py = y(val);
      ctx.beginPath();
      ctx.moveTo(P.left, py);
      ctx.lineTo(w - P.right, py);
      ctx.stroke();
      ctx.fillText(o.formatY ? o.formatY(val) : Math.round(val), P.left - 6, py);
    }

    var grad = ctx.createLinearGradient(0, P.top, 0, P.top + plotH);
    grad.addColorStop(0, hexToRgba(colorLine, 0.25));
    grad.addColorStop(1, hexToRgba(colorLine, 0.02));

    ctx.beginPath();
    ctx.moveTo(x(0), y(values[0].v));
    for (var i = 1; i < values.length; i++) {
      var px = x(i), pyv = y(values[i].v);
      var ppx = x(i - 1), ppy = y(values[i - 1].v);
      var cx = (ppx + px) / 2;
      ctx.bezierCurveTo(cx, ppy, cx, pyv, px, pyv);
    }
    var linePath = ctx.strokeStyle;
    ctx.save();
    ctx.lineTo(x(values.length - 1), P.top + plotH);
    ctx.lineTo(x(0), P.top + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.restore();

    ctx.beginPath();
    ctx.moveTo(x(0), y(values[0].v));
    for (var j = 1; j < values.length; j++) {
      var nx = x(j), ny = y(values[j].v);
      var bx = (x(j - 1) + nx) / 2;
      ctx.bezierCurveTo(bx, y(values[j - 1].v), bx, ny, nx, ny);
    }
    ctx.strokeStyle = colorLine;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    ctx.fillStyle = colorText;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(values[0].label || '', P.left, h - P.bottom + 5);
    ctx.textAlign = 'right';
    ctx.fillText(values[values.length - 1].label || '', w - P.right, h - P.bottom + 5);
  }

  function loadCharts() {
    var hours = ($('charts-hours') || {}).value || 24;
    return api('/api/metrics?kind=history&hours=' + hours).then(function (data) {
      var points = data.points || [];
      var hasData = points.some(function (p) { return p.sent || p.queued || p.restarts || p.ws; });

      var empty = $('charts-empty');
      if (empty) empty.style.display = hasData ? 'none' : '';

      var status = $('charts-status');
      if (status) status.textContent = 'за ' + (data.hours || hours) + ' ч';

      var last = points.length ? points[points.length - 1] : {};
      if ($('cv-sent')) $('cv-sent').textContent = last.sent || 0;
      if ($('cv-queue')) $('cv-queue').textContent = last.queued || 0;
      if ($('cv-ws')) $('cv-ws').textContent = (last.ws == null ? '—' : last.ws + '%');
      if ($('cv-restarts')) $('cv-restarts').textContent = last.restarts || 0;

      drawLine($('chart-sent'), points, { field: 'sent', color: cssVar('--aq-primary', '#1f4e8c') });
      drawLine($('chart-queue'), points, { field: 'queued', color: cssVar('--warn', '#b26a00') });
      drawLine($('chart-ws'), points, { field: 'ws', color: cssVar('--ok', '#2e7d32'), formatY: function (v) { return Math.round(v) + '%'; } });
      drawLine($('chart-restarts'), points, { field: 'restarts', color: cssVar('--err', '#c62828') });
    }).catch(function () { /* графики не критичны */ });
  }

  // ---------------------------------------------------------------- календарь

  var AW_WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];
  var AW_MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var AW_PALETTE = ['#4c8dff', '#2fb37a', '#e8a33d', '#d9534f', '#8e6cd4',
                    '#17a2b8', '#c2410c', '#65a30d', '#db2777', '#0891b2'];
  var awDays = [];
  var awOffset = 0;
  var awMaxOffset = 0;
  var awColors = {};
  var awSeq = 0;

  function awColor(name) {
    if (!awColors[name]) {
      awColors[name] = AW_PALETTE[awSeq % AW_PALETTE.length];
      awSeq++;
    }
    return awColors[name];
  }

  function awYmd(d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function awMonday(dateStr) {
    var d = new Date(dateStr + 'T00:00:00');
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d;
  }

  function awWeek(shift) {
    if (!awDays.length) return [];
    var byDate = {};
    awDays.forEach(function (d) { byDate[d.date] = d; });

    var withData = awDays.filter(function (d) { return d.count > 0; });
    if (!withData.length) return [];

    var anchor = awMonday(withData[withData.length - 1].date);
    anchor.setDate(anchor.getDate() - shift * 7);

    var out = [];
    for (var i = 0; i < 7; i++) {
      var d = new Date(anchor);
      d.setDate(anchor.getDate() + i);
      var key = awYmd(d);
      out.push(byDate[key] || { date: key, count: 0, by_channel: [] });
    }
    return out;
  }

  function awLabel(days) {
    if (!days.length) return '';
    var a = new Date(days[0].date + 'T00:00:00');
    var b = new Date(days[6].date + 'T00:00:00');
    if (a.getMonth() === b.getMonth()) {
      return a.getDate() + '–' + b.getDate() + ' ' + AW_MONTHS[a.getMonth()];
    }
    return a.getDate() + ' ' + AW_MONTHS[a.getMonth()] + ' – ' + b.getDate() + ' ' + AW_MONTHS[b.getMonth()];
  }

  function awTipHtml(day) {
    var dt = new Date(day.date + 'T00:00:00');
    var wd = AW_WEEKDAYS[(dt.getDay() + 6) % 7];
    var html = '<div class="aw-tip-head">' + escapeHtml(day.date) + ' · ' + wd + '<br>' +
      '<strong>' + (day.count || 0) + '</strong> ' +
      ((day.count === 1) ? 'уведомление' : 'уведомлений') + '</div>';

    var list = day.by_channel || [];
    if (list.length) {
      html += '<div class="aw-tip-list">' + list.slice(0, 8).map(function (item) {
        return '<div class="aw-tip-row">' +
          '<i class="aw-tip-dot" style="background:' + awColor(item.name) + '"></i>' +
          '<span class="aw-tip-uid">' + escapeHtml(item.name) + '</span>' +
          '<span class="aw-tip-cnt">' + item.count + '</span></div>';
      }).join('') + '</div>';
    } else {
      html += '<div class="aw-tip-empty">нет уведомлений</div>';
    }
    return html;
  }

  function renderCalendar() {
    var root = $('activity-week');
    if (!root) return;
    var days = awWeek(awOffset);
    if (!days.length) { root.innerHTML = ''; return; }

    var max = Math.max.apply(null, days.map(function (d) { return d.count || 0; }).concat([0]));
    var H = 30;

    var cols = days.map(function (day) {
      var dt = new Date(day.date + 'T00:00:00');
      var wd = AW_WEEKDAYS[(dt.getDay() + 6) % 7];
      var h = max ? Math.max(3, Math.round(((day.count || 0) / max) * H)) : 3;
      var list = day.by_channel || [];

      var bar;
      if (list.length > 1) {
        var segs = list.map(function (item) {
          var seg = Math.max(1, Math.round((item.count / (day.count || 1)) * h));
          return '<i class="aw-seg" style="height:' + seg + 'px;background:' + awColor(item.name) + '"></i>';
        }).join('');
        bar = '<span class="aw-stack" style="height:' + h + 'px">' + segs + '</span>';
      } else {
        var color = list.length ? awColor(list[0].name) : 'var(--border-light)';
        bar = '<span class="aw-stack" style="height:' + h + 'px">' +
              '<i class="aw-seg" style="height:' + h + 'px;background:' + color + '"></i></span>';
      }

      return '<span class="aw-col" data-tip="' + escapeHtml(awTipHtml(day)) + '">' +
             bar + '<em class="aw-lbl">' + wd + '</em></span>';
    }).join('');

    root.innerHTML =
      '<div class="aw-chart">' + cols + '</div>' +
      '<div class="aw-nav">' +
        '<button type="button" class="am-btn" data-nav="-1"' +
          (awOffset < awMaxOffset ? '' : ' disabled') + ' title="предыдущая неделя">‹</button>' +
        '<span class="aw-period">' + escapeHtml(awLabel(days)) + '</span>' +
        '<button type="button" class="am-btn" data-nav="1"' +
          (awOffset > 0 ? '' : ' disabled') + ' title="следующая неделя">›</button>' +
      '</div>';

    root.querySelectorAll('.am-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.disabled) return;
        awOffset += parseInt(b.getAttribute('data-nav'), 10);
        awOffset = Math.max(0, Math.min(awOffset, awMaxOffset));
        renderCalendar();
      });
    });
  }

  function loadCalendar() {
    return api('/api/metrics?kind=days&limit=365').then(function (data) {
      awDays = data.days || [];
      var withData = awDays.filter(function (d) { return d.count > 0; });
      if (withData.length) {
        var first = awMonday(withData[0].date);
        var last = awMonday(withData[withData.length - 1].date);
        awMaxOffset = Math.max(0, Math.round((last - first) / (7 * 86400000)));
      } else {
        awMaxOffset = 0;
      }
      if (awOffset > awMaxOffset) awOffset = awMaxOffset;
      renderCalendar();
    }).catch(function () {});
  }

  var awTip = null;

  function awShowTip(el) {
    var html = el.getAttribute('data-tip');
    if (!html) return;
    if (!awTip) {
      awTip = document.createElement('div');
      awTip.className = 'aw-tip';
      document.body.appendChild(awTip);
    }
    awTip.innerHTML = html;
    awTip.style.display = 'block';

    var r = el.getBoundingClientRect();
    var tw = awTip.offsetWidth, th = awTip.offsetHeight;
    var left = Math.max(8, Math.min(r.left + r.width / 2 - tw / 2, window.innerWidth - tw - 8));
    var top = r.top - th - 8;
    if (top < 8) top = r.bottom + 8;
    awTip.style.left = left + 'px';
    awTip.style.top = top + 'px';
  }

  function awHideTip() {
    if (awTip) awTip.style.display = 'none';
  }

  // ---------------------------------------------------------------- диагностика

  function fmtTimestamp(ms) {
    if (!ms) return '—';
    try {
      return new Date(Number(ms)).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
      });
    } catch (e) { return '—'; }
  }

  function loadDiagnostics() {
    return Promise.all([
      api('/api/diagnostics?part=identity').catch(function (e) { return { data: { error: e.message } }; }),
      api('/api/diagnostics?part=limits').catch(function (e) { return { data: { error: e.message } }; }),
      api('/api/diagnostics?part=channels').catch(function (e) { return { data: { error: e.message, items: [] } }; }),
      api('/api/diagnostics?part=chats').catch(function (e) { return { data: { error: e.message, chats: [] } }; }),
    ]).then(function (results) {
      renderDiagIdentity(results[0].data);
      renderDiagLimits(results[1].data);
      renderDiagChannels(results[2].data);
      renderDiagChats(results[3].data);
    });
  }

  function renderDiagIdentity(data) {
    if (!data || !data.available) {
      rows($('diag-identity'), [['Состояние', '<span class="err">' + escapeHtml((data && data.error) || 'бот не запущен') + '</span>']]);
      return;
    }
    var health = data.health || {};
    rows($('diag-identity'), [
      ['ID бота', '<code>' + escapeHtml(data.me_id || '—') + '</code>'],
      ['Сервер', escapeHtml(data.server_name || '—')],
      ['Версия сервера', escapeHtml(data.server_version || '—')],
      ['Состояние', health.status === 'authorized'
        ? '<span class="ok">авторизован</span>'
        : '<span class="warn">' + escapeHtml(health.status || '—') + '</span>'],
      ['WebSocket', health.websocket_connected ? '<span class="ok">подключён</span>' : '<span class="err">нет</span>'],
      ['Порт', escapeHtml(String(health.port || '—'))],
    ]);
  }

  function renderDiagLimits(data) {
    if (!data || !data.available) {
      rows($('diag-limits'), [['Состояние', '<span class="dim">' + escapeHtml((data && data.error) || 'недоступно') + '</span>']]);
      return;
    }
    var ext = (data.extensions || []).join(', ') || '—';
    rows($('diag-limits'), [
      ['Макс. размер файла', data.max_size_mb ? data.max_size_mb + ' МБ' : '—'],
      ['Режим расширений', escapeHtml(data.extensions_mode || '—')],
      ['Расширения', '<code>' + escapeHtml(ext) + '</code>'],
    ]);
  }

  function renderDiagChannels(data) {
    var body = $('diag-channels');
    if (!body) return;
    var items = (data && data.items) || [];
    var problems = (data && data.problems) || 0;

    var badge = $('diag-ch-problems');
    if (badge) {
      badge.textContent = problems;
      badge.className = 'badge badge-count' + (problems ? ' badge-warn' : '');
    }

    var summary = $('diag-ch-summary');
    if (summary && data) {
      var parts = ['всего: ' + (data.total || 0)];
      if (data.inspected != null) parts.push('проверено: ' + data.inspected);
      if (data.skipped) parts.push('не успели: ' + data.skipped);
      if (data.cached) parts.push('из кэша: ' + data.cached);
      summary.textContent = parts.join(' · ');
    }

    if (!items.length) {
      body.innerHTML = '<tr><td colspan="6"><div class="empty-cell">' +
        (data && data.error ? escapeHtml(data.error) : 'каналов нет') + '</div></td></tr>';
      return;
    }

    body.innerHTML = items.map(function (item) {
      var skipped = (item.reason || '').indexOf('не проверен') === 0 ||
                    (item.reason || '').indexOf('не проверялся') === 0;
      var broken = !item.ok && !skipped;
      var style = broken ? ' style="background:var(--err-bg)"'
                : (skipped ? ' style="opacity:.55"' : '');
      var botCell = item.bot_is_member === true
        ? '<span class="ok">участник</span>' + (item.bot_role ? ' <span class="dim fs-11">(' + escapeHtml(item.bot_role) + ')</span>' : '')
        : (item.bot_is_member === false ? '<span class="err">нет</span>' : '<span class="dim">—</span>');
      return '<tr' + style + '>' +
        '<td><strong>' + escapeHtml(item.name) + '</strong></td>' +
        '<td>' + (item.title
          ? escapeHtml(item.title)
          : '<span class="dim mono">' + escapeHtml(String(item.chat_id).slice(0, 16)) + '…</span>') + '</td>' +
        '<td class="fs-12">' + escapeHtml(item.chat_type || '—') + '</td>' +
        '<td class="fs-12">' + (item.participants || 0) + '</td>' +
        '<td class="fs-12">' + botCell + '</td>' +
        '<td class="fs-12 ' + (broken ? 'err' : 'dim') + '">' + escapeHtml(item.reason || '') + '</td>' +
        '</tr>';
    }).join('');
  }

  function renderDiagChats(data) {
    var body = $('diag-chats');
    if (!body) return;
    var chats = (data && data.chats) || [];
    var count = $('diag-chats-count');
    if (count) count.textContent = chats.length;

    body.innerHTML = chats.length ? chats.map(function (chat) {
      return '<tr>' +
        '<td>' + escapeHtml(chat.title || '<без названия>') + '</td>' +
        '<td class="mono dim fs-12">' + escapeHtml(String(chat.chat_id).slice(0, 20)) + '…</td>' +
        '<td class="fs-12">' + escapeHtml(chat.chat_type || '—') + '</td>' +
        '<td class="fs-12">' + (chat.unread || 0) + '</td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="4"><div class="empty-cell">' +
        (data && data.error ? escapeHtml(data.error) : 'чатов нет') + '</div></td></tr>';
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

  function initDiagnosticsHandlers() {
    on('diag-refresh', 'click', function () {
      loadDiagnostics().then(function () { toast('Данные обновлены'); })
        .catch(function (e) { toast(e.message, true); });
    });
    /* Полная перепроверка каналов в обход кэша */
    on('diag-recheck', 'click', function () {
      api('/api/diagnostics?part=channels&fresh=1&budget=40')
        .then(function (result) {
          renderDiagChannels(result.data);
          toast('Каналы проверены заново');
        })
        .catch(function (e) { toast(e.message, true); });
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
    if (page === 'diagnostics') return { diagnostics: true };
    return { status: true, logs: true, charts: true, calendar: true };
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

    document.addEventListener('mouseover', function (e) {
      var el = e.target.closest && e.target.closest('.aw-col[data-tip]');
      if (el) awShowTip(el);
    });
    document.addEventListener('mouseout', function (e) {
      var el = e.target.closest && e.target.closest('.aw-col[data-tip]');
      if (el) awHideTip();
    });
    window.addEventListener('scroll', awHideTip, true);

    var resizeTimer = null;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () { loadCharts(); }, 250);
    });

    loadMe().then(function () {
      if (tasks.status) {
        loadStatus();
        setInterval(loadStatus, 5000);
      }
      if (tasks.charts) {
        on('charts-hours', 'change', loadCharts);
        loadCharts();
        setInterval(loadCharts, 60000);
      }
      if (tasks.calendar) {
        loadCalendar();
        setInterval(loadCalendar, 300000);
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
      if (tasks.diagnostics) {
        initDiagnosticsHandlers();
        loadDiagnostics();
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