"""
JSON-эндпоинты «Ситуационного центра» (templates/admin.html).

Модуль только читает данные и переиспользует хелперы из views.py.
Все изменения состояния (статусы платежей, подписки, тесты, API-ключи)
идут через уже существующие ручки:
    api_admin_set_payment_status, api_admin_grant_premium, api_admin_add_tests,
    api_key_save, api_key_toggle, api_key_test, api_key_delete, api_key_cleanup.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
import urllib.request

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.db.models.functions import Length, TruncDate
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import (
    APIKey,
    APIKeyUsage,
    AuthUser,
    Payment,
    Subscription,
    Survey,
    TestAttempt,
    TokensUsed,
    TrafficLog,
)
from .views import (
    AI_KEY_PURPOSES,
    AI_PROVIDER_PRESETS,
    MOSCOW_TZ,
    PULSE_PLAN_ORDER,
    _ensure_system_key,
    _key_price_per_1m,
    _mask_key,
    _pulse_model_label,
    _pulse_plan_label,
)

RANGE_DAYS = {"7D": 7, "30D": 30, "90D": 90, "1Y": 365}
MAX_SPAN_DAYS = 3 * 366
DEFAULT_ALL_SPAN_DAYS = 365
PAGE_SIZE = 25
HEALTHY_SUCCESS_RATE = 90.0
MIN_CALLS_FOR_HEALTH = 5
STALE_KEY_DAYS = 30
ONLINE_WINDOW_MIN = 5
PENDING_ALERT_HOURS = 1
MONTHS_RU = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
PAYMENT_STATUSES = ("pending", "completed", "failed")
CRITICAL_PURPOSES = ("SURVEY",)
ERROR_RATE_ALERT = 20.0
FREE_PLAN_NAMES = ("free_plan", "Стартовый")


# --------------------------------------------------------------------------- #
#  Инфраструктура
# --------------------------------------------------------------------------- #

def superuser_json(view):
    """403 JSON вместо редиректа + московская таймзона для __date-лукапов."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_superuser):
            return JsonResponse({"ok": False, "error": "Доступ только для суперпользователя"}, status=403)
        with timezone.override(MOSCOW_TZ):
            return view(request, *args, **kwargs)

    return wrapper


def _bucket_start(day: date, bucket: str) -> date:
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    if bucket == "month":
        return day.replace(day=1)
    return day


def _next_bucket(day: date, bucket: str) -> date:
    if bucket == "week":
        return day + timedelta(days=7)
    if bucket == "month":
        return (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return day + timedelta(days=1)


def _bucket_label(day: date, bucket: str) -> str:
    if bucket == "month":
        return f"{MONTHS_RU[day.month - 1]} {day.strftime('%y')}"
    return day.strftime("%d.%m")


class Period:
    """Выбранный период, равный ему предыдущий период и бакеты для графиков."""

    def __init__(self, key: str, start: date, end: date):
        self.key = key
        self.start = start
        self.end = end
        self.days = (end - start).days + 1
        self.prev_end = start - timedelta(days=1)
        self.prev_start = self.prev_end - timedelta(days=self.days - 1)
        if self.days <= 92:
            self.bucket = "day"
        elif self.days <= 400:
            self.bucket = "week"
        else:
            self.bucket = "month"

        self.keys: list[date] = []
        cursor = _bucket_start(start, self.bucket)
        while cursor <= end:
            self.keys.append(cursor)
            cursor = _next_bucket(cursor, self.bucket)
        self._index = {k: i for i, k in enumerate(self.keys)}

    @property
    def range(self):
        return (self.start, self.end)

    @property
    def prev_range(self):
        return (self.prev_start, self.prev_end)

    def slot(self, day):
        if day is None:
            return None
        if isinstance(day, datetime):
            day = day.date()
        return self._index.get(_bucket_start(day, self.bucket))

    def zeros(self):
        return [0.0] * len(self.keys)

    def as_dict(self):
        return {
            "key": self.key,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "prev_start": self.prev_start.isoformat(),
            "prev_end": self.prev_end.isoformat(),
            "days": self.days,
            "bucket": self.bucket,
            "labels": [_bucket_label(k, self.bucket) for k in self.keys],
        }


def _first_activity_date(today: date) -> date:
    candidates = []
    for value in (
        Payment.objects.aggregate(v=Min("created_at"))["v"],
        Survey.objects.aggregate(v=Min("created_at"))["v"],
        AuthUser.objects.aggregate(v=Min("date_joined"))["v"],
    ):
        if value:
            candidates.append(timezone.localtime(value, MOSCOW_TZ).date())
    if not candidates:
        return today - timedelta(days=DEFAULT_ALL_SPAN_DAYS - 1)
    return max(min(candidates), today - timedelta(days=MAX_SPAN_DAYS - 1))


def _parse_period(request, today: date) -> Period:
    key = (request.GET.get("range") or "30D").upper()

    if key == "CUSTOM":
        try:
            start = date.fromisoformat(request.GET.get("start_date") or "")
            end = date.fromisoformat(request.GET.get("end_date") or "")
        except ValueError:
            key = "30D"
        else:
            if start > end:
                start, end = end, start
            end = min(end, today)
            start = min(start, end)
            if (end - start).days + 1 > MAX_SPAN_DAYS:
                start = end - timedelta(days=MAX_SPAN_DAYS - 1)
            return Period("CUSTOM", start, end)

    if key == "ALL":
        return Period("ALL", _first_activity_date(today), today)

    if key not in RANGE_DAYS:
        key = "30D"
    return Period(key, today - timedelta(days=RANGE_DAYS[key] - 1), today)


def _by_day(qs, field: str, *extra: str, **aggregates):
    """Группировка по московскому дню. order_by() снимает Meta.ordering, иначе GROUP BY ломается."""
    if not aggregates:
        aggregates = {"v": Count("pk")}
    return list(
        qs.order_by()
        .annotate(_day=TruncDate(field, tzinfo=MOSCOW_TZ))
        .values("_day", *extra)
        .annotate(**aggregates)
    )


def _fold(period: Period, rows, value_key: str = "v", scale: float = 1.0):
    out = period.zeros()
    for row in rows:
        idx = period.slot(row["_day"])
        if idx is not None:
            out[idx] += float(row[value_key] or 0) * scale
    return out


def _round_list(values, digits=2):
    return [round(v, digits) for v in values]


def _metric(current, previous, digits: int = 0):
    current = round(float(current or 0), digits)
    previous = round(float(previous or 0), digits)
    delta = round((current - previous) / previous * 100.0, 1) if previous else None
    return {"value": current, "prev": previous, "delta": delta}


def _rate(ok, total):
    return round(ok / total * 100.0, 1) if total else None


def _rub(kopecks) -> float:
    return round(float(kopecks or 0) / 100.0, 2)


def _local_str(dt, fmt="%d.%m.%Y %H:%M"):
    return timezone.localtime(dt, MOSCOW_TZ).strftime(fmt) if dt else None


def _real_users():
    # Гостевые аккаунты имеют длинные служебные username — исключаем, как и в admin_stats.
    return AuthUser.objects.annotate(_ulen=Length("username")).filter(_ulen__lt=40)


def _purpose_items():
    """AI_KEY_PURPOSES в едином виде [(code, label)] + назначения, встречающиеся в БД."""
    raw = AI_KEY_PURPOSES
    items: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        items = [(str(k), str(v)) for k, v in raw.items()]
    else:
        for entry in raw or []:
            if isinstance(entry, (list, tuple)) and entry:
                code = str(entry[0])
                label = str(entry[1]) if len(entry) > 1 else code
            elif isinstance(entry, dict):
                code = str(entry.get("value") or entry.get("code") or entry.get("key") or entry.get("id") or "")
                label = str(entry.get("label") or entry.get("name") or code)
            else:
                code = label = str(entry)
            if code:
                items.append((code, label))
    known = {code for code, _ in items}
    for code in APIKey.objects.order_by().values_list("purpose", flat=True).distinct():
        if code and code not in known:
            items.append((code, code))
            known.add(code)
    return items


def _key_prices(keys):
    return {
        k.id: float(_key_price_per_1m(k.model_name, k.provider, k.cost_per_1m_tokens) or 0)
        for k in keys
    }


def _cost(tokens, price_per_1m) -> float:
    return (float(tokens or 0) / 1_000_000.0) * float(price_per_1m or 0)


def _ai_cost_between(day_range, prices) -> float:
    rows = (
        APIKeyUsage.objects.filter(timestamp__date__range=day_range)
        .order_by()
        .values("api_key_id")
        .annotate(t=Sum("tokens_used"))
    )
    return round(sum(_cost(r["t"], prices.get(r["api_key_id"], 0)) for r in rows), 4)


# --------------------------------------------------------------------------- #
#  Обзор: деньги, аудитория, продукт, здоровье, алерты
# --------------------------------------------------------------------------- #

@require_GET
@superuser_json
def admin_dashboard_overview_api(request):
    now = timezone.now()
    today = timezone.localdate()
    period = _parse_period(request, today)
    rng, prev = period.range, period.prev_range
    n = len(period.keys)

    # ---------- Выручка ----------
    paid = Payment.objects.filter(status="completed")
    paid_cur = paid.filter(created_at__date__range=rng)
    paid_prev = paid.filter(created_at__date__range=prev)

    rev_cur = _rub(paid_cur.aggregate(s=Sum("amount"))["s"])
    rev_prev = _rub(paid_prev.aggregate(s=Sum("amount"))["s"])
    rev_today = _rub(paid.filter(created_at__date=today).aggregate(s=Sum("amount"))["s"])
    pay_cnt_cur = paid_cur.count()
    pay_cnt_prev = paid_prev.count()
    payers_cur = paid_cur.order_by().values("staff_id").distinct().count()
    payers_prev = paid_prev.order_by().values("staff_id").distinct().count()

    plans = {
        label: {"label": label, "revenue": [0.0] * n, "count": [0.0] * n, "total": 0.0, "payments": 0}
        for label in PULSE_PLAN_ORDER
    }
    for row in _by_day(paid_cur, "created_at", "subscription__plan_name", s=Sum("amount"), c=Count("pk")):
        label = _pulse_plan_label(row["subscription__plan_name"])
        bucket = plans.setdefault(
            label, {"label": label, "revenue": [0.0] * n, "count": [0.0] * n, "total": 0.0, "payments": 0}
        )
        idx = period.slot(row["_day"])
        amount = _rub(row["s"])
        bucket["total"] += amount
        bucket["payments"] += row["c"]
        if idx is not None:
            bucket["revenue"][idx] += amount
            bucket["count"][idx] += row["c"]
    revenue_total_series = period.zeros()
    for p in plans.values():
        p["revenue"] = _round_list(p["revenue"])
        p["count"] = [int(v) for v in p["count"]]
        p["total"] = round(p["total"], 2)
        for i, v in enumerate(p["revenue"]):
            revenue_total_series[i] += v

    status_rows = (
        Payment.objects.filter(created_at__date__range=rng)
        .order_by()
        .values("status")
        .annotate(c=Count("pk"), s=Sum("amount"))
    )
    payment_status = {s: {"count": 0, "amount": 0.0} for s in PAYMENT_STATUSES}
    for row in status_rows:
        payment_status.setdefault(row["status"], {"count": 0, "amount": 0.0})
        payment_status[row["status"]] = {"count": row["c"], "amount": _rub(row["s"])}

    # ---------- Подписки ----------
    subs_active = Subscription.objects.filter(status="active", end_date__gt=now).count()
    subs_new_cur = Subscription.objects.filter(start_date__date__range=rng).count()
    subs_new_prev = Subscription.objects.filter(start_date__date__range=prev).count()
    subs_expiring_7d = (
        Subscription.objects.filter(status="active", end_date__gt=now, end_date__lte=now + timedelta(days=7))
        .exclude(plan_name__in=FREE_PLAN_NAMES)
        .count()
    )
    subs_series = _fold(period, _by_day(Subscription.objects.filter(start_date__date__range=rng), "start_date"))

    # ---------- Аудитория ----------
    users = _real_users()
    users_new_cur = users.filter(date_joined__date__range=rng).count()
    users_new_prev = users.filter(date_joined__date__range=prev).count()
    users_total = users.count()
    reg_series = _fold(period, _by_day(users.filter(date_joined__date__range=rng), "date_joined"))
    dau = users.filter(last_login__date=today).count()
    wau = users.filter(last_login__date__gte=today - timedelta(days=6)).count()
    mau = users.filter(last_login__date__gte=today - timedelta(days=29)).count()

    # ---------- Продукт ----------
    surveys_cur_qs = Survey.objects.filter(created_at__date__range=rng)
    gen_cur = surveys_cur_qs.count()
    gen_prev = Survey.objects.filter(created_at__date__range=prev).count()
    gen_total = Survey.objects.count()
    gen_series = _fold(period, _by_day(surveys_cur_qs, "created_at"))

    attempts_cur_qs = TestAttempt.objects.filter(created_at__date__range=rng)
    att_cur = attempts_cur_qs.count()
    att_prev = TestAttempt.objects.filter(created_at__date__range=prev).count()
    att_series = _fold(period, _by_day(attempts_cur_qs, "created_at"))
    score_expr = Avg(F("score") * 100.0 / F("total_questions"))
    score_cur = attempts_cur_qs.filter(total_questions__gt=0).aggregate(a=score_expr)["a"] or 0
    score_prev = (
        TestAttempt.objects.filter(created_at__date__range=prev, total_questions__gt=0).aggregate(a=score_expr)["a"]
        or 0
    )

    buckets = [0] * 10
    for score, total in attempts_cur_qs.filter(total_questions__gt=0).values_list("score", "total_questions").iterator(
        chunk_size=2000
    ):
        idx = min(int(score * 10 // total), 9) if total else 0
        buckets[max(idx, 0)] += 1

    reg_ids = users.filter(date_joined__date__range=rng).values("id_staff")
    funnel = [
        {"label": "Зарегистрировались", "value": users_new_cur},
        {
            "label": "Создали тест",
            "value": Survey.objects.filter(id_staff__in=reg_ids).order_by().values("id_staff").distinct().count(),
        },
        {
            "label": "Получили прохождение",
            "value": TestAttempt.objects.filter(survey__id_staff__in=reg_ids)
            .order_by()
            .values("survey__id_staff")
            .distinct()
            .count(),
        },
        {
            "label": "Оплатили",
            "value": Payment.objects.filter(status="completed", staff_id__in=reg_ids)
            .order_by()
            .values("staff_id")
            .distinct()
            .count(),
        },
    ]

    # ---------- Токены и деньги на AI ----------
    def _tokens(day_range):
        agg = TokensUsed.objects.filter(created_at__date__range=day_range).aggregate(
            s=Sum("tokens_survey_used"), f=Sum("tokens_feedback_used")
        )
        return int(agg["s"] or 0), int(agg["f"] or 0)

    tok_s_cur, tok_f_cur = _tokens(rng)
    tok_s_prev, tok_f_prev = _tokens(prev)

    keys = list(APIKey.objects.all())
    prices = _key_prices(keys)
    ai_cost_cur = _ai_cost_between(rng, prices)
    ai_cost_prev = _ai_cost_between(prev, prices)
    ai_cost_series = period.zeros()
    for row in _by_day(
        APIKeyUsage.objects.filter(timestamp__date__range=rng), "timestamp", "api_key_id", t=Sum("tokens_used")
    ):
        idx = period.slot(row["_day"])
        if idx is not None:
            ai_cost_series[idx] += _cost(row["t"], prices.get(row["api_key_id"], 0))
    ai_calls_cur = APIKeyUsage.objects.filter(timestamp__date__range=rng).count()

    # ---------- Здоровье системы ----------
    def _usage_day(day):
        return APIKeyUsage.objects.filter(timestamp__date=day).aggregate(
            calls=Count("pk"), ok=Count("pk", filter=Q(success=True)), ms=Avg("response_time_ms")
        )

    u_today = _usage_day(today)
    u_yday = _usage_day(today - timedelta(days=1))
    u_hour = APIKeyUsage.objects.filter(timestamp__gte=now - timedelta(hours=1)).aggregate(
        calls=Count("pk"), errors=Count("pk", filter=Q(success=False))
    )
    online_now = (
        TrafficLog.objects.filter(created_at__gte=now - timedelta(minutes=ONLINE_WINDOW_MIN), is_bot=False)
        .order_by()
        .values("ip")
        .distinct()
        .count()
    )
    visitors_today = (
        TrafficLog.objects.filter(created_at__date=today, is_bot=False).order_by().values("ip").distinct().count()
    )

    # ---------- Алерты: только то, что ломает сервис или деньги ----------
    alerts = []
    purposes = _purpose_items()
    purpose_labels = dict(purposes)
    active_purposes = set(
        APIKey.objects.filter(is_active=True).order_by().values_list("purpose", flat=True).distinct()
    )
    for code in CRITICAL_PURPOSES:
        if code not in active_purposes:
            alerts.append({
                "level": "critical",
                "target": "ai",
                "text": f"Нет активного ключа для «{purpose_labels.get(code, code)}»: генерация тестов не работает.",
            })
    if u_hour["calls"] >= MIN_CALLS_FOR_HEALTH:
        err_rate = u_hour["errors"] / u_hour["calls"] * 100.0
        if err_rate >= ERROR_RATE_ALERT:
            alerts.append({
                "level": "critical",
                "target": "ai",
                "text": f"За последний час {u_hour['errors']} из {u_hour['calls']} запросов к AI завершились ошибкой ({err_rate:.0f}%).",
            })
    key_names = {k.id: k.name for k in keys}
    for row in (
        APIKeyUsage.objects.filter(timestamp__date=today, api_key__is_active=True)
        .order_by()
        .values("api_key_id")
        .annotate(calls=Count("pk"), ok=Count("pk", filter=Q(success=True)))
    ):
        rate = _rate(row["ok"], row["calls"])
        if row["calls"] >= MIN_CALLS_FOR_HEALTH and rate is not None and rate < HEALTHY_SUCCESS_RATE:
            alerts.append({
                "level": "warning",
                "target": "ai",
                "text": f"Активный ключ «{key_names.get(row['api_key_id'], row['api_key_id'])}»: успешных запросов сегодня {rate}%.",
            })
    stuck = Payment.objects.filter(
        status="pending",
        created_at__lte=now - timedelta(hours=PENDING_ALERT_HOURS),
        created_at__gte=now - timedelta(days=7),
    ).count()
    if stuck:
        alerts.append({
            "level": "warning",
            "target": "payments",
            "text": f"Платежей в ожидании дольше часа за неделю: {stuck}. Проверьте и смените статус вручную.",
        })

    # ---------- Истекающие подписки ----------
    churn_qs = (
        Subscription.objects.filter(
            status="active",
            end_date__gte=now - timedelta(days=3),
            end_date__lte=now + timedelta(days=7),
        )
        .exclude(plan_name__in=FREE_PLAN_NAMES)
        .order_by("end_date")[:12]
    )
    churn_subs = list(churn_qs)
    churn_users = {u.id_staff: u for u in AuthUser.objects.filter(id_staff__in=[s.staff_id for s in churn_subs])}
    churn = []
    for sub in churn_subs:
        user = churn_users.get(sub.staff_id)
        end_local = timezone.localtime(sub.end_date, MOSCOW_TZ)
        churn.append({
            "staff_id": str(sub.staff_id),
            "username": user.username if user and len(user.username) < 40 else "Гость",
            "email": (user.email if user else None) or "",
            "test_balance": user.test_balance if user else 0,
            "plan": sub.get_human_plan(),
            "sub_status": "active" if sub.end_date > now else "expired",
            "end_date": end_local.strftime("%d.%m.%Y"),
            "days_left": (end_local.date() - today).days,
        })

    # ---------- Лента генераций ----------
    feed_surveys = list(Survey.objects.order_by("-created_at").annotate(attempts_n=Count("attempts"))[:12])
    feed_authors = {
        u.id_staff: u.username for u in AuthUser.objects.filter(id_staff__in=[s.id_staff for s in feed_surveys])
    }
    feed = [
        {
            "title": s.title,
            "author": (feed_authors.get(s.id_staff) or "—") if len(feed_authors.get(s.id_staff) or "") < 40 else "Гость",
            "time": _local_str(s.created_at, "%d.%m %H:%M"),
            "questions": s.questions_count or 0,
            "model": _pulse_model_label(s.model_name),
            "views": s.view_count,
            "attempts": s.attempts_n,
        }
        for s in feed_surveys
    ]

    arpu_cur = rev_cur / payers_cur if payers_cur else 0
    arpu_prev = rev_prev / payers_prev if payers_prev else 0

    return JsonResponse({
        "ok": True,
        "generated_at": _local_str(now, "%H:%M:%S"),
        "period": period.as_dict(),
        "weather": get_cached_weather(),
        "kpi": {
            "revenue": {**_metric(rev_cur, rev_prev, 2), "today": rev_today, "series": _round_list(revenue_total_series)},
            "payments": _metric(pay_cnt_cur, pay_cnt_prev),
            "payers": _metric(payers_cur, payers_prev),
            "arpu": _metric(arpu_cur, arpu_prev, 2),
            "subs": {
                "active": subs_active,
                "new": _metric(subs_new_cur, subs_new_prev),
                "expiring_7d": subs_expiring_7d,
                "series": [int(v) for v in subs_series],
            },
            "users": {
                "new": _metric(users_new_cur, users_new_prev),
                "total": users_total,
                "dau": dau,
                "wau": wau,
                "mau": mau,
                "series": [int(v) for v in reg_series],
            },
            "generations": {**_metric(gen_cur, gen_prev), "total": gen_total, "series": [int(v) for v in gen_series]},
            "attempts": {**_metric(att_cur, att_prev), "series": [int(v) for v in att_series]},
            "score": _metric(score_cur, score_prev, 1),
            "tokens": {
                **_metric(tok_s_cur + tok_f_cur, tok_s_prev + tok_f_prev),
                "survey": tok_s_cur,
                "feedback": tok_f_cur,
            },
            "ai_cost": {**_metric(ai_cost_cur, ai_cost_prev, 4), "calls": ai_calls_cur, "series": _round_list(ai_cost_series, 4)},
        },
        "revenue_by_plan": list(plans.values()),
        "payment_status": payment_status,
        "health": {
            "calls_today": u_today["calls"],
            "success_today": _rate(u_today["ok"], u_today["calls"]),
            "success_yesterday": _rate(u_yday["ok"], u_yday["calls"]),
            "latency_today": int(u_today["ms"] or 0),
            "latency_yesterday": int(u_yday["ms"] or 0),
            "calls_hour": u_hour["calls"],
            "errors_hour": u_hour["errors"],
            "online_now": online_now,
            "online_window_min": ONLINE_WINDOW_MIN,
            "visitors_today": visitors_today,
        },
        "alerts": alerts,
        "funnel": funnel,
        "scores": {"labels": [f"{i * 10}–{i * 10 + 9 if i < 9 else 100}" for i in range(10)], "data": buckets},
        "churn": churn,
        "feed": feed,
    })


# --------------------------------------------------------------------------- #
#  AI: маршрутизация, ключи, расход
# --------------------------------------------------------------------------- #

def _key_state(key, period_stats, last_used, now):
    if key.expires_at and key.expires_at <= now:
        return "expired"
    if not key.is_active:
        return "paused"
    if last_used is None:
        return "never"
    rate = period_stats.get("success_rate")
    if period_stats.get("calls", 0) >= MIN_CALLS_FOR_HEALTH and rate is not None and rate < HEALTHY_SUCCESS_RATE:
        return "degraded"
    return "healthy"


@require_GET
@superuser_json
def admin_dashboard_ai_api(request):
    _ensure_system_key()
    now = timezone.now()
    today = timezone.localdate()
    period = _parse_period(request, today)
    n = len(period.keys)

    keys = list(APIKey.objects.all().order_by("purpose", "-is_active", "name"))
    prices = _key_prices(keys)
    usage_period = APIKeyUsage.objects.filter(timestamp__date__range=period.range)

    agg = dict(
        calls=Count("pk"),
        ok=Count("pk", filter=Q(success=True)),
        tokens=Sum("tokens_used"),
        ms=Avg("response_time_ms"),
    )
    per_period = {r["api_key_id"]: r for r in usage_period.order_by().values("api_key_id").annotate(**agg)}
    per_today = {
        r["api_key_id"]: r
        for r in APIKeyUsage.objects.filter(timestamp__date=today).order_by().values("api_key_id").annotate(**agg)
    }
    last_used = {
        r["api_key_id"]: r["last"]
        for r in APIKeyUsage.objects.order_by().values("api_key_id").annotate(last=Max("timestamp"))
    }

    def _stats(row, price):
        if not row:
            return {"calls": 0, "success_rate": None, "tokens": 0, "cost": 0.0, "avg_ms": 0}
        return {
            "calls": row["calls"],
            "success_rate": _rate(row["ok"], row["calls"]),
            "tokens": int(row["tokens"] or 0),
            "cost": round(_cost(row["tokens"], price), 4),
            "avg_ms": int(row["ms"] or 0),
        }

    keys_payload = []
    for key in keys:
        price = prices.get(key.id, 0)
        p_stats = _stats(per_period.get(key.id), price)
        last = last_used.get(key.id)
        days_since = (today - timezone.localtime(last, MOSCOW_TZ).date()).days if last else None
        keys_payload.append({
            "id": key.id,
            "name": key.name,
            "provider": key.provider or "",
            "purpose": key.purpose or "",
            "model_name": key.model_name or "",
            "base_url": key.base_url or "",
            "masked_key": _mask_key(key.key) if key.key else (".env" if key.is_system else "—"),
            "is_active": key.is_active,
            "is_system": key.is_system,
            "cost_per_1m_tokens": float(key.cost_per_1m_tokens or 0),
            "price_per_1m": price,
            "expires_at": timezone.localtime(key.expires_at, MOSCOW_TZ).date().isoformat() if key.expires_at else None,
            "expires_in_days": (timezone.localtime(key.expires_at, MOSCOW_TZ).date() - today).days
            if key.expires_at
            else None,
            "created_at": _local_str(key.created_at, "%d.%m.%Y"),
            "last_used": _local_str(last),
            "days_since_used": days_since,
            "stale": last is None or (days_since is not None and days_since > STALE_KEY_DAYS),
            "period": p_stats,
            "today": _stats(per_today.get(key.id), price),
            "state": _key_state(key, p_stats, last, now),
        })

    keys_by_id = {k["id"]: k for k in keys_payload}
    routing = []
    for code, label in _purpose_items():
        purpose_keys = [k for k in keys_payload if k["purpose"] == code]
        active = next((k for k in purpose_keys if k["is_active"]), None)
        routing.append({
            "code": code,
            "label": label,
            "active_key_id": active["id"] if active else None,
            "critical": code in CRITICAL_PURPOSES,
            "key_ids": [k["id"] for k in purpose_keys],
        })

    provider_of = {k.id: (k.provider or "unknown") for k in keys}
    providers = sorted({provider_of[k.id] for k in keys})
    tokens_by_provider = {p: [0.0] * n for p in providers}
    calls_by_provider = {p: [0.0] * n for p in providers}
    cost_series = [0.0] * n
    errors_series = [0.0] * n
    for row in _by_day(
        usage_period,
        "timestamp",
        "api_key_id",
        t=Sum("tokens_used"),
        c=Count("pk"),
        e=Count("pk", filter=Q(success=False)),
    ):
        idx = period.slot(row["_day"])
        if idx is None:
            continue
        prov = provider_of.get(row["api_key_id"], "unknown")
        tokens_by_provider.setdefault(prov, [0.0] * n)[idx] += float(row["t"] or 0)
        calls_by_provider.setdefault(prov, [0.0] * n)[idx] += float(row["c"] or 0)
        cost_series[idx] += _cost(row["t"], prices.get(row["api_key_id"], 0))
        errors_series[idx] += float(row["e"] or 0)

    models = defaultdict(lambda: {"calls": 0, "errors": 0, "tokens": 0, "cost": 0.0})
    for row in (
        usage_period.order_by()
        .values("api_key_id", "model_name")
        .annotate(c=Count("pk"), e=Count("pk", filter=Q(success=False)), t=Sum("tokens_used"))
    ):
        name = row["model_name"] or (keys_by_id.get(row["api_key_id"], {}).get("model_name")) or "—"
        bucket = models[name]
        bucket["calls"] += row["c"]
        bucket["errors"] += row["e"]
        bucket["tokens"] += int(row["t"] or 0)
        bucket["cost"] += _cost(row["t"], prices.get(row["api_key_id"], 0))
    models_payload = sorted(
        (
            {
                "model": name,
                "label": _pulse_model_label(name) if name != "—" else "—",
                "calls": v["calls"],
                "tokens": v["tokens"],
                "cost": round(v["cost"], 4),
                "error_rate": _rate(v["errors"], v["calls"]),
            }
            for name, v in models.items()
        ),
        key=lambda m: (-m["cost"], -m["calls"]),
    )

    totals_row = usage_period.aggregate(**agg)
    return JsonResponse({
        "ok": True,
        "generated_at": _local_str(now, "%H:%M:%S"),
        "period": period.as_dict(),
        "purposes": [{"code": c, "label": l} for c, l in _purpose_items()],
        "presets": AI_PROVIDER_PRESETS,
        "routing": routing,
        "keys": keys_payload,
        "series": {
            "providers": [
                {
                    "provider": p,
                    "tokens": [int(v) for v in tokens_by_provider.get(p, [0.0] * n)],
                    "calls": [int(v) for v in calls_by_provider.get(p, [0.0] * n)],
                }
                for p in providers
            ],
            "cost": _round_list(cost_series, 4),
            "errors": [int(v) for v in errors_series],
        },
        "models": models_payload,
        "totals": {
            "keys": len(keys_payload),
            "active_keys": sum(1 for k in keys_payload if k["is_active"]),
            "stale_keys": sum(1 for k in keys_payload if k["stale"] and not k["is_system"]),
            "calls": totals_row["calls"],
            "success_rate": _rate(totals_row["ok"], totals_row["calls"]),
            "tokens": int(totals_row["tokens"] or 0),
            "cost": round(sum(k["period"]["cost"] for k in keys_payload), 4),
            "avg_ms": int(totals_row["ms"] or 0),
        },
    })


# --------------------------------------------------------------------------- #
#  Платежи: фильтры, поиск, серверная пагинация
# --------------------------------------------------------------------------- #

@require_GET
@superuser_json
def admin_dashboard_payments_api(request):
    now = timezone.now()
    today = timezone.localdate()
    status = request.GET.get("status") or ""
    query = (request.GET.get("q") or "").strip()
    scope = request.GET.get("scope") or "all"
    try:
        page_number = max(int(request.GET.get("page") or 1), 1)
    except ValueError:
        page_number = 1

    qs = Payment.objects.select_related("subscription")
    period = None
    if scope == "period":
        period = _parse_period(request, today)
        qs = qs.filter(created_at__date__range=period.range)

    if query:
        cond = Q(order_id__icontains=query) | Q(payment_id__icontains=query)
        user_ids = AuthUser.objects.filter(Q(email__icontains=query) | Q(username__icontains=query)).values("id_staff")
        cond |= Q(staff_id__in=user_ids)
        try:
            cond |= Q(staff_id=uuid.UUID(query))
        except ValueError:
            pass
        qs = qs.filter(cond)

    counts = {s: {"count": 0, "amount": 0.0} for s in PAYMENT_STATUSES}
    total_count = 0
    for row in qs.order_by().values("status").annotate(c=Count("pk"), s=Sum("amount")):
        counts[row["status"]] = {"count": row["c"], "amount": _rub(row["s"])}
        total_count += row["c"]

    if status in PAYMENT_STATUSES:
        qs = qs.filter(status=status)

    paginator = Paginator(qs.order_by("-created_at", "-id"), PAGE_SIZE)
    page = paginator.get_page(page_number)
    rows = list(page.object_list)

    staff_ids = {p.staff_id for p in rows}
    users = {u.id_staff: u for u in AuthUser.objects.filter(id_staff__in=staff_ids)}

    items = []
    for p in rows:
        user = users.get(p.staff_id)
        sub = p.subscription
        sub_active = bool(sub and sub.status == "active" and sub.end_date and sub.end_date > now)
        items.append({
            "id": p.id,
            "payment_id": p.payment_id,
            "order_id": p.order_id,
            "amount": _rub(p.amount),
            "status": p.status,
            "created_at": _local_str(p.created_at),
            "plan_label": _pulse_plan_label(sub.plan_name if sub else ""),
            "plan_raw": sub.plan_name if sub else "",
            "billing_cycle": sub.billing_cycle if sub else "",
            "staff_id": str(p.staff_id),
            "username": (user.username if len(user.username) < 40 else "Гость") if user else "—",
            "email": (user.email if user else None) or "",
            "test_balance": user.test_balance if user else 0,
            "user_exists": user is not None,
            "sub_plan": sub.get_human_plan() if sub else "",
            "sub_status": "active" if sub_active else "inactive",
            "sub_end": _local_str(sub.end_date, "%d.%m.%Y") if sub else None,
        })

    return JsonResponse({
        "ok": True,
        "items": items,
        "counts": counts,
        "total": total_count,
        "page": page.number,
        "pages": paginator.num_pages,
        "page_size": PAGE_SIZE,
        "filtered_total": paginator.count,
        "period": period.as_dict() if period else None,
    })


def get_cached_weather():
    weather = cache.get("admin_moscow_weather")
    if weather:
        return weather
    try:
        url = "https://wttr.in/Moscow?format=%c+%t,+%C&lang=ru"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            weather = resp.read().decode("utf-8").strip()
            cache.set("admin_moscow_weather", weather, 900)
            return weather
    except Exception:
        return None
