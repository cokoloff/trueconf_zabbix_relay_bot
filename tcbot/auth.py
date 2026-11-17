# -*- coding: utf-8 -*-
"""
Слой авторизации админ-панели.

Способы входа (WEBUI_AUTH):
    keycloak — только Keycloak (SSO)
    local    — только local-admin (логин/пароль в самом боте)
    both     — оба способа: на странице входа есть кнопка SSO и форма локального входа
    token    — статический токен X-WebUI-Token (для скриптов и проверок)
    none     — без авторизации (только закрытый контур)

Роли:
    admin  — полный доступ, включая изменения
    viewer — только просмотр (GET/HEAD/OPTIONS)

Резервный вход: если Keycloak недоступен, local-admin продолжает работать —
именно поэтому режим both рекомендуется по умолчанию.
"""

from __future__ import annotations

import logging
import secrets
from typing import Optional
from urllib.parse import quote

from aiohttp import web

from .localadmin import LocalAdminStore
from .sso import KeycloakSSO, SSOUser

logger = logging.getLogger("bot")

STATE_COOKIE = "tcbot_oidc_state"
SESSION_COOKIE = "tcbot_session"
CSRF_FIELD = "_csrf"

# Маршруты, доступные без авторизации
PUBLIC_PATHS = {
    "/health",
    "/live",
    "/ready",
    "/favicon.ico",
    "/login",
    "/auth/login",
    "/auth/local",
    "/auth/callback",
}

# Префиксы, доступные без авторизации (статика нужна на странице входа)
PUBLIC_PREFIXES = ("/static/",)

# Вебхуки авторизуются отдельно (сеть/токен), SSO к ним не применяется
WEBHOOK_PATHS = {"/webhook", "/zabbix-webhook", "/api/webhook"}

READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}

LOGIN_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход — TrueConf Zabbix Relay Bot</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/style.css">
<script>
(function () {{
  /* Светлая тема по умолчанию; тёмная — только если выбрана вручную. */
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
      <img class="brand-logo" src="/static/logo.svg" alt="Логотип" onerror="this.style.display='none';">
    </span>
    <div>
      <div class="brand-title">TrueConf Zabbix Relay Bot</div>
      <div class="brand-sub">Relay уведомлений Zabbix в чаты TrueConf</div>
    </div>
  </a>
  <div class="user">
    <button type="button" class="ua-theme-btn" id="theme-toggle" title="Переключить тему">
      <span class="ua-theme-icon">🌙</span>
    </button>
  </div>
</header>

<div class="login-wrap">
  <div class="card login-card">
    <h2>Вход в панель</h2>

    {error}

    {sso_button}

    <form class="login-form" method="post" action="/auth/local">
      <input type="hidden" name="next" value="{next_url}">
      <div class="row">
        <span class="label">Логин</span>
        <input type="text" name="username" autocomplete="username"
               value="{username}" placeholder="local-admin" required autofocus>
      </div>
      <div class="row">
        <span class="label">Пароль</span>
        <input type="password" name="password" autocomplete="current-password" required>
      </div>
      <div class="actions">
        <button type="submit">Войти</button>
      </div>
    </form>

    <p class="login-hint">{note}</p>
  </div>
</div>

<div class="copy-toast" id="toast"></div>
<script>
(function () {{
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  var icon = btn.querySelector('.ua-theme-icon');
  function label() {{
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (icon) icon.textContent = dark ? '☀' : '🌙';
    btn.title = dark ? 'Включить светлую тему' : 'Включить тёмную тему';
  }}
  label();
  btn.addEventListener('click', function () {{
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
    try {{ localStorage.setItem('tcbot-theme', dark ? 'light' : 'dark'); }} catch (e) {{}}
    label();
  }});
}})();
</script>
</body>
</html>
"""


class AuthManager:
    def __init__(
        self,
        *,
        mode: str = "token",
        sso: Optional[KeycloakSSO] = None,
        local: Optional[LocalAdminStore] = None,
        token: str = "",
        login_path: str = "/login",          # страница выбора способа входа
        sso_path: str = "/auth/login",       # старт OIDC-входа
        callback_path: str = "/auth/callback",
        local_path: str = "/auth/local",
        session_ttl_seconds: int = 8 * 3600,
        session_secret: str = "",
    ):
        self.mode = (mode or "token").lower()
        self.sso = sso
        self.local = local
        self.token = token
        self.login_path = login_path
        self.sso_path = sso_path
        self.callback_path = callback_path
        self.local_path = local_path
        self.session_ttl_seconds = session_ttl_seconds

        # Подписант cookie для режима без SSO (local/token)
        from .sso import SessionSigner

        self._local_signer = SessionSigner(
            session_secret or secrets.token_urlsafe(32),
            ttl=session_ttl_seconds,
            cookie_name=SESSION_COOKIE,
        )

        if self.mode in ("keycloak", "both") and self.sso is None:
            logger.error(f"❌ WEBUI_AUTH={self.mode}, но Keycloak не настроен — SSO недоступен")
            if self.mode == "both" and self.local is not None:
                self.mode = "local"
                logger.warning("⚠️ Панель переключена на вход через local-admin")
            elif self.mode == "keycloak":
                self.mode = "deny"

        if self.mode in ("local", "both") and self.local is None:
            logger.error(f"❌ WEBUI_AUTH={self.mode}, но local-admin не инициализирован")
            if self.mode == "both" and self.sso is not None:
                self.mode = "keycloak"
            elif self.mode == "local":
                self.mode = "deny"

        logger.info(f"🔐 Авторизация панели: {self.mode}")

    # ------------------------------ свойства ------------------------------ #

    @property
    def sso_enabled(self) -> bool:
        return self.sso is not None and self.mode in ("keycloak", "both")

    @property
    def local_enabled(self) -> bool:
        return self.local is not None and self.local.enabled and self.mode in ("local", "both")

    @property
    def cookie_secure(self) -> bool:
        return bool(self.sso and self.sso.cookie_secure)

    def _signer(self):
        """Подписант cookie: при наличии SSO используем его, иначе собственный."""
        return self.sso.signer if self.sso is not None else self._local_signer

    # --------------------------- вспомогательное --------------------------- #

    def session_from_request(self, request: web.Request) -> Optional[SSOUser]:
        signer = self._signer()
        if signer is None:
            return None
        raw = request.cookies.get(signer.cookie_name)
        if not raw:
            return None
        data = signer.loads(raw)
        if data is None:
            return None
        return SSOUser.from_session(data)

    def set_session_cookie(self, response: web.Response, user: SSOUser) -> None:
        signer = self._signer()
        if signer is None:
            return
        value = signer.dumps(user.to_session())
        response.set_cookie(
            signer.cookie_name,
            value,
            max_age=signer.ttl,
            httponly=True,
            samesite="Lax",
            secure=self.cookie_secure,
            path="/",
        )

    def clear_session_cookie(self, response: web.Response) -> None:
        signer = self._signer()
        if signer is None:
            return
        response.del_cookie(signer.cookie_name, path="/")

    # ----------------------------- проверка ----------------------------- #

    def authorize(self, request: web.Request) -> Optional[web.Response]:
        """None — доступ разрешён; иначе готовый ответ (401/403/redirect)."""
        path = request.path
        method = request.method.upper()

        if self.mode == "none":
            return None

        if path in PUBLIC_PATHS or path in WEBHOOK_PATHS:
            return None

        if path.startswith(PUBLIC_PREFIXES):
            return None

        if self.mode == "token":
            supplied = request.headers.get("X-WebUI-Token") or request.query.get("token")
            if not self.token or supplied == self.token:
                return None
            if path.startswith("/api/"):
                return web.json_response({"error": "unauthorized"}, status=401)
            return self._login_redirect(request)

        # token-заголовок работает как «сервисный» доступ в любом режиме
        if self.token:
            supplied = request.headers.get("X-WebUI-Token") or request.query.get("token")
            if supplied == self.token:
                request["user"] = SSOUser(
                    subject="service-token",
                    username="service-token",
                    name="Сервисный доступ",
                    roles=["admin"],
                    is_admin=True,
                    is_viewer=True,
                    via="token",
                )
                return None

        if self.mode == "deny":
            return web.json_response({"error": "unauthorized"}, status=401)

        user = self.session_from_request(request)
        if user is None:
            if path.startswith("/api/"):
                return web.json_response(
                    {"error": "unauthorized", "login": self._entry_path()}, status=401
                )
            return self._login_redirect(request)

        request["user"] = user

        if method not in READ_ONLY_METHODS and not user.is_admin:
            logger.warning(f"🚫 {user.display} пытался изменить {path} без прав администратора")
            return web.json_response(
                {"error": "forbidden", "detail": "требуются права администратора"}, status=403
            )

        if not (user.is_admin or user.is_viewer):
            return web.json_response(
                {"error": "forbidden", "detail": "нет роли для доступа к панели"}, status=403
            )
        return None

    def _entry_path(self) -> str:
        """Адрес, с которого начинается вход."""
        return self.login_path if self.local_enabled else self.sso_path

    def _login_redirect(self, request: web.Request) -> web.Response:
        """
        Куда отправить неавторизованный запрос.

        Если доступен только SSO — сразу на Keycloak (лишний клик не нужен).
        Если есть локальный вход — на страницу выбора способа входа.
        """
        target = request.path_qs or "/"
        destination = self.login_path if self.local_enabled else self.sso_path
        return web.HTTPFound(f"{destination}?next={quote(target, safe='')}")

    # ------------------------------ страница входа ------------------------------ #

    def login_page_html(self, *, error: str = "", username: str = "", next_url: str = "/") -> str:
        sso_button = ""
        if self.sso_enabled:
            sso_button = (
                f'<div class="actions" style="margin:0 0 4px;">'
                f'<a class="btn-link" href="{self.sso_path}?next={quote(next_url, safe="")}" '
                f'style="text-decoration:none; display:block; width:100%;">'
                f'<button type="button" class="secondary" style="width:100%;">'
                "Войти через Keycloak (SSO)</button></a></div>"
            )

        if self.sso_enabled and self.local_enabled:
            sso_button += '<div class="login-divider"><span>или</span></div>'
            note = (
                "SSO — обычный вход для сотрудников. Локальный администратор нужен, "
                "если Keycloak недоступен."
            )
        elif self.local_enabled:
            sso_button = ""
            note = "Вход по локальной учётной записи администратора бота."
        else:
            note = "SSO временно недоступен."

        html = LOGIN_PAGE_TEMPLATE.format(
            error=f'<div class="flash error">{error}</div>' if error else "",
            sso_button=sso_button,
            username=username,
            note=note,
            next_url=next_url,
        )
        if not self.local_enabled:
            html = html.replace('<form class="login-form"', '<form class="login-form hidden"')
        return html

    async def handle_login_page(self, request: web.Request) -> web.Response:
        """GET /login — страница выбора способа входа."""
        next_url = request.query.get("next", "/")
        if not next_url.startswith("/"):
            next_url = "/"
        return web.Response(
            text=self.login_page_html(next_url=next_url),
            content_type="text/html",
            charset="utf-8",
        )

    # ------------------------------ SSO ------------------------------ #

    async def handle_login(self, request: web.Request) -> web.Response:
        """GET /auth/login — старт OIDC-входа."""
        if not self.sso_enabled:
            # SSO выключен или не настроен — уводим на страницу выбора способа входа
            return self.handle_login_page(request)

        next_url = request.query.get("next", "/")
        if not next_url.startswith("/"):
            next_url = "/"
        redirect_uri = self.sso.redirect_uri or str(request.url.with_path(self.callback_path).with_query({}))

        try:
            url, state_data = await self.sso.build_login_url(redirect_uri, next_url)
        except Exception as exc:
            logger.error(f"❌ Не удалось начать вход через SSO: {exc}")
            return web.Response(
                text=(
                    "Keycloak недоступен. Если у вас есть локальная учётная запись — "
                    f'войдите через <a href="{self.local_path}">/auth/local</a>.'
                ),
                content_type="text/html",
                status=502,
            )

        response = web.HTTPFound(url)
        response.set_cookie(
            STATE_COOKIE,
            self.sso.signer.dumps(state_data),
            max_age=600,
            httponly=True,
            samesite="Lax",
            secure=self.cookie_secure,
            path="/",
        )
        return response

    async def handle_callback(self, request: web.Request) -> web.Response:
        """GET /auth/callback — обмен кода на токены."""
        if self.sso is None:
            return web.Response(text="SSO не настроен", status=503)

        error = request.query.get("error")
        if error:
            description = request.query.get("error_description", "")
            logger.warning(f"⚠️ Keycloak вернул ошибку: {error} {description}")
            return web.Response(text=f"Ошибка входа: {error} {description}", status=401)

        code = request.query.get("code")
        state = request.query.get("state")
        if not code or not state:
            return web.Response(text="Некорректный ответ Keycloak (нет code/state)", status=400)

        raw_state = request.cookies.get(STATE_COOKIE)
        state_data = self.sso.signer.loads(raw_state) if raw_state else None
        if not state_data or state_data.get("state") != state:
            logger.warning("⚠️ state не совпал — возможна CSRF-попытка")
            return web.Response(text="Состояние входа истекло, повторите вход", status=400)

        try:
            user = await self.sso.authenticate(code, state_data)
        except Exception as exc:
            logger.error(f"❌ Ошибка проверки токенов Keycloak: {exc}")
            return web.Response(text=f"Не удалось завершить вход: {exc}", status=401)

        if not (user.is_admin or user.is_viewer):
            required_roles = sorted(
                (getattr(self.sso, "admin_roles", set()) or set())
                | (getattr(self.sso, "viewer_roles", set()) or set())
            )
            logger.warning(
                f"🚫 Отказано в доступе: {user.display} ({user.roles or 'без ролей'}) — "
                f"нет ни одной из ролей {required_roles}"
            )
            required = ", ".join(required_roles) or "—"
            hints = (
                "<li>пользователю назначены роли/группы в Keycloak "
                f"(<code>{required}</code>)</li>"
                "<li>в клиенте включены client scopes <code>roles</code> и "
                "<code>groups</code></li>"
                "<li>в <code>.env</code> задано "
                "<code>SSO_SCOPE=openid profile email roles groups</code></li>"
            )
            return web.Response(
                text=(
                    "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
                    "<title>Доступ запрещён</title><style>body{font:14px/1.6 "
                    "-apple-system,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:60px auto;"
                    "padding:0 20px;color:#e6edf5;background:#0f1419}"
                    "code{background:#1e2632;padding:1px 6px;border-radius:4px}"
                    "h1{font-size:18px;color:#f85149}li{margin:6px 0}</style></head><body>"
                    "<h1>Доступ запрещён</h1>"
                    "<p>Учётная запись прошла проверку в Keycloak, но не имеет роли для входа "
                    "в панель.</p>"
                    f"<p><b>Пользователь:</b> {user.display}<br>"
                    f"<b>Логин:</b> <code>{user.username or '—'}</code><br>"
                    f"<b>Роли:</b> {', '.join(user.roles) or '—'}</p>"
                    f"<p>Требуется одна из ролей: <code>{required}</code></p>"
                    f"<p>Проверьте:</p><ul>{hints}</ul>"
                    "<p>Если Keycloak недоступен или роли не настроены, используйте "
                    f"<a href='{self.local_path}' style='color:#388bfd'>локальный вход</a>.</p>"
                    "</body></html>"
                ),
                content_type="text/html",
                status=403,
            )

        logger.info(
            f"✅ Вход в панель: {user.display} "
            f"({'администратор' if user.is_admin else 'просмотр'}), роли={user.roles}"
        )

        next_url = state_data.get("next") or "/"
        if not next_url.startswith("/"):
            next_url = "/"

        response = web.HTTPFound(next_url)
        self.set_session_cookie(response, user)
        response.del_cookie(STATE_COOKIE, path="/")
        return response

    # --------------------------- local-admin --------------------------- #

    async def handle_local_login(self, request: web.Request) -> web.Response:
        """POST /auth/local — вход по логину/паролю local-admin."""
        if self.local is None or not self.local.enabled:
            return web.Response(text="Локальный вход отключён", status=403)

        form = await request.post()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        next_url = str(form.get("next", "/"))
        if not next_url.startswith("/"):
            next_url = "/"

        ip = self._client_ip(request)
        ok, reason = self.local.authenticate(username, password, ip)

        if not ok:
            logger.warning(f"🚫 local-admin: отказ для '{username}' с {ip}: {reason}")
            return web.Response(
                text=self.login_page_html(error=reason, username=username, next_url=next_url),
                content_type="text/html",
                charset="utf-8",
                status=401,
            )

        user = SSOUser(
            subject=f"local:{username}",
            username=username,
            name=username,
            roles=["local-admin"],
            is_admin=True,
            is_viewer=True,
            via="local",
        )
        logger.info(f"✅ Вход в панель (local-admin): {username} с {ip}")

        response = web.HTTPFound(next_url)
        self.set_session_cookie(response, user)
        return response

    @staticmethod
    def _client_ip(request: web.Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        peer = request.transport.get_extra_info("peername") if request.transport else None
        return peer[0] if peer else "unknown"

    # ------------------------------ ВЫХОД ------------------------------ #

    async def handle_logout(self, request: web.Request) -> web.Response:
        """GET /auth/logout — выход и завершение сессии Keycloak (если была через SSO)."""
        user = self.session_from_request(request)
        if user is not None:
            logger.info(f"👋 Выход из панели: {user.display} ({user.via})")

        redirect_uri = str(request.url.with_path("/").with_query({}))
        target = redirect_uri

        # завершаем сессию Keycloak только если вход был через SSO
        if self.sso is not None and (user is None or user.via == "keycloak"):
            try:
                target = await self.sso.logout_url(redirect_uri)
            except Exception:
                target = redirect_uri

        response = web.HTTPFound(target)
        self.clear_session_cookie(response)
        return response

    def current_user(self, request: web.Request) -> Optional[SSOUser]:
        cached = request.get("user")
        if isinstance(cached, SSOUser):
            return cached
        return None
