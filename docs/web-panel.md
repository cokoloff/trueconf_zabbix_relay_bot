# Веб-панель и авторизация

## Содержание

- [Режимы входа](#режимы-входа)
- [SSO через Keycloak](#sso-через-keycloak)
- [Локальный администратор](#локальный-администратор)
- [Роли](#роли)
- [Разделы панели](#разделы-панели)
- [Эндпоинты](#эндпоинты)

## Режимы входа

Задаётся переменной `WEBUI_AUTH`:

| Режим | Что доступно |
|---|---|
| `both` | **рекомендуется**: SSO Keycloak + локальный администратор на одной странице входа |
| `keycloak` | только SSO |
| `local` | только локальный администратор |
| `token` | статический `X-WebUI-Token` (для скриптов и healthcheck) |
| `none` | без авторизации (только закрытый контур) |

Страница `/login` показывает кнопку SSO и форму локального входа. Если доступен
только один способ, лишний шаг не создаётся.

## SSO через Keycloak

Вход по OpenID Connect, поток **Authorization Code + PKCE (S256)**.

### Что создать в Keycloak

1. **Client** с именем `tcbot-admin`, тип **public** (Client authentication = Off),
   Standard flow включён, PKCE `S256`.
2. **Valid redirect URIs**: `https://<панель>/auth/callback`
   (плюс `http://localhost:8080/auth/callback` для отладки).
3. **Web origins**: адрес панели или `+`.
4. **Роли** в realm (или в клиенте): `tcbot-admin` — полный доступ,
   `tcbot-viewer` — только просмотр. Назначьте их группам или пользователям.

### Настройка бота

```
WEBUI_AUTH=both
WEBUI_PUBLIC_URL=https://tcbot.example.com
SSO_SERVER_URL=https://auth.example.com
SSO_REALM=your-realm
SSO_CLIENT_ID=tcbot-admin
SSO_ADMIN_ROLES=tcbot-admin
SSO_VIEWER_ROLES=tcbot-viewer
SSO_COOKIE_SECURE=true
SSO_SESSION_SECRET=<длинная случайная строка>
```

`SSO_SESSION_SECRET` лучше задать: без него секрет подписи cookie генерируется
при старте, и после каждого перезапуска нужно входить заново.

### Если пришло «у учётной записи нет роли»

Вход прошёл, но Keycloak не вернул ролей. Проверьте:

1. **Запрошены ли scope `roles` и `groups`?** Без них Keycloak не кладёт
   `realm_access` / `resource_access` в токен:
   ```
   SSO_SCOPE=openid profile email roles groups
   ```
2. **Назначена ли роль пользователю?** *Users → пользователь → Role mapping
   → Assign role* → `tcbot-admin`.
3. **Добавлены ли client scopes клиенту?** *Clients → клиент → Client scopes*
   → `roles` и `groups` как default.
4. **Совпадают ли имена ролей** с `SSO_ADMIN_ROLES` / `SSO_VIEWER_ROLES`.

Роли читаются из трёх источников — `access_token`, `id_token` и `userinfo`;
поддерживаются `realm_access.roles`, `resource_access.<client>.roles`,
`groups` (берётся последний сегмент пути) и плоский список `roles`.

Если ролей нет вовсе, в лог пишется предупреждение со списком фактически
пришедших claims.

### Проверка токенов

- подпись RS256 по JWKS Keycloak (через `PyJWT[crypto]`);
- `iss`, `aud`, `exp`, `nonce`;
- если `PyJWT` не установлен, подпись не сверяется, но в лог пишется
  предупреждение (проверка claims всё равно выполняется).

Сессия — подписанная HMAC-SHA256 cookie (`HttpOnly`, `SameSite=Lax`, опционально
`Secure`).

## Локальный администратор

Резервный вход, который работает **даже если Keycloak недоступен**.

```
LOCAL_ADMIN_ENABLED=true
LOCAL_ADMIN_USERNAME=local-admin
LOCAL_ADMIN_PASSWORD=            # только для первого запуска
LOCAL_ADMIN_PASSWORD_HASH=       # либо готовый хэш
```

### Первый запуск

1. `LOCAL_ADMIN_PASSWORD=...` — при старте пароль сразу преобразуется в хэш.
2. Ничего не задавать — пароль **генерируется автоматически** и однократно
   записывается в файл `local-admin-initial-password.txt`. После смены пароля
   файл удаляется автоматически.

Получить хэш для `LOCAL_ADMIN_PASSWORD_HASH`:

```bash
python -c "from tcbot.localadmin import hash_password; print(hash_password('пароль'))"
```

**Если заданы оба параметра**, используется `LOCAL_ADMIN_PASSWORD`. Хэш
проверяется на формат: если в `LOCAL_ADMIN_PASSWORD_HASH` по ошибке записан
`client_secret` или обычный пароль, значение игнорируется с ошибкой в логе.

### Хранение и защита

- пароль хранится только как **PBKDF2-HMAC-SHA256** (260 000 итераций,
  случайная соль 16 байт) в `bot_state.json`;
- сравнение постоянного времени;
- **защита от подбора**: 5 неудач по паре (IP, логин) → блокировка 60 с,
  затем 300 и 900 с. Блокировка привязана к IP;
- требования к паролю: минимум 12 символов, буквы и цифры;
- смена пароля — в панели на странице «Локальный вход» или через API.

## Роли

| Роль | Доступ |
|---|---|
| `admin` | полный, включая изменения |
| `viewer` | только чтение (`GET`/`HEAD`/`OPTIONS`) |

Пользователи из `ADMIN_IDS` получают полный доступ автоматически — сравнение
идёт по логину, e-mail и по логину без домена (`admin` = `admin@example.com`).

Все изменения требуют роли администратора: попытка `viewer` выполнить `POST`
возвращает `403`.

## Разделы панели

На главной — только состояние сервиса и логи. Остальное — отдельные страницы
из меню аватара:

| Страница | Назначение |
|---|---|
| `/` | компактное состояние (метрики, heartbeat) и логи |
| `/channels` | каналы: поиск, сортировка, пагинация, редактирование |
| `/outbox` | очередь недоставленных |
| `/send` | ручная отправка сообщения |
| `/settings` | параметры удаления и ограничений |
| `/admins` | администраторы бота |
| `/local-admin` | смена пароля локального администратора |

## Эндпоинты

### Служебные

| Путь | Назначение |
|---|---|
| `/health`, `/live` | живость процесса, всегда 200 |
| `/ready` | готовность: 200 только когда WebSocket подключён и бот авторизован |

### Вебхуки

`POST /webhook?channel=<имя>` — также `/zabbix-webhook`, `/api/webhook`.
Авторизация SSO к ним не применяется.

### Авторизация

| Путь | Назначение |
|---|---|
| `/login` | страница выбора способа входа |
| `/auth/login` | старт OIDC-входа |
| `/auth/callback` | обмен кода на токены |
| `/auth/local` | вход по логину и паролю |
| `/auth/logout` | выход |
| `/api/me` | текущий пользователь и права |

### API панели

| Метод и путь | Назначение |
|---|---|
| `GET /api/status` | состояние, статистика, очередь, события |
| `GET/POST /api/channels` | список и создание канала |
| `PUT/DELETE /api/channels/{name}` | изменение и удаление канала |
| `GET/POST /api/admins` | администраторы |
| `DELETE /api/admins/{id}` | удалить администратора |
| `GET/POST /api/settings` | параметры |
| `POST /api/send` | отправить сообщение |
| `POST /api/reconnect` | пересоздать соединение |
| `GET/POST /api/outbox` | очередь (`?action=flush\|clear`) |
| `GET /api/logs` | чтение логов |
| `GET/POST /api/local-admin` | локальная учётная запись |
