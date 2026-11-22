"""
Реклама для бесплатных пользователей: Gradius API v1 (https://docs.gradius.pro/llms.txt).

Используем метод Generation (мы генерируем артефакт — тест — по текстовому запросу):
    POST https://api.adlean.pro/v1/native/generation_model/chat?chat_id=..&user_id=..&lang=ru
    Заголовки: Auth: <ключ>, Accept/Content-Type: application/json
    Тело:      {"text": "<запрос>", "user_metadata": {...}}
    Ответ:     {"have_ads": true, "content": "<markdown со ссылкой>", "cta_link": "...", ...}
               без рекламы: {"have_ads": false}  (это норма, не ошибка и не повод ретраить)

Настройки (.env / settings):
    AD_API_TOKEN  — ключ издателя (только на сервере; в логи не пишем)
    AD_API_BASE   — необязательно, по умолчанию https://api.adlean.pro
    ADS_ENABLED   — в settings, рубильник (по умолчанию True)
(AD_API_URL со старым /engine/send_message больше не используется.)

Поток: вьюха генерации -> queue_ad_for_survey (создаёт строку AdEvent "queued") -> Celery fetch_ad_for_test
(tasks.py) -> run_ad_fetch (обновляет AdEvent: found / empty / error + цены) ->
кэш ad_content_<survey_id> (без срока жизни: по правилам Gradius объявление не убирают по таймеру) ->
GET /api/ad/v1/<id>/ -> блок #ad-slot на странице теста ->
POST /api/ad/v1/<id>/event/ (view / click) -> счётчики в AdEvent -> виджеты «Реклама» в админ-дашборде.

Вся запись статистики в БД необязательна для работы рекламы: любая ошибка БД (например, не применена
миграция) только пишется в лог и рекламу не ломает.
"""
import hashlib
import html as _html
import json
import logging
import os
import re
import time

import markdown
import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

tracer_l = logging.getLogger("askify_app")

DEFAULT_BASE = "https://api.adlean.pro"
GENERATION_PATH = "/v1/native/generation_model/chat"

AD_EMPTY_TTL = 15 * 60      # «рекламы нет / сбой»: страница перестаёт опрашивать, повторов в цикле нет
AD_LOCK_TTL = 120           # защита от двойной постановки задачи
VIEW_DEDUP_TTL = 30 * 60    # один посетитель = один показ теста за 30 минут
CLICK_DEDUP_TTL = 5         # защита от дребезга клика


# ----------------------------------------------------------------------------
# Кому показывать
# ----------------------------------------------------------------------------
def ads_enabled() -> bool:
    return bool(getattr(settings, "ADS_ENABLED", True))


def has_ever_paid(staff_id) -> bool:
    """Хотя бы один завершённый платёж за всё время (как is_veteran в create_payment)."""
    if not staff_id:
        return False
    from .models import Payment
    return Payment.objects.filter(staff_id=staff_id, status="completed").exists()


def ad_eligible(staff_id, sub_level) -> bool:
    """Есть идентификатор, нет подписки/пакетов (get_subscription_level < 1) и ни разу не платил."""
    if not ads_enabled() or not staff_id:
        return False
    try:
        if int(sub_level or 0) >= 1:
            return False
        return not has_ever_paid(staff_id)
    except Exception as exc:  # реклама не должна ронять страницу
        tracer_l.warning(f"ADS eligible check failed: {exc}")
        return False


# ----------------------------------------------------------------------------
# Что отправляем в сеть: минимум (название + 3 формулировки вопросов), без исходного текста
# ----------------------------------------------------------------------------
def _anon_id(staff_id) -> str:
    """Стабильный непустой user_id (требование Gradius) без реального идентификатора пользователя."""
    salt = str(getattr(settings, "SECRET_KEY", ""))[:16]
    return hashlib.sha256(f"{salt}:{staff_id}".encode()).hexdigest()[:16]


def build_ad_text(title, questions) -> str:
    q_texts = []
    for q in (questions or [])[:3]:
        t = (q.get("question") or q.get("text") or "") if isinstance(q, dict) else str(q)
        t = " ".join(str(t).split())
        if t:
            q_texts.append(t[:160])
    head = " ".join(str(title or "Тест").split())[:160]
    text = f"Тест: {head}"
    if q_texts:
        text += ". Вопросы: " + " ".join(q_texts)
    return text[:600]


# ----------------------------------------------------------------------------
# Трассировка решений (видна и в логе, и в кэше: cache.get("ad_trace_<id>"))
# ----------------------------------------------------------------------------
def _trace(survey_id, text):
    tracer_l.info(f"ADS {survey_id}: {text}")
    try:
        cache.set(f"ad_trace_{survey_id}", f"{time.strftime('%H:%M:%S')} {text}", 24 * 3600)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Статистика в БД (модель AdEvent). Любая ошибка здесь глотается: реклама важнее статистики.
# ----------------------------------------------------------------------------
def _plain_snippet(markdown_text, limit=140) -> str:
    """Читаемый кусок рекламы для ленты в админке: без ссылок и разметки."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(markdown_text or ""))
    s = re.sub(r"[*_`#>]+", "", s)
    return " ".join(s.split())[:limit]


def _is_temp_guest(staff_id) -> bool:
    """Временный аккаунт: username начинается с guest_ (такие аккаунты потом удаляются)."""
    try:
        from .models import AuthUser
        return AuthUser.objects.filter(id_staff=staff_id, username__startswith="guest_").exists()
    except Exception as exc:
        tracer_l.warning(f"ADS guest check failed: {exc.__class__.__name__}: {exc}")
        return False


def _event_open(survey_id, source, is_guest):
    try:
        from .models import AdEvent
        AdEvent.objects.update_or_create(
            survey_id=str(survey_id),
            defaults={
                "status": "queued", "error_code": "", "source": source, "is_guest": bool(is_guest),
                "created_at": timezone.now(), "latency_ms": None, "show_price": 0, "click_price": 0,
                "snippet": "", "shown_count": 0, "click_count": 0,
                "first_shown_at": None, "last_click_at": None,
            },
        )
    except Exception as exc:
        tracer_l.warning(f"ADS {survey_id}: AdEvent open failed: {exc.__class__.__name__}: {exc}")


def _event_close(survey_id, status, started, error_code="", ad=None):
    try:
        from .models import AdEvent
        fields = {
            "status": status,
            "error_code": str(error_code or "")[:40],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        if ad:
            price = ad.get("price") or {}
            fields["show_price"] = _num(price.get("show_price"))
            fields["click_price"] = _num(price.get("click_price"))
            fields["snippet"] = _plain_snippet(ad.get("content"))
        AdEvent.objects.filter(survey_id=str(survey_id)).update(**fields)
    except Exception as exc:
        tracer_l.warning(f"ADS {survey_id}: AdEvent close failed: {exc.__class__.__name__}: {exc}")


def _num(value) -> float:
    try:
        n = float(value)
        return n if n >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------------
# Постановка задачи (из вьюхи; никогда не падает)
# ----------------------------------------------------------------------------
def queue_ad_for_survey(staff_id, sub_level, survey_id, title, questions, source="text", is_guest=False) -> bool:
    """
    source:   "text" (генерация из текста) или "file" (из файла) — для разреза в админке.
    is_guest: True для гостевой генерации — для разреза «гости / зарегистрированные».
    Оба аргумента необязательные: старые вызовы без них продолжают работать.
    """
    try:
        if not ads_enabled():
            _trace(survey_id, "skip: ADS_ENABLED=False")
            return False
        if not ad_eligible(staff_id, sub_level):
            _trace(survey_id, f"skip: not eligible (staff_id={staff_id}, sub_level={sub_level})")
            return False
        if not cache.add(f"ad_lock_{survey_id}", 1, AD_LOCK_TTL):
            _trace(survey_id, "skip: lock (уже ставили)")
            return False
        # Гость = временный аккаунт guest_*: он технически «авторизован», но потом удаляется,
        # поэтому признак фиксируем в событии сейчас, пока аккаунт существует.
        guest = bool(is_guest) or _is_temp_guest(staff_id)
        _event_open(survey_id, source if source in ("text", "file") else "text", guest)
        from .tasks import fetch_ad_for_test  # импорт внутри: tasks.py сам импортирует этот модуль
        res = fetch_ad_for_test.delay(
            text=build_ad_text(title, questions),
            chat_id=str(survey_id),
            user_id=_anon_id(staff_id),
        )
        _trace(survey_id, f"queued task {getattr(res, 'id', '?')}")
        return True
    except Exception as exc:
        _trace(survey_id, f"queue FAILED: {exc}")
        return False


# ----------------------------------------------------------------------------
# Запрос в Gradius и сохранение результата (вызывается из Celery-задачи)
# ----------------------------------------------------------------------------
def _credentials():
    token = getattr(settings, "AD_API_TOKEN", None) or os.getenv("AD_API_TOKEN") or ""
    base = getattr(settings, "AD_API_BASE", None) or os.getenv("AD_API_BASE") or DEFAULT_BASE
    return str(token).strip(), str(base).rstrip("/")


def run_ad_fetch(text, chat_id, user_id) -> dict:
    """
    Один запрос Generation. Возвращает {"state": "ready"|"empty"|"error", ...}.
    Можно вызывать руками из shell:  run_ad_fetch("Тест: Фотосинтез", "diag-1", "u1")
    """
    started = time.perf_counter()
    token, base = _credentials()
    if not token:
        tracer_l.error("ADS: AD_API_TOKEN не задан (.env) — реклама не запрашивается")
        store_empty(chat_id)
        _event_close(chat_id, "error", started, "no_token")
        return {"state": "error", "reason": "no_token"}

    try:
        resp = requests.post(
            base + GENERATION_PATH,
            params={"chat_id": str(chat_id), "user_id": str(user_id), "lang": "ru"},
            headers={"Auth": token, "Accept": "application/json", "Content-Type": "application/json"},
            json={"text": text, "user_metadata": {"platform": "web"}},
            timeout=(3.05, 10),
        )
    except requests.RequestException as exc:
        # сбой сети/таймаут: основной продукт работает без рекламы
        tracer_l.warning(f"ADS {chat_id}: сеть/таймаут: {exc.__class__.__name__}")
        store_empty(chat_id)
        _event_close(chat_id, "error", started, exc.__class__.__name__)
        return {"state": "error", "reason": exc.__class__.__name__}

    if resp.status_code == 401:
        tracer_l.error("ADS: 401 от Gradius — ключ AD_API_TOKEN отсутствует или неверный (ошибка конфигурации)")
        store_empty(chat_id)
        _event_close(chat_id, "error", started, "http_401")
        return {"state": "error", "status": 401}
    if resp.status_code >= 400:
        tracer_l.warning(f"ADS {chat_id}: HTTP {resp.status_code} {resp.text[:300]}")
        store_empty(chat_id)
        _event_close(chat_id, "error", started, f"http_{resp.status_code}")
        return {"state": "error", "status": resp.status_code}

    try:
        data = resp.json()
    except ValueError:
        tracer_l.warning(f"ADS {chat_id}: ответ не JSON")
        store_empty(chat_id)
        _event_close(chat_id, "error", started, "bad_json")
        return {"state": "error", "reason": "bad_json"}

    if isinstance(data, dict) and data.get("have_ads") and str(data.get("content") or "").strip():
        price = data.get("price") or {}
        tracer_l.info(f"ADS {chat_id}: AD FOUND show_price={price.get('show_price')} click_price={price.get('click_price')}")
        store_ad(chat_id, data)
        _event_close(chat_id, "found", started, ad=data)
        _trace(chat_id, "ad stored")
        return {"state": "ready"}

    # have_ads: false — это нормальный ответ, не ошибка и не повод ретраить
    store_empty(chat_id)
    _event_close(chat_id, "empty", started)
    _trace(chat_id, "gradius: no ads")
    return {"state": "empty"}


# ----------------------------------------------------------------------------
# Безопасная сборка блока. content — markdown рекламодателя, ему не доверяем,
# но ссылки (redirect Gradius) оставляем как есть: правила Gradius запрещают их менять.
# ----------------------------------------------------------------------------
_A_TAG = re.compile(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', re.S)


def _fix_link(m):
    href, label = m.group(1), m.group(2)
    if not href.lower().startswith(("https://", "http://")):
        return label                                     # javascript:, data: и т.п. — только текст
    return (f'<a data-ad-link href="{href}" target="_blank" '
            f'rel="sponsored nofollow noopener noreferrer" style="color:#a5b4fc">{label}</a>')


def render_ad_html(raw_markdown: str) -> str:
    # escape ДО markdown: любой <script>/<img onerror> становится текстом
    body = markdown.markdown(_html.escape(str(raw_markdown or ""), quote=False))
    body = _A_TAG.sub(_fix_link, body)
    return (
        '<div class="dv-card" style="padding:14px 16px;margin:16px 0">'
        '<div style="font-size:11px;color:#71717a;margin-bottom:8px">Реклама</div>'
        f'<div style="font-size:13.5px;line-height:1.55;color:#d4d4d8">{body}</div></div>'
    )


def store_ad(chat_id, ad: dict) -> None:
    """Без срока жизни: объявление не убирается по таймеру (правило Gradius)."""
    cache.set(f"ad_content_{chat_id}", {"html": render_ad_html(ad.get("content"))}, None)


def store_empty(chat_id) -> None:
    cache.set(f"ad_content_{chat_id}", {"empty": True}, AD_EMPTY_TTL)


# ----------------------------------------------------------------------------
# Чтение для /api/ad/v1/<id>/
# ----------------------------------------------------------------------------
def get_cached_ad(survey_id) -> dict:
    val = cache.get(f"ad_content_{survey_id}")
    if val is None:
        return {"html": None, "state": "pending"}
    if isinstance(val, dict) and val.get("html"):
        return {"html": val["html"], "state": "ready"}
    return {"html": None, "state": "none"}


# ----------------------------------------------------------------------------
# Приём событий со страницы: POST /api/ad/v1/<id>/event/   тело {"type": "view" | "click"}
# Публичная ручка (CSRF не нужен: ничего секретного, только счётчик). Всегда отвечает 204.
# ----------------------------------------------------------------------------
def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else "") or request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


@csrf_exempt
@require_POST
def ad_track_event(request, survey_id):
    try:
        try:
            payload = json.loads((request.body or b"{}").decode("utf-8", "ignore"))
        except ValueError:
            payload = {}
        kind = payload.get("type") if isinstance(payload, dict) else None
        if kind not in ("view", "click"):
            return HttpResponse(status=400)
        sid = str(survey_id)[:64]
        who = hashlib.sha1(f"{_client_ip(request)}|{request.META.get('HTTP_USER_AGENT', '')}".encode()).hexdigest()[:16]
        ttl = VIEW_DEDUP_TTL if kind == "view" else CLICK_DEDUP_TTL
        if not cache.add(f"ad_ev_{kind}_{sid}_{who}", 1, ttl):
            return HttpResponse(status=204)

        from django.db.models import F
        from .models import AdEvent
        now = timezone.now()
        rows = AdEvent.objects.filter(survey_id=sid, status="found")
        if kind == "view":
            rows.update(shown_count=F("shown_count") + 1)
            rows.filter(first_shown_at__isnull=True).update(first_shown_at=now)
        else:
            rows.update(click_count=F("click_count") + 1, last_click_at=now)
    except Exception as exc:
        tracer_l.warning(f"ADS track failed: {exc.__class__.__name__}: {exc}")
    return HttpResponse(status=204)
