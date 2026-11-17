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

    var serviceRestart = $('menu-service-restart');
    if (serviceRestart) {
      // Кнопку показываем только когда перезапуск разрешён в настройках
      api('/api/service/status').then(function (data) {
        if (data && data.restart_enabled) {
          serviceRestart.style.display = '';
          // В контейнере перезапуск идёт через перезапуск самого контейнера
          serviceRestart.title = data.mode === 'exit'
            ? 'перезапуск контейнера'
            : 'systemctl restart ' + (data.service || '');
        }
      }).catch(function () { /* сервисное управление недоступно */ });

      serviceRestart.addEventListener('click', function () {
        menu.classList.remove('is-open');
        var what = serviceRestart.title;
        if (!confirm('Перезапустить бота (' + what + ')?\n\nПанель будет недоступна несколько секунд.')) {
          return;
        }
        api('/api/service/restart', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm: 'restart' })
        })
          .then(function () {
            toast('Служба перезапускается — обновите страницу через 10 секунд');
          })
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

  var globalIncidentMode = 'notify';

  /* Подпись режима инцидентов для канала */
  var INCIDENT_MODE_SHORT = {
    notify: 'учесть',
    delete: 'удалить',
    resolve: 'решено',
    both: 'удалить + решено'
  };

  var INCIDENT_MODE_FULL = {
    notify: 'только учесть',
    delete: 'удалить проблему',
    resolve: 'прислать «решено»',
    both: 'удалить и прислать'
  };

  function channelModeCell(info) {
    var own = info.incident_mode;
    if (own) {
      return '<span class="ch-mode own" title="Своя настройка канала">' +
        escapeHtml(INCIDENT_MODE_SHORT[own] || own) + '</span>';
    }
    return '<span class="ch-mode inherits" title="Как в общих настройках">' +
      escapeHtml(INCIDENT_MODE_SHORT[globalIncidentMode] || globalIncidentMode) +
      '&nbsp;<span class="dim fs-11">↳</span></span>';
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
        '<td>' + channelModeCell(info) + '</td>' +
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
    }).join('') : '<tr><td colspan="6"><div class="empty-cell">' +
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
      globalIncidentMode = data.incident_mode || 'notify';
      var def = $('default-chat');
      if (def) def.textContent = data.default_chat || 'не задан';

      var usage = $('dc-usage');
      if (usage && data.default_chat) {
        var used = 0;
        Object.keys(data.channels || {}).forEach(function (name) {
          if ((data.channels[name] || {}).chat_id === data.default_chat) used++;
        });
        usage.textContent = used ? '(' + used + ' канал(ов) ведут сюда)' : '';
      }
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
      if ($('set-incident-mode')) {
        $('set-incident-mode').value = s.incident_mode || 'notify';
        updateIncidentModeHint();
      }
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
    if ($('edit-incident-mode')) {
      $('edit-incident-mode').value = info.incident_mode || '';
    }
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
      // Пустая строка = наследовать глобальный режим
      payload.incident_mode = ($('edit-incident-mode') || {}).value || '';

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

  /* Высота графика берётся из CSS-переменной --chart-h,
     чтобы канвас и блок статусов были ровно одной высоты. */
  function chartHeight(fallback) {
    var raw = cssVar('--chart-h', '').trim();
    var value = parseInt(raw, 10);
    return isFinite(value) && value > 0 ? value : (fallback || 110);
  }

  /* Рисует линейный график: без библиотек и CDN. */
  function drawLine(canvas, points, opts) {
    if (!canvas) return;
    var o = opts || {};
    var field = o.field;
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(120, rect.width || canvas.clientWidth || 300);
    var h = o.height || chartHeight(110);

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

  /* Столбчатая диаграмма по каналам: подписи снизу, значения сверху. */
  /* Столбчатая диаграмма по каналам: столбик делится на проблемы (красное)
     и решения (зелёное), чтобы видеть не только объём, но и соотношение. */
  function drawBars(canvas, items, opts) {
    if (!canvas) return;
    var o = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(200, rect.width || canvas.clientWidth || 400);
    var h = o.height || chartHeight(110);

    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.height = h + 'px';

    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var colorText = cssVar('--text-dim', '#8a96a3');
    var colorPrimary = o.color || cssVar('--aq-primary', '#1f4e8c');
    var colorProblem = cssVar('--err', '#c62828');
    var colorResolved = cssVar('--ok', '#2e7d32');
    var colorGrid = cssVar('--border-light', '#dde3ea');

    var data = (items || []).slice(0, o.limit || 10);
    if (!data.length) {
      ctx.fillStyle = colorText;
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(o.emptyText || 'Нет данных за период', w / 2, h / 2);
      return;
    }

    var data0 = data;
    var padTop = 18, padSide = 8;
    var padBottom = data0.length > 16 ? Math.min(78, 18 + data0.length * 2.4) : 34;
    var plotH = h - padTop - padBottom;

    // Для раскраски считаем максимум по проблемам и решениям отдельно,
    // чтобы соотношение было видно при любом объёме
    var max = Math.max.apply(null, data.map(function (d) { return d.count; }).concat([1]));
    var slot = (w - padSide * 2) / data.length;
    var barW = Math.max(6, Math.min(o.barWidth || 46, slot * 0.68));

    // Горизонтальная сетка с подписями количества — без неё не понять масштаб
    ctx.strokeStyle = colorGrid;
    ctx.lineWidth = 1;
    ctx.font = '10px sans-serif';
    ctx.fillStyle = colorText;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    var steps = 4;
    for (var s = 0; s <= steps; s++) {
      var level = (max * s) / steps;
      var gy = padTop + plotH - (level / max) * plotH;
      ctx.beginPath();
      ctx.moveTo(padSide, gy);
      ctx.lineTo(w - padSide, gy);
      ctx.stroke();
      ctx.fillText(String(Math.round(level)), padSide + 26, gy);
    }

    data.forEach(function (item, i) {
      var hasSplit = (item.problem != null || item.resolved != null);
      var problem = item.problem || 0;
      var resolved = item.resolved || 0;
      var totalForSplit = problem + resolved;

      var bh = Math.max(2, (item.count / max) * plotH);
      var x = padSide + slot * i + (slot - barW) / 2;
      var y = padTop + plotH - bh;

      if (hasSplit && totalForSplit > 0) {
        // Делим столбик: снизу проблемы, сверху решения
        var hp = Math.round((problem / totalForSplit) * bh);
        var hr = bh - hp;

        if (hp > 0) {
          var gradP = ctx.createLinearGradient(0, y + hr, 0, y + bh);
          gradP.addColorStop(0, colorProblem);
          gradP.addColorStop(1, hexToRgba(colorProblem, 0.65));
          ctx.fillStyle = gradP;
          ctx.beginPath();
          if (ctx.roundRect) {
            ctx.roundRect(x, y + hr, barW, bh - hr, hr > 0 ? 0 : 3);
          } else {
            ctx.rect(x, y + hr, barW, bh - hr);
          }
          ctx.fill();
        }
        if (hr > 0) {
          var gradR = ctx.createLinearGradient(0, y, 0, y + hr);
          gradR.addColorStop(0, colorResolved);
          gradR.addColorStop(1, hexToRgba(colorResolved, 0.65));
          ctx.fillStyle = gradR;
          ctx.beginPath();
          if (ctx.roundRect) {
            ctx.roundRect(x, y, barW, hr, 3);
          } else {
            ctx.rect(x, y, barW, hr);
          }
          ctx.fill();
        }
      } else {
        var grad = ctx.createLinearGradient(0, y, 0, padTop + plotH);
        grad.addColorStop(0, colorPrimary);
        grad.addColorStop(1, hexToRgba(colorPrimary, 0.35));
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.roundRect ? ctx.roundRect(x, y, barW, bh, 3) : ctx.rect(x, y, barW, bh);
        ctx.fill();
      }

      // Значение над столбиком
      ctx.fillStyle = colorPrimary;
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(String(item.count), x + barW / 2, y - 2);

      // Подпись канала снизу. При большом числе столбиков поворачиваем —
      // иначе подписи наезжают друг на друга и читать невозможно.
      var label = String(item.name || '');
      var maxChars = data.length > 16 ? 14 : 11;
      if (label.length > maxChars) label = label.slice(0, maxChars - 1) + '…';

      ctx.fillStyle = colorText;
      ctx.font = '10px sans-serif';
      var baseY = padTop + plotH + 6;

      if (data.length > 16) {
        ctx.save();
        ctx.translate(x + barW / 2, baseY);
        ctx.rotate(-Math.PI / 4);
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, 0, 0);
        ctx.restore();
      } else {
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(label, x + barW / 2, baseY);
      }
    });
  }

  function loadCharts() {
    var hours = ($('charts-hours') || {}).value || 24;
    return api('/api/metrics?kind=history&hours=' + hours).then(function (data) {
      var points = data.points || [];
      var hasData = points.some(function (p) {
        return p.sent || p.failed || p.queued || p.restarts || (p.ws != null);
      });

      var empty = $('charts-empty');
      if (empty) empty.style.display = hasData ? 'none' : '';

      var status = $('charts-status');
      if (status) status.textContent = 'за ' + (data.hours || hours) + ' ч';

      // --- Показатели цифрами: почти статичные величины не рисуем графиком ---
      var channels = data.channels || [];
      var total = channels.reduce(function (sum, c) { return sum + c.count; }, 0);

      var sentTotal = points.reduce(function (s, p) { return s + (p.sent || 0); }, 0);
      var failedTotal = points.reduce(function (s, p) { return s + (p.failed || 0); }, 0);
      var attempts = sentTotal + failedTotal;
      var rate = attempts ? (sentTotal / attempts * 100) : null;

      var latencies = points.filter(function (p) { return p.latency != null; });
      var avgLatency = latencies.length
        ? latencies.reduce(function (s, p) { return s + p.latency; }, 0) / latencies.length
        : null;

      var last = points.length ? points[points.length - 1] : {};
      var maxQueue = points.reduce(function (m, p) { return Math.max(m, p.queued || 0); }, 0);

      if ($('st-sent')) $('st-sent').textContent = sentTotal;
      if ($('st-failed')) $('st-failed').textContent = failedTotal;
      if ($('st-rate')) {
        $('st-rate').textContent = rate == null ? '—' : rate.toFixed(1) + '%';
        $('st-rate').className = 'stat-value ' +
          (rate == null ? '' : (rate >= 99 ? 'ok' : (rate >= 90 ? 'warn' : 'err')));
      }
      if ($('st-latency')) {
        $('st-latency').textContent = avgLatency == null
          ? '—' : Math.round(avgLatency * 1000) + ' мс';
      }
      if ($('st-queue')) {
        $('st-queue').textContent = maxQueue;
        $('st-queue').className = 'stat-value ' + (maxQueue > 0 ? 'warn' : 'ok');
      }
      if ($('st-ws')) {
        var wsNow = last.ws;
        $('st-ws').textContent = wsNow == null ? '—' : wsNow + '%';
        $('st-ws').className = 'stat-value ' +
          (wsNow == null ? '' : (wsNow >= 99 ? 'ok' : (wsNow >= 80 ? 'warn' : 'err')));
      }

      // --- Отправлено и отказы ---
      if ($('cv-sent')) {
        $('cv-sent').textContent = sentTotal + (failedTotal ? ' / ' + failedTotal : '');
      }
      drawLine($('chart-sent'), points, {
        field: 'sent', color: cssVar('--aq-primary', '#1f4e8c')
      });

      // --- Задержка доставки ---
      if ($('cv-latency')) {
        $('cv-latency').textContent = avgLatency == null
          ? '—' : Math.round(avgLatency * 1000) + ' мс';
      }
      drawLine($('chart-latency'), points, {
        field: 'latency',
        color: cssVar('--warn', '#b26a00'),
        formatY: function (v) { return Math.round(v * 1000) + 'мс'; },
        emptyText: 'Нет замеров'
      });

      // --- Статусы и строгость ---
      renderStatusBars(data.statuses || []);

      // --- Очередь ---
      if ($('cv-queue')) $('cv-queue').textContent = maxQueue;
      drawLine($('chart-queue'), points, {
        field: 'queued', color: cssVar('--warn', '#b26a00')
      });
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

  // ---------------------------------------------------------------- резервные копии

  var bkItems = [];

  function fmtSize(bytes) {
    if (!bytes || bytes < 0) return '\u2014';
    var units = ['Б', 'КБ', 'МБ', 'ГБ'];
    var n = bytes, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(n < 10 && i > 0 ? 1 : 0) + ' ' + units[i];
  }

  function fmtDateTime(ts) {
    if (!ts) return '\u2014';
    var d = new Date(ts * 1000);
    function pad(v) { return String(v).padStart(2, '0'); }
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() +
           ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function renderBackups(stats, items) {
    bkItems = items || [];

    var count = $('bk-count');
    if (count) count.textContent = bkItems.length;
    if ($('bk-keep') && stats) $('bk-keep').textContent = stats.keep;

    var totals = $('bk-totals');
    if (totals && stats) {
      var cells = [
        { value: stats.count, label: 'копий' },
        { value: fmtSize(stats.total_size), label: 'всего' },
        { value: stats.keep, label: 'хранится' },
        { value: stats.enabled ? 'вкл' : 'выкл', label: 'автокопии',
          cls: stats.enabled ? 'ok' : 'err' }
      ];
      totals.innerHTML = cells.map(function (c) {
        return '<div class="cs-total">' +
          '<div class="cs-total-value ' + (c.cls || '') + '">' + c.value + '</div>' +
          '<div class="cs-total-label">' + c.label + '</div></div>';
      }).join('');
    }

    var body = $('bk-rows');
    if (!body) return;

    if (!bkItems.length) {
      body.innerHTML = '<tr><td colspan="5"><div class="empty-cell">' +
        'копий пока нет \u2014 создайте первую кнопкой выше</div></td></tr>';
      return;
    }

    body.innerHTML = bkItems.map(function (item) {
      var content = [];
      if (item.channels != null) content.push(item.channels + ' каналов');
      if (item.admins != null) content.push(item.admins + ' админ.');
      return '<tr>' +
        '<td><code class="mono fs-12">' + escapeHtml(item.name) + '</code></td>' +
        '<td class="cs-num">' + fmtSize(item.size) + '</td>' +
        '<td class="dim fs-12">' + fmtDateTime(item.created_at) + '</td>' +
        '<td class="dim fs-12">' + (content.join(' \u00b7 ') || '\u2014') + '</td>' +
        '<td class="actions-cell">' +
          '<button type="button" class="secondary small" data-restore="' +
            escapeHtml(item.name) + '">Восстановить</button> ' +
          '<button type="button" class="secondary small danger" data-delete="' +
            escapeHtml(item.name) + '">Удалить</button>' +
        '</td>' +
        '</tr>';
    }).join('');

    body.querySelectorAll('[data-restore]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var name = btn.getAttribute('data-restore');
        if (!confirm('Восстановить состояние из ' + name + '?\n\n' +
                     'Текущее состояние будет сохранено в отдельную копию. ' +
                     'После восстановления потребуется перезапуск бота.')) {
          return;
        }
        api('/api/backups/' + encodeURIComponent(name) + '/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm: 'restore' })
        })
          .then(function (result) {
            toast('Восстановлено: ' + result.channels + ' каналов');
            loadBackups();
          })
          .catch(function (e) { toast(e.message, true); });
      });
    });

    body.querySelectorAll('[data-delete]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var name = btn.getAttribute('data-delete');
        if (!confirm('Удалить копию ' + name + '?')) return;
        api('/api/backups/' + encodeURIComponent(name), { method: 'DELETE' })
          .then(function () { toast('Копия удалена'); loadBackups(); })
          .catch(function (e) { toast(e.message, true); });
      });
    });
  }

  function loadBackups() {
    return api('/api/backups').then(function (data) {
      renderBackups(data.stats || {}, data.items || []);
    }).catch(function (e) {
      var body = $('bk-rows');
      if (body) {
        body.innerHTML = '<tr><td colspan="5"><div class="empty-cell">' +
          escapeHtml(e.message) + '</div></td></tr>';
      }
    });
  }

  function initBackupHandlers() {
    on('bk-refresh', 'click', function () {
      loadBackups().then(function () { toast('Список обновлён'); });
    });
    on('bk-create', 'click', function () {
      api('/api/backups', { method: 'POST' })
        .then(function (r) {
          toast('Копия создана: ' + r.file);
          loadBackups();
        })
        .catch(function (e) { toast(e.message, true); });
    });
  }

  // ---------------------------------------------------------------- статистика каналов

  var csData = [];
  var csHours = 24;

  function fmtMs(seconds) {
    if (seconds == null) return '—';
    var ms = Math.round(seconds * 1000);
    return ms < 1000 ? ms + ' мс' : (seconds.toFixed(2) + ' с');
  }

  function fmtAgo(ts) {
    if (!ts) return '—';
    var diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60) return 'только что';
    if (diff < 3600) return Math.floor(diff / 60) + ' мин назад';
    if (diff < 86400) return Math.floor(diff / 3600) + ' ч назад';
    return Math.floor(diff / 86400) + ' дн назад';
  }

  /* Мини-график канала: столбик делится на проблемы (красное) и
     решения (зелёное). Сразу видно соотношение, а не только объём. */
  function csSparkline(hourly, problems, resolved) {
    var data = hourly || [];
    if (!data.length) return '';

    var prob = problems || [];
    var res = resolved || [];
    var height = 22;

    var totals = data.map(function (v, i) {
      return (prob[i] || 0) + (res[i] || 0);
    });
    var max = Math.max.apply(null, totals.concat([1]));

    var colorProblem = cssVar('--err', '#c62828');
    var colorResolved = cssVar('--ok', '#2e7d32');

    var bars = data.map(function (v, i) {
      var p = prob[i] || 0;
      var r = res[i] || 0;
      var sum = p + r;

      if (!sum) {
        return '<i class="cs-seg zero" style="height:2px"></i>';
      }

      var total_h = Math.max(3, Math.round((sum / max) * height));
      // Делим высоту пропорционально: проблемы снизу, решения сверху
      var hp = sum ? Math.round((p / sum) * total_h) : 0;
      var hr = total_h - hp;

      var tip = 'проблем: ' + p + ', решено: ' + r;
      var segs = '';
      if (hp > 0) {
        segs += '<i class="cs-seg" style="height:' + hp + 'px;background:' +
          colorProblem + '"></i>';
      }
      if (hr > 0) {
        segs += '<i class="cs-seg" style="height:' + hr + 'px;background:' +
          colorResolved + '"></i>';
      }
      return '<span class="cs-seg-stack" style="height:' + total_h + 'px" title="' +
        escapeHtml(tip) + '">' + segs + '</span>';
    }).join('');

    var totalProblem = prob.reduce(function (a, b) { return a + (b || 0); }, 0);
    var totalResolved = res.reduce(function (a, b) { return a + (b || 0); }, 0);

    // Подпись-итог: перекос видно без наведения
    var summary = '';
    if (totalProblem || totalResolved) {
      summary = '<span class="cs-spark-sum">' +
        '<b style="color:' + colorProblem + '">' + totalProblem + '</b>/' +
        '<b style="color:' + colorResolved + '">' + totalResolved + '</b>' +
        '</span>';
    }

    return '<div class="cs-spark-row">' +
      '<div class="cs-spark">' + bars + '</div>' + summary + '</div>';
  }

  function csRateCell(rate) {
    if (rate == null) return '<span class="dim">—</span>';
    var cls = rate >= 99 ? '' : (rate >= 90 ? ' warn' : ' err');
    return '<div class="cs-rate">' +
      '<span class="cs-rate-track"><span class="cs-rate-fill' + cls +
        '" style="width:' + Math.max(2, rate) + '%"></span></span>' +
      '<span class="cs-rate-text">' + rate.toFixed(1) + '%</span>' +
      '</div>';
  }

  function csStatusBadges(statuses) {
    var list = statuses || [];
    if (!list.length) return '<span class="dim">—</span>';
    return '<div class="cs-badges">' + list.slice(0, 4).map(function (s) {
      var cls = s.name === 'PROBLEM' || s.name === 'FIRING' ? ' problem'
              : (s.name === 'RESOLVED' || s.name === 'OK' ? ' resolved' : '');
      return '<span class="cs-badge' + cls + '">' + escapeHtml(s.name) +
             ' ' + s.count + '</span>';
    }).join('') + '</div>';
  }

  function renderChannelStats() {
    var query = (($('cs-search') || {}).value || '').trim().toLowerCase();
    var sortBy = (($('cs-sort') || {}).value) || 'total';

    var items = csData.slice();
    if (query) {
      items = items.filter(function (c) {
        return c.name.toLowerCase().indexOf(query) >= 0;
      });
    }

    var sorters = {
      total: function (a, b) { return b.total - a.total; },
      name: function (a, b) { return a.name.localeCompare(b.name); },
      failed: function (a, b) { return b.failed - a.failed; },
      latency: function (a, b) { return (b.avg_latency || 0) - (a.avg_latency || 0); },
      last: function (a, b) { return (b.last_at || 0) - (a.last_at || 0); }
    };
    items.sort(sorters[sortBy] || sorters.total);

    var count = $('cs-count');
    if (count) count.textContent = items.length;
    var filtered = $('cs-filtered');
    if (filtered) filtered.textContent = query ? 'найдено: ' + items.length : '';

    var body = $('cs-rows');
    if (!body) return;

    body.innerHTML = items.length ? items.map(function (c) {
      return '<tr>' +
        '<td><div class="cs-name">' + escapeHtml(c.name) + '</div>' +
          csSparkline(c.hourly, c.hourly_problem, c.hourly_resolved) + '</td>' +
        '<td class="cs-num">' + c.sent + '</td>' +
        '<td class="cs-num' + (c.failed ? ' err' : '') + '">' + (c.failed || '—') + '</td>' +
        '<td>' + csRateCell(c.success_rate) + '</td>' +
        '<td class="cs-num fs-12">' + fmtMs(c.avg_latency) +
          (c.max_latency ? '<div class="dim fs-11">макс ' + fmtMs(c.max_latency) + '</div>' : '') +
        '</td>' +
        '<td>' + csStatusBadges(c.statuses) + '</td>' +
        '<td class="dim fs-12">' + fmtAgo(c.last_at) + '</td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="7"><div class="empty-cell">' +
        (query ? 'ничего не найдено' : 'данных пока нет — уведомления ещё не приходили') +
        '</div></td></tr>';
  }

  function renderCsTotals(totals) {
    var box = $('cs-totals');
    if (!box || !totals) return;
    var cells = [
      { value: totals.channels || 0, label: 'каналов' },
      { value: totals.sent || 0, label: 'отправлено' },
      { value: totals.failed || 0, label: 'отказов', cls: totals.failed ? 'err' : '' },
      { value: totals.success_rate == null ? '—' : totals.success_rate.toFixed(1) + '%',
        label: 'успешность', cls: 'ok' },
      { value: fmtMs(totals.avg_latency), label: 'ср. задержка' }
    ];
    box.innerHTML = cells.map(function (c) {
      return '<div class="cs-total">' +
        '<div class="cs-total-value ' + (c.cls || '') + '">' + c.value + '</div>' +
        '<div class="cs-total-label">' + c.label + '</div></div>';
    }).join('');
  }

  function loadChannelStats() {
    return api('/api/metrics?kind=channel-report&hours=' + csHours).then(function (data) {
      csData = data.channels || [];
      renderCsTotals(data.totals || {});
      renderChannelStats();
    }).catch(function (e) {
      var body = $('cs-rows');
      if (body) body.innerHTML = '<tr><td colspan="7"><div class="empty-cell">' +
        escapeHtml(e.message) + '</div></td></tr>';
    });
  }

  // ---------------------------------------------------------------- временная шкала

  var TL_COLORS = ['#4c8dff', '#2fb37a', '#e8a33d', '#d9534f', '#8e6cd4',
                   '#17a2b8', '#c2410c', '#65a30d', '#db2777', '#0891b2',
                   '#7c3aed', '#059669', '#d97706', '#dc2626', '#2563eb'];
  var tlPoints = [];
  var tlBucket = 'auto';
  var tlBucketMinutes = 5;
  var tlColors = {};
  var tlColorSeq = 0;
  var tlTip = null;

  function tlColor(name) {
    if (!tlColors[name]) {
      tlColors[name] = TL_COLORS[tlColorSeq % TL_COLORS.length];
      tlColorSeq++;
    }
    return tlColors[name];
  }

  /* Рисует точки на шкале времени: размер зависит от числа сообщений. */
  function drawTimeline(canvas, points, opts) {
    if (!canvas) return;
    var o = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(320, rect.width || canvas.clientWidth || 600);
    var h = o.height || 200;

    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.height = h + 'px';

    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var colorText = cssVar('--text-dim', '#8a96a3');
    var colorGrid = cssVar('--border-light', '#dde3ea');

    if (!points.length) {
      ctx.fillStyle = colorText;
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(o.emptyText || 'За период событий не было', w / 2, h / 2);
      return;
    }

    var padL = 26, padR = 12, padT = 16, padB = 30;
    var plotW = w - padL - padR;
    var plotH = h - padT - padB;

    var t0 = points[0].ts;
    var t1 = points[points.length - 1].ts;
    var span = (t1 - t0) || 1;
    var maxTotal = Math.max.apply(null, points.map(function (p) { return p.total; }));

    function xOf(ts) { return padL + ((ts - t0) / span) * plotW; }
    // Точки держим у нижней части, чтобы подсказки не уходили за край
    function yOf(point, index) {
      var ratio = maxTotal ? point.total / maxTotal : 0;
      var spread = (index % 3) / 3;
      return padT + plotH * (1 - ratio * 0.72 - spread * 0.22);
    }
    function radiusOf(point) {
      if (!maxTotal) return 4;
      var r = 4 + Math.sqrt(point.total / maxTotal) * 13;
      return Math.min(17, r);
    }

    // Горизонтальная сетка с подписями количества: без неё непонятен масштаб
    ctx.strokeStyle = colorGrid;
    ctx.lineWidth = 1;
    ctx.font = '10px sans-serif';
    ctx.fillStyle = colorText;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    var gridSteps = 4;
    for (var gs = 0; gs <= gridSteps; gs++) {
      var level = (maxTotal * gs) / gridSteps;
      var gy = padT + plotH - (level / (maxTotal || 1)) * plotH;
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(w - padR, gy);
      ctx.stroke();
      if (level > 0) {
        ctx.fillText(String(Math.round(level)), padL - 2, gy);
      }
    }

    // Вертикальная сетка по времени — тоже помогает читать график
    var vTicks = Math.min(8, points.length);
    ctx.strokeStyle = hexToRgba(colorGrid, 0.7);
    for (var vi = 0; vi < vTicks; vi++) {
      var vIdx = Math.round((points.length - 1) * (vi / Math.max(1, vTicks - 1)));
      var vx = xOf(points[vIdx].ts);
      ctx.beginPath();
      ctx.moveTo(vx, padT);
      ctx.lineTo(vx, padT + plotH);
      ctx.stroke();
    }

    // Ось времени
    ctx.strokeStyle = colorGrid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, padT + plotH);
    ctx.lineTo(w - padR, padT + plotH);
    ctx.stroke();

    ctx.fillStyle = colorText;
    ctx.font = '10px sans-serif';
    ctx.textBaseline = 'top';

    var ticks = Math.min(7, points.length);
    for (var i = 0; i < ticks; i++) {
      var idx = Math.round((points.length - 1) * (i / Math.max(1, ticks - 1)));
      var pt = points[idx];
      var px = xOf(pt.ts);
      ctx.textAlign = i === 0 ? 'left' : (i === ticks - 1 ? 'right' : 'center');
      ctx.fillText(pt.time, px, padT + plotH + 8);
    }

    // Цвета статусов: проблема — красная, решение — зелёное
    var colorProblem = cssVar('--err', '#c62828');
    var colorResolved = cssVar('--ok', '#2e7d32');

    // Точки
    points.forEach(function (point, index) {
      var x = xOf(point.ts);
      var y = yOf(point, index);
      var r = radiusOf(point);

      var problems = point.problems || 0;
      var resolved = point.resolved || 0;

      // Если в интервале только решения — точка зелёная,
      // только проблемы — красная, смешанные — красная с зелёной серединой.
      var hasProblem = problems > 0;
      var hasResolved = resolved > 0;
      var mainColor = hasProblem
        ? colorProblem
        : (hasResolved ? colorResolved : cssVar('--aq-primary', '#1f4e8c'));

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = hexToRgba(mainColor, 0.3);
      ctx.fill();

      // Смешанный интервал: правая половина — решения, левая — проблемы
      if (hasProblem && hasResolved) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, Math.max(2.5, r * 0.5), 0, Math.PI * 2);
        ctx.clip();
        ctx.fillStyle = colorProblem;
        ctx.fillRect(x - r, y - r, r, r * 2);
        ctx.fillStyle = colorResolved;
        ctx.fillRect(x, y - r, r, r * 2);
        ctx.restore();
      } else {
        ctx.beginPath();
        ctx.arc(x, y, Math.max(2.5, r * 0.45), 0, Math.PI * 2);
        ctx.fillStyle = mainColor;
        ctx.fill();
      }

      if (point.failed) {
        ctx.beginPath();
        ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
        ctx.strokeStyle = cssVar('--warn', '#b26a00');
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      point._x = x;
      point._y = y;
      point._r = r;
    });

    tlPoints = points;
  }

  function tlTipHtml(point) {
    // Точное время интервала: от начала до конца шага
    var stepMin = point.bucket_minutes || tlBucketMinutes || 5;
    var startLabel = point.label;
    var endDate = new Date(point.ts * 1000 + stepMin * 60000);
    var pad2 = function (v) { return String(v).padStart(2, '0'); };
    var endLabel = pad2(endDate.getDate()) + '.' + pad2(endDate.getMonth() + 1) +
      ' ' + pad2(endDate.getHours()) + ':' + pad2(endDate.getMinutes());

    var html = '<div class="tl-tip-head">' +
      '<strong>' + escapeHtml(startLabel) + ' – ' + escapeHtml(endLabel.split(' ')[1]) +
      '</strong>' +
      (point.weekday ? ' · ' + escapeHtml(point.weekday) : '') +
      (point.approximate ? ' <span style="opacity:.6">(примерно)</span>' : '') +
      '<br>интервал ' + stepMin + ' мин, всего <strong>' + point.total + '</strong>' +
      '</div>';

    // Проблемы и решения отдельными строками
    var problems = point.problems || 0;
    var resolved = point.resolved || 0;
    if (problems || resolved) {
      html += '<div class="tl-tip-row">' +
        '<i class="tl-tip-dot" style="background:' +
          cssVar('--err', '#c62828') + '"></i>' +
        '<span class="tl-tip-name">проблем</span>' +
        '<span class="tl-tip-count">' + problems + '</span></div>';
      html += '<div class="tl-tip-row">' +
        '<i class="tl-tip-dot" style="background:' +
          cssVar('--ok', '#2e7d32') + '"></i>' +
        '<span class="tl-tip-name">решено</span>' +
        '<span class="tl-tip-count">' + resolved + '</span></div>';
    }

    // Каналы: если есть разбивка по статусам — показываем «3 / 1»
    var byChannel = point.by_channel || {};
    html += '<div class="tl-tip-list" style="margin-top:6px;">' +
      point.channels.slice(0, 8).map(function (item) {
        var detail = byChannel[item.name] || {};
        var extra = '';
        if (detail.problem != null || detail.resolved != null) {
          var p = detail.problem || 0;
          var r2 = detail.resolved || 0;
          if (p && r2) extra = ' (' + p + ' / ' + r2 + ')';
        }
        return '<div class="tl-tip-row">' +
          '<i class="tl-tip-dot" style="background:' + tlColor(item.name) + '"></i>' +
          '<span class="tl-tip-name">' + escapeHtml(item.name) + '</span>' +
          '<span class="tl-tip-count">' + item.count + escapeHtml(extra) + '</span>' +
          '</div>';
      }).join('') + '</div>';

    var sev = Object.keys(point.severities || {});
    if (sev.length) {
      html += '<div class="tl-tip-head" style="border:0;padding:6px 0 0;margin:6px 0 0;' +
              'border-top:1px solid var(--border-light);">' +
              escapeHtml(sev.join(', ')) + '</div>';
    }
    return html;
  }

  function tlShowTip(event) {
    if (!tlPoints.length) return;
    var canvas = $('chart-timeline');
    if (!canvas) return;

    var rect = canvas.getBoundingClientRect();
    var mx = event.clientX - rect.left;
    var my = event.clientY - rect.top;

    var best = null;
    var bestDist = Infinity;
    tlPoints.forEach(function (point) {
      if (point._x == null) return;
      var dx = mx - point._x;
      var dy = my - point._y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < Math.max(18, point._r + 6) && dist < bestDist) {
        bestDist = dist;
        best = point;
      }
    });

    if (!best) { tlHideTip(); return; }

    if (!tlTip) {
      tlTip = document.createElement('div');
      tlTip.className = 'tl-tip';
      document.body.appendChild(tlTip);
    }
    tlTip.innerHTML = tlTipHtml(best);
    tlTip.style.display = 'block';

    var tw = tlTip.offsetWidth, th = tlTip.offsetHeight;
    var left = Math.max(8, Math.min(event.clientX - tw / 2, window.innerWidth - tw - 8));
    var topPos = rect.top + best._y - th - 12;
    if (topPos < 8) topPos = rect.top + best._y + best._r + 12;
    tlTip.style.left = left + 'px';
    tlTip.style.top = topPos + 'px';

    canvas.style.cursor = 'pointer';
  }

  function tlHideTip() {
    if (tlTip) tlTip.style.display = 'none';
    var canvas = $('chart-timeline');
    if (canvas) canvas.style.cursor = 'default';
  }

  function renderTimelineLegend(points) {
    var box = $('tl-legend');
    if (!box) return;
    var totals = {};
    points.forEach(function (point) {
      point.channels.forEach(function (item) {
        totals[item.name] = (totals[item.name] || 0) + item.count;
      });
    });
    var ordered = Object.keys(totals).sort(function (a, b) {
      return totals[b] - totals[a];
    }).slice(0, 10);

    if (!ordered.length) { box.innerHTML = ''; return; }

    // Сначала пояснение цветов статусов — главное на графике
    var statusLegend =
      '<span class="tl-item"><i class="tl-dot" style="background:' +
        cssVar('--err', '#c62828') + '"></i>проблема</span>' +
      '<span class="tl-item"><i class="tl-dot" style="background:' +
        cssVar('--ok', '#2e7d32') + '"></i>решено</span>' +
      '<span class="tl-item" style="opacity:.7;">размер точки — число сообщений</span>';

    box.innerHTML = statusLegend +
      '<span class="tl-item" style="opacity:.4;margin:0 2px;">|</span>' +
      ordered.map(function (name) {
        return '<span class="tl-item">' +
          '<i class="tl-dot" style="background:' + tlColor(name) +
            ';width:7px;height:7px;"></i>' +
          escapeHtml(name) + ' <span style="opacity:.65">' + totals[name] + '</span>' +
          '</span>';
      }).join('');
  }

  function loadTimeline() {
    var hours = csHours || 24;
    var bucket = tlBucket || 'auto';
    return api('/api/metrics?kind=timeline&hours=' + hours + '&bucket=' + bucket)
      .then(function (data) {
      var points = data.points || [];
      if ($('tl-status')) {
        if (points.length) {
          var step = data.bucket_minutes;
          var label = step >= 60
            ? (step / 60) + ' ч'
            : step + ' мин';
          $('tl-status').textContent = points.length + ' точек, шаг ' + label;
        } else {
          $('tl-status').textContent = 'нет событий';
        }
      }
      tlBucketMinutes = data.bucket_minutes || 5;
      drawTimeline($('chart-timeline'), points, {
        height: 210,
        bucketMinutes: tlBucketMinutes
      });
      renderTimelineLegend(points);
    }).catch(function () { /* не критично */ });
  }

  /* Графики на странице статистики: те же данные, отдельные элементы. */
  function loadStatsCharts() {
    var hours = csHours || 24;
    return api('/api/metrics?kind=history&hours=' + hours).then(function (data) {
      var points = data.points || [];

      var status = $('cs-charts-status');
      if (status) status.textContent = 'за ' + (data.hours || hours) + ' ч';

      // По каналам — во всю ширину: при 30 каналах нужно место
      var channels = data.channels || [];
      var total = channels.reduce(function (sum, c) { return sum + c.count; }, 0);
      if ($('cv-total')) $('cv-total').textContent = total;
      drawBars($('chart-channels'), channels, {
        color: cssVar('--aq-primary', '#1f4e8c'),
        height: 210,
        limit: 30,
        barWidth: 32,
        emptyText: 'За период ничего не отправлялось'
      });

      var sentTotal = points.reduce(function (s, p) { return s + (p.sent || 0); }, 0);
      var failedTotal = points.reduce(function (s, p) { return s + (p.failed || 0); }, 0);
      if ($('cv-sent-2')) {
        $('cv-sent-2').textContent = sentTotal + (failedTotal ? ' / ' + failedTotal : '');
      }
      drawLine($('chart-sent-2'), points, {
        field: 'sent', color: cssVar('--aq-primary', '#1f4e8c')
      });

      var latencies = points.filter(function (p) { return p.latency != null; });
      var avg = latencies.length
        ? latencies.reduce(function (s, p) { return s + p.latency; }, 0) / latencies.length
        : null;
      if ($('cv-latency-2')) {
        $('cv-latency-2').textContent = avg == null
          ? '\u2014' : Math.round(avg * 1000) + ' \u043c\u0441';
      }
      drawLine($('chart-latency-2'), points, {
        field: 'latency',
        color: cssVar('--warn', '#b26a00'),
        formatY: function (v) { return Math.round(v * 1000) + '\u043c\u0441'; },
        emptyText: 'Нет замеров'
      });

      renderSeverityBars(data.severities || [], 'severity-bars', 'cv-severity');
      renderStatusBars(data.statuses || [], 'status-bars-2', 'cv-statuses-2');
    }).catch(function () { /* графики не критичны */ });
  }

  function initChannelStatsHandlers() {
    on('tl-bucket', 'change', function () {
      tlBucket = $('tl-bucket').value || 'auto';
      loadTimeline();
    });

    var tlCanvas = $('chart-timeline');
    if (tlCanvas) {
      tlCanvas.addEventListener('mousemove', tlShowTip);
      tlCanvas.addEventListener('mouseleave', tlHideTip);
      window.addEventListener('scroll', tlHideTip, true);
    }

    on('cs-hours', 'change', function () {
      csHours = Number($('cs-hours').value) || 24;
      loadChannelStats();
      loadStatsCharts();
      loadTimeline();
    });
    on('cs-refresh', 'click', function () {
      Promise.all([loadChannelStats(), loadStatsCharts(), loadTimeline()])
        .then(function () { toast('Статистика обновлена'); });
    });
    on('cs-search', 'input', renderChannelStats);
    on('cs-sort', 'change', renderChannelStats);
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

  var INCIDENT_MODE_HINTS = {
    notify: 'Сообщение о проблеме остаётся в чате. При решении бот только отмечает инцидент в истории.',
    delete: 'При решении сообщение о проблеме удаляется из чата. Новое сообщение не отправляется.',
    resolve: 'При решении в чат приходит сообщение «✅ Восстановлено». Прежнее сообщение остаётся.',
    both: 'При решении сообщение о проблеме удаляется И приходит сообщение «✅ Восстановлено».'
  };

  function updateIncidentModeHint() {
    var select = $('set-incident-mode');
    var hint = $('set-mode-hint');
    if (!select || !hint) return;
    hint.textContent = INCIDENT_MODE_HINTS[select.value] || '';

    // Режимы с удалением включают удаление автоматически — показываем это
    var del = $('set-delete');
    if (del && (select.value === 'delete' || select.value === 'both')) {
      del.value = 'true';
    }
  }

  function initSettingsHandlers() {
    on('set-incident-mode', 'change', updateIncidentModeHint);

    on('set-save', 'click', function () {
      api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({
          incident_mode: ($('set-incident-mode') || {}).value || 'notify',
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

  // ---------------------------------------------------------------- чат по умолчанию

  var dcState = { chatId: null, title: null };

  function dcShowForm(show) {
    var form = $('dc-form');
    var view = $('dc-view');
    var btn = $('dc-edit');
    if (form) form.classList.toggle('hidden', !show);
    if (view) view.classList.toggle('hidden', show);
    if (btn) btn.classList.toggle('hidden', show);
    if (show) {
      var input = $('dc-chat-id');
      if (input) {
        input.value = dcState.chatId || '';
        input.focus();
      }
      var title = $('dc-chat-title');
      if (title) title.value = dcState.title || '';
    }
  }

  function dcHint(text) {
    var hint = $('dc-hint');
    if (!hint) return;
    hint.textContent = text || '';
    hint.classList.toggle('hidden', !text);
  }

  function loadDefaultChat() {
    return api('/api/default-chat').then(function (data) {
      dcState.chatId = data.chat_id;
      dcState.options = data.options || [];

      var def = $('default-chat');
      if (def) def.textContent = data.chat_id || 'не задан';

      var usage = $('dc-usage');
      if (usage) {
        usage.textContent = data.channels_using
          ? '(' + data.channels_using + ' канал(ов) ведут сюда)'
          : '';
      }

      // Заполняем список чатов, которые уже используются каналами
      var select = $('dc-select');
      if (select) {
        var current = data.chat_id;
        var html = '<option value="">— выберите канал —</option>';
        dcState.options.forEach(function (opt) {
          var label = opt.channels.length
            ? opt.channels.join(', ')
            : (opt.chat_title || 'вне каналов');
          var title = opt.chat_title ? ' \u2014 ' + opt.chat_title : '';
          var mark = opt.chat_id === current ? ' \u2713' : '';
          html += '<option value="' + escapeHtml(opt.chat_id) + '">' +
            escapeHtml(label) + escapeHtml(title) + escapeHtml(mark) +
            '</option>';
        });
        select.innerHTML = html;
        if (current) select.value = current;
      }
    }).catch(function () { /* не критично */ });
  }

  function dcSave(chatId, title) {
    return api('/api/default-chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, chat_title: title || '' })
    }).then(function (data) {
      dcState.chatId = data.chat_id;
      var def = $('default-chat');
      if (def) def.textContent = data.chat_id || 'не задан';
      dcShowForm(false);
      dcHint(chatId ? '' : 'Чат по умолчанию очищен: уведомления без канала будут отклоняться.');
      toast(chatId ? 'Чат по умолчанию сохранён' : 'Чат по умолчанию очищен');
      loadDefaultChat();
    }).catch(function (e) { toast(e.message, true); });
  }

  function initDefaultChatHandlers() {
    on('dc-edit', 'click', function () { dcShowForm(true); });

    on('dc-apply', 'click', function () {
      var select = $('dc-select');
      var value = select ? select.value : '';
      if (!value) {
        dcHint('Сначала выберите канал в списке');
        return;
      }
      var opt = (dcState.options || []).filter(function (o) {
        return o.chat_id === value;
      })[0] || {};
      dcHint('');
      dcSave(value, opt.chat_title || '');
    });

    on('dc-save-manual', 'click', function () {
      var chatId = (($('dc-chat-id') || {}).value || '').trim();
      var title = (($('dc-chat-title') || {}).value || '').trim();
      if (!chatId) {
        dcHint('Введите chat_id');
        return;
      }
      dcHint('');
      dcSave(chatId, title);
    });
    on('dc-cancel', 'click', function () { dcShowForm(false); dcHint(''); });

    on('dc-clear', 'click', function () {
      if (!confirm('Очистить чат по умолчанию?\n\n' +
                   'Уведомления без указания канала перестанут доставляться.')) {
        return;
      }
      dcSave('', '');
    });

    loadDefaultChat();
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
    if (page === 'channel-stats') return { channelStats: true };
    if (page === 'backups') return { backups: true };
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
      if (tasks.channels) {
        initDefaultChatHandlers();
      }
      if (tasks.backups) {
        initBackupHandlers();
        loadBackups();
      }
      if (tasks.channelStats) {
        initChannelStatsHandlers();
        loadChannelStats();
        loadStatsCharts();
        loadTimeline();
        setInterval(function () {
          loadChannelStats();
          loadStatsCharts();
          loadTimeline();
        }, 60000);
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