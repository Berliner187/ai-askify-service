"""
Клиент Яндекс ID: OAuth 2.0 Authorization Code + PKCE.

Чистый HTTP-слой: ничего не знает о моделях, сессиях и пользователях.
Документация: https://yandex.ru/dev/id/doc/ru/codes/code-url
             https://yandex.ru/dev/id/doc/ru/user-information
"""
import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
TOKEN_URL = "https://oauth.yandex.ru/token"
USERINFO_URL = "https://login.yandex.ru/info"

# Телефон в приложении разрешён, но не запрашиваем: лишний пункт на экране согласия.
DEFAULT_SCOPE = "login:info login:email"

# (connect, read) секунд
TIMEOUT = (5, 10)


class YandexOAuthError(Exception):
    """Сбой на стороне Яндекса или сети. code — машинный код для логов."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class YandexProfile:
    uid: str
    login: str
    email: str
    first_name: str
    last_name: str
    display_name: str
    real_name: str
    raw: dict = field(repr=False, default_factory=dict)


def make_state():
    return secrets.token_urlsafe(32)


def make_pkce_pair():
    """(code_verifier, code_challenge) по RFC 7636, метод S256."""
    verifier = secrets.token_urlsafe(64)  # 86 символов, допустимо 43..128
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(client_id, redirect_uri, state, code_challenge,
                        scope=DEFAULT_SCOPE, force_confirm=False):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if force_confirm:
        # Заставляет Яндекс заново показать согласие и выбор аккаунта
        params["force_confirm"] = "yes"
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _json(resp):
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def exchange_code(code, client_id, client_secret, code_verifier, http=requests):
    """Код подтверждения -> access_token. Код живёт 10 минут и одноразовый."""
    try:
        resp = http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
            },
            auth=(client_id, client_secret),  # Authorization: Basic base64(id:secret)
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise YandexOAuthError("token_network", type(exc).__name__) from exc

    payload = _json(resp)
    token = payload.get("access_token")
    if resp.status_code != 200 or not token:
        raise YandexOAuthError(
            "token_rejected",
            f"http={resp.status_code} error={payload.get('error')} "
            f"desc={payload.get('error_description')}",
        )
    return token


def fetch_profile(access_token, expected_client_id=None, http=requests):
    """access_token -> YandexProfile."""
    try:
        resp = http.get(
            USERINFO_URL,
            params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise YandexOAuthError("info_network", type(exc).__name__) from exc

    data = _json(resp)
    uid = str(data.get("id") or "").strip()
    if resp.status_code != 200 or not uid:
        raise YandexOAuthError("info_rejected", f"http={resp.status_code}")

    # Токен должен быть выдан именно нашему приложению
    if expected_client_id and data.get("client_id") and data["client_id"] != expected_client_id:
        raise YandexOAuthError("client_mismatch", str(data.get("client_id")))

    def s(key):
        return str(data.get(key) or "").strip()

    return YandexProfile(
        uid=uid,
        login=s("login"),
        email=s("default_email").lower(),
        first_name=s("first_name"),
        last_name=s("last_name"),
        display_name=s("display_name"),
        real_name=s("real_name"),
        raw=data,
    )
