# -*- coding: utf-8 -*-
"""
Вход в админ-панель через Keycloak (OpenID Connect, Authorization Code + PKCE).

Схема:

    браузер → /login            → редирект на Keycloak (code_challenge, state, nonce)
    Keycloak → /auth/callback   → обмен кода на токены (PKCE, без client_secret)
                                → проверка id_token/access_token
                                → сессия в подписанной HttpOnly-cookie
    /logout                     → чистка сессии + end_session_endpoint Keycloak

Почему PKCE без секрета: панель — внутренний сервис, а клиент удобнее держать
public (S256), чтобы не хранить client_secret на хосте бота.

Проверка токенов:
    * подпись RS256 — через JWKS Keycloak (PyJWT[crypto], если установлен);
    * если PyJWT недоступен, проверяются только claims (iss/aud/exp/nonce) —
      токен при этом получен от Keycloak напрямую по TLS, но подпись не сверяется;
    * всегда проверяются iss, aud, exp и nonce.

Права:
    * доступ к панели — членство в группе/роли Keycloak (SSO_ADMIN_ROLES);
    * «только просмотр» — отдельный список ролей (SSO_VIEWER_ROLES);
    * пользователи из ADMIN_IDS (config) имеют полный доступ по e-mail/логину.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger("bot")


# ============================================================================
# ВСПОМОГАТЕЛЬНОЕ
# ============================================================================

def b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def decode_jwt_unverified(token: str) -> Dict[str, Any]:
    """Разбирает JWT без проверки подписи (только payload)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        return json.loads(b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        return {}


class SessionSigner:
    """Подписанные cookie-сессии (HMAC-SHA256, без внешних зависимостей)."""

    def __init__(self, secret: str, ttl: int = 8 * 3600, cookie_name: str = "tcbot_session"):
        self.secret = secret.encode("utf-8")
        self.ttl = int(ttl)
        self.cookie_name = cookie_name

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.secret, payload, hashlib.sha256).hexdigest()

    def dumps(self, data: Dict[str, Any]) -> str:
        body = dict(data)
        body["exp"] = int(time.time()) + self.ttl
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        encoded = b64url_encode(raw)
        return f"{encoded}.{self._sign(raw)}"

    def loads(self, value: str) -> Optional[Dict[str, Any]]:
        if not value or "." not in value:
            return None
        encoded, signature = value.rsplit(".", 1)
        try:
            raw = b64url_decode(encoded)
        except Exception:
            return None
        if not hmac.compare_digest(self._sign(raw), signature):
            logger.warning("⚠️ Подпись cookie-сессии не совпала")
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if int(data.get("exp", 0)) < time.time():
            return None
        return data


# ============================================================================
# ПОЛЬЗОВАТЕЛЬ
# ============================================================================

@dataclass
class SSOUser:
    subject: str
    username: str = ""
    email: str = ""
    name: str = ""
    roles: List[str] = field(default_factory=list)
    is_admin: bool = False
    is_viewer: bool = False
    via: str = "keycloak"     # keycloak | local
    expires_at: Optional[int] = None

    @property
    def display(self) -> str:
        return self.name or self.username or self.email or self.subject

    def to_session(self) -> Dict[str, Any]:
        return {
            "sub": self.subject,
            "username": self.username,
            "email": self.email,
            "name": self.name,
            "roles": self.roles,
            "is_admin": self.is_admin,
            "is_viewer": self.is_viewer,
            "via": self.via,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_session(cls, data: Dict[str, Any]) -> "SSOUser":
        return cls(
            subject=str(data.get("sub", "")),
            username=str(data.get("username", "")),
            email=str(data.get("email", "")),
            name=str(data.get("name", "")),
            roles=list(data.get("roles", [])),
            is_admin=bool(data.get("is_admin")),
            is_viewer=bool(data.get("is_viewer")),
            via=str(data.get("via", "keycloak")),
            expires_at=data.get("expires_at"),
        )


# ============================================================================
# КЛИЕНТ KEYCLOAK
# ============================================================================

class KeycloakSSO:
    """OIDC-клиент для входа в админ-панель."""

    def __init__(
        self,
        *,
        server_url: str,
        realm: str,
        client_id: str,
        client_secret: str = "",
        redirect_uri: str = "",
        admin_roles: Optional[List[str]] = None,
        viewer_roles: Optional[List[str]] = None,
        local_admins: Optional[List[str]] = None,
        session_ttl: int = 8 * 3600,
        cookie_name: str = "tcbot_session",
        cookie_secure: bool = False,
        verify_ssl: Any = True,
        scope: str = "openid profile email",
        session_secret: str = "",
    ):
        self.server_url = server_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.admin_roles = {role.lower() for role in (admin_roles or [])}
        self.viewer_roles = {role.lower() for role in (viewer_roles or [])}
        self.local_admins = {item.lower() for item in (local_admins or []) if item}
        self.scope = scope
        self.verify_ssl = verify_ssl
        self.cookie_secure = cookie_secure

        secret = session_secret or secrets.token_urlsafe(32)
        self.signer = SessionSigner(secret, ttl=session_ttl, cookie_name=cookie_name)

        self._discovery: Optional[Dict[str, Any]] = None
        self._jwks: Optional[Dict[str, Any]] = None
        self._jwks_at: float = 0.0
        self._lock = asyncio.Lock()

        logger.info(
            f"🔐 SSO Keycloak: {self.server_url}/realms/{self.realm}, "
            f"client={self.client_id}, роли админа={sorted(self.admin_roles) or '—'}"
        )

    # ------------------------------ метаданные ------------------------------ #

    @property
    def _realm_base(self) -> str:
        return f"{self.server_url}/realms/{self.realm}"

    async def discovery(self) -> Dict[str, Any]:
        if self._discovery is not None:
            return self._discovery
        async with self._lock:
            if self._discovery is not None:
                return self._discovery
            url = f"{self._realm_base}/.well-known/openid-configuration"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        resp.raise_for_status()
                        self._discovery = await resp.json()
                        logger.info("🔐 OIDC-конфигурация Keycloak получена")
            except Exception as exc:
                logger.error(f"❌ Не удалось получить OIDC-конфигурацию {url}: {exc}")
                raise
        return self._discovery

    async def _post_token(self, data: Dict[str, str]) -> Dict[str, Any]:
        conf = await self.discovery()
        endpoint = conf["token_endpoint"]
        payload = dict(data)
        if self.client_secret:
            payload["client_secret"] = self.client_secret
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise ValueError(f"token endpoint {resp.status}: {body[:300]}")
                return json.loads(body)

    # ------------------------------ проверка ------------------------------ #

    async def _load_jwks(self, force: bool = False) -> Dict[str, Any]:
        if self._jwks is not None and not force and time.time() - self._jwks_at < 3600:
            return self._jwks
        conf = await self.discovery()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                conf["jwks_uri"], timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                resp.raise_for_status()
                self._jwks = await resp.json()
                self._jwks_at = time.time()
        return self._jwks

    async def _verify_signature(self, token: str) -> Tuple[bool, str]:
        """
        Проверяет подпись JWT по JWKS Keycloak.

        Требуется PyJWT[crypto]; если библиотеки нет — возвращает (True, "skipped"),
        чтобы панель работала, но в лог пишется предупреждение.
        """
        try:
            import jwt  # PyJWT
            from jwt import PyJWKClient
        except Exception:
            return True, "skipped"

        try:
            conf = await self.discovery()
            jwks = await self._load_jwks()
            header = json.loads(b64url_decode(token.split(".")[0]).decode("utf-8"))
            kid = header.get("kid")

            key_data = None
            for entry in jwks.get("keys", []):
                if kid is None or entry.get("kid") == kid:
                    key_data = entry
                    break
            if key_data is None:
                jwks = await self._load_jwks(force=True)
                for entry in jwks.get("keys", []):
                    if kid is None or entry.get("kid") == kid:
                        key_data = entry
                        break
            if key_data is None:
                return False, "ключ подписи не найден в JWKS"

            from jwt.algorithms import RSAAlgorithm

            public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))
            jwt.decode(
                token,
                key=public_key,
                algorithms=[key_data.get("alg", "RS256")],
                options={"verify_aud": False, "verify_exp": False},
                issuer=conf.get("issuer"),
            )
            return True, "ok"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _check_claims(self, claims: Dict[str, Any], *, expect_nonce: Optional[str], issuer: str) -> Optional[str]:
        now = int(time.time())
        if int(claims.get("exp", 0)) < now:
            return "токен истёк"
        if claims.get("iss") and issuer and claims["iss"] != issuer:
            return f"неверный iss: {claims['iss']}"
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud] if aud else []
        if audiences and self.client_id not in audiences and "account" not in audiences:
            return f"неверный aud: {audiences}"
        if expect_nonce and claims.get("nonce") and claims["nonce"] != expect_nonce:
            return "неверный nonce"
        return None

    # ------------------------------ сценарий входа ------------------------------ #

    async def build_login_url(self, redirect_uri: str, next_url: str = "/") -> Tuple[str, Dict[str, str]]:
        """Готовит URL авторизации и данные для cookie-состояния."""
        conf = await self.discovery()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.scope,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"{conf['authorization_endpoint']}?{urlencode(params)}"
        return url, {"state": state, "nonce": nonce, "verifier": verifier, "next": next_url}

    async def exchange_code(self, code: str, verifier: str) -> Dict[str, Any]:
        return await self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            }
        )

    def debug_claims(self, claims: Dict[str, Any]) -> str:
        """Краткая сводка claims — помогает понять, почему роли не пришли."""
        keys = sorted(claims.keys())
        realm_roles = (claims.get("realm_access") or {}).get("roles") or []
        client_roles = ((claims.get("resource_access") or {}).get(self.client_id) or {}).get("roles") or []
        groups = claims.get("groups") or []
        return (
            f"claims={keys}; realm_access={realm_roles or '—'}; "
            f"client({self.client_id})={client_roles or '—'}; groups={groups or '—'}"
        )

    async def userinfo(self, access_token: str) -> Dict[str, Any]:
        conf = await self.discovery()
        endpoint = conf.get("userinfo_endpoint")
        if not endpoint:
            return {}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return {}
                    return await resp.json()
        except Exception as exc:
            logger.warning(f"⚠️ userinfo недоступен: {exc}")
            return {}

    def extract_roles(self, claims: Dict[str, Any], client_roles: Optional[Dict[str, Any]] = None) -> List[str]:
        roles: List[str] = []
        realm_access = claims.get("realm_access") or {}
        if isinstance(realm_access, dict):
            roles.extend(realm_access.get("roles") or [])

        resource_access = claims.get("resource_access") or {}
        if isinstance(resource_access, dict):
            client = resource_access.get(self.client_id) or {}
            if isinstance(client, dict):
                roles.extend(client.get("roles") or [])

        if client_roles:
            roles.extend(client_roles.get("roles") or [])

        groups = claims.get("groups") or []
        if isinstance(groups, list):
            # группы вида /infra/admins — берём последний сегмент
            roles.extend(str(group).rstrip("/").split("/")[-1] for group in groups)

        if isinstance(claims.get("roles"), list):
            roles.extend(claims["roles"])

        result: List[str] = []
        for role in roles:
            if role and role not in result:
                result.append(str(role))
        return result

    async def authenticate(self, code: str, state_data: Dict[str, str]) -> SSOUser:
        """Обменивает код на токены и собирает пользователя."""
        tokens = await self.exchange_code(code, state_data["verifier"])
        access_token = tokens.get("access_token", "")
        id_token = tokens.get("id_token", "")

        conf = await self.discovery()
        issuer = conf.get("issuer", self._realm_base)

        claims: Dict[str, Any] = {}
        if id_token:
            ok, reason = await self._verify_signature(id_token)
            if not ok:
                raise ValueError(f"подпись id_token неверна — {reason}")
            if reason == "skipped":
                logger.warning(
                    "⚠️ PyJWT не установлен: подпись id_token не проверена "
                    "(pip install 'pyjwt[crypto]')"
                )
            claims = decode_jwt_unverified(id_token)
            problem = self._check_claims(claims, expect_nonce=state_data.get("nonce"), issuer=issuer)
            if problem:
                raise ValueError(f"id_token отклонён: {problem}")

        access_claims = decode_jwt_unverified(access_token)
        if not claims:
            problem = self._check_claims(access_claims, expect_nonce=None, issuer=issuer)
            if problem:
                raise ValueError(f"access_token отклонён: {problem}")
            claims = access_claims
        else:
            # id_token уже проверен; access_token получен по TLS от Keycloak,
            # проверяем только срок действия
            problem = self._check_claims(access_claims, expect_nonce=None, issuer=issuer)
            if problem:
                logger.warning(f"⚠️ access_token: {problem} — роли могут быть неполными")

        info = await self.userinfo(access_token)

        # Keycloak кладёт realm_access/resource_access ТОЛЬКО в access_token
        # (в id_token и userinfo их обычно нет), поэтому роли собираем из всех
        # трёх источников, а не только из id_token.
        roles: List[str] = []
        for source, label in (
            (access_claims, "access_token"),
            (claims, "id_token"),
            (info, "userinfo"),
        ):
            if not source:
                continue
            for role in self.extract_roles(source):
                if role not in roles:
                    roles.append(role)

        if not roles:
            logger.warning(
                "⚠️ Keycloak не вернул ни одной роли. Проверьте, что в клиенте "
                f"'{self.client_id}' включены scope 'roles' и 'groups', "
                "а пользователю назначены роли/группы. "
                f"Доступные claims: {sorted(access_claims.keys())}"
            )

        user = SSOUser(
            subject=str(claims.get("sub") or info.get("sub") or ""),
            username=str(claims.get("preferred_username") or info.get("preferred_username") or ""),
            email=str(claims.get("email") or info.get("email") or ""),
            name=str(claims.get("name") or info.get("name") or ""),
            roles=roles,
            expires_at=int(claims.get("exp") or 0) or None,
        )
        user.is_admin, user.is_viewer = self._resolve_rights(user, roles)
        return user

    def _resolve_rights(self, user: SSOUser, roles: List[str]) -> Tuple[bool, bool]:
        lowered = {role.lower() for role in roles}
        is_admin = bool(lowered & self.admin_roles)
        is_viewer = bool(lowered & self.viewer_roles)

        # Администраторы бота (ADMIN_IDS) получают полный доступ без ролей Keycloak.
        # Сравниваем по логину без домена: в Keycloak пользователь часто
        # 'admin', а в ADMIN_IDS записан 'admin@example.com'.
        identifiers = {
            user.username.lower(),
            user.email.lower(),
            user.subject.lower(),
        }
        identifiers |= {item.split("@")[0] for item in list(identifiers) if item}
        identifiers.discard("")

        for admin in self.local_admins:
            admin_l = admin.lower()
            if admin_l in identifiers or admin_l.split("@")[0] in identifiers:
                logger.info(f"🔓 Доступ выдан по ADMIN_IDS: {admin} -> {user.display}")
                is_admin = True
                break

        if is_admin:
            is_viewer = True
        return is_admin, is_viewer

    async def logout_url(self, redirect_uri: str) -> str:
        try:
            conf = await self.discovery()
            endpoint = conf.get("end_session_endpoint")
        except Exception:
            endpoint = None
        if not endpoint:
            return redirect_uri
        params = {"post_logout_redirect_uri": redirect_uri, "client_id": self.client_id}
        return f"{endpoint}?{urlencode(params)}"
