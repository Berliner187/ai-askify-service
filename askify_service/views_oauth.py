"""
Вход через Яндекс ID.

  GET /auth/yandex/            -> yandex_start: state + PKCE в сессию, редирект в Яндекс
  GET /auth/yandex/callback/   -> yandex_callback: проверка state, обмен кода, вход

"""
import hmac
import logging
import time

from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from askify_app.middleware import check_blocked, check_legal_process
from askify_service.services.accounts import AccountError, login_or_register_with_yandex
from askify_service.services.yandex_oauth import (
    YandexOAuthError,
    build_authorize_url,
    exchange_code,
    fetch_profile,
    make_pkce_pair,
    make_state,
)
from askify_service.utils import get_client_ip

log = logging.getLogger("askify_app")

SESSION_KEY = "yandex_oauth"
STATE_TTL = 10 * 60
DEFAULT_NEXT = "/create/"
AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _cfg():
    cfg = getattr(settings, "YANDEX_OAUTH", None) or {}
    missing = [k for k in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI") if not cfg.get(k)]
    if missing:
        raise ImproperlyConfigured(f"YANDEX_OAUTH: не заданы {', '.join(missing)}")
    return cfg


def _safe_next(request, url):
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return ""


def _fail(request, message, status=400):
    return render(
        request,
        "login.html",
        {"error": message, "debug": settings.DEBUG, "next_url": DEFAULT_NEXT},
        status=status,
    )


@check_blocked
@check_legal_process
@require_GET
def yandex_start(request):
    if request.user.is_authenticated:
        return redirect(DEFAULT_NEXT)

    cfg = _cfg()
    state = make_state()
    verifier, challenge = make_pkce_pair()
    request.session[SESSION_KEY] = {
        "state": state,
        "verifier": verifier,
        "next": _safe_next(request, request.GET.get("next", "")),
        "ts": int(time.time()),
    }

    url = build_authorize_url(
        client_id=cfg["CLIENT_ID"],
        redirect_uri=cfg["REDIRECT_URI"],
        state=state,
        code_challenge=challenge,
        # ?switch=1 — выбрать другой аккаунт Яндекса (и для тестов)
        force_confirm=request.GET.get("switch") == "1",
    )
    log.info(
        f"YANDEX_OAUTH start ip={get_client_ip(request)} "
        f"client_id={cfg['CLIENT_ID'][:6]}... redirect_uri={cfg['REDIRECT_URI']}"
    )
    return redirect(url)


@check_blocked
@require_GET
def yandex_callback(request):
    ip = get_client_ip(request)
    stash = request.session.pop(SESSION_KEY, None)  # одноразовый

    if request.user.is_authenticated:
        # Повторный заход на callback (кнопка «Назад», перезагрузка, предпросмотр ссылки):
        # вход уже выполнен, показывать ошибку незачем.
        log.info(f"YANDEX_OAUTH duplicate_callback user={request.user.username} ip={ip}")
        return redirect((stash or {}).get("next") or DEFAULT_NEXT)

    error = request.GET.get("error")
    if error:
        log.info(f"YANDEX_OAUTH provider_error={error} ip={ip}")
        if error == "access_denied":
            return _fail(request, "Вход через Яндекс отменён.")
        return _fail(request, "Яндекс не подтвердил вход. Попробуйте ещё раз или войдите по email.")

    state = request.GET.get("state", "")
    code = request.GET.get("code", "")

    if not stash or not state or not hmac.compare_digest(stash.get("state", ""), state):
        log.warning(
            f"YANDEX_OAUTH bad_state has_stash={bool(stash)} "
            f"has_cookie={settings.SESSION_COOKIE_NAME in request.COOKIES} "
            f"host={request.get_host()} ip={ip} "
            f"ua={request.META.get('HTTP_USER_AGENT', '')[:80]}"
        )
        return _fail(request, "Сессия входа устарела. Нажмите «Войти с Яндекс ID» ещё раз.")

    if time.time() - stash.get("ts", 0) > STATE_TTL:
        log.info(f"YANDEX_OAUTH state_expired ip={ip}")
        return _fail(request, "Сессия входа устарела. Нажмите «Войти с Яндекс ID» ещё раз.")

    if not code:
        log.warning(f"YANDEX_OAUTH no_code ip={ip}")
        return _fail(request, "Яндекс не вернул код входа. Попробуйте ещё раз.")

    cfg = _cfg()
    try:
        token = exchange_code(code, cfg["CLIENT_ID"], cfg["CLIENT_SECRET"], stash["verifier"])
        profile = fetch_profile(token, expected_client_id=cfg["CLIENT_ID"])
        user, created, demo_survey_id = login_or_register_with_yandex(request, profile)
    except YandexOAuthError as exc:
        log.error(f"YANDEX_OAUTH provider_fail code={exc.code} detail={exc.detail} ip={ip}")
        return _fail(request, "Не удалось связаться с Яндексом. Попробуйте ещё раз или войдите по email.", 502)
    except AccountError as exc:
        log.warning(f"YANDEX_OAUTH account_fail code={exc.code} ip={ip}")
        return _fail(request, exc.message)

    login(request, user, backend=AUTH_BACKEND)
    request.session["user_id"] = user.id
    log.info(f"YANDEX_OAUTH success user={user.username} created={created} ip={ip}")

    if demo_survey_id:
        return redirect(f"/c/{demo_survey_id}/")
    return redirect(stash.get("next") or DEFAULT_NEXT)
