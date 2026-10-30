"""
Ситуационный центр каталога тестов (/ops/surveys/).

Кладётся рядом с views.py:  askify_service/admin_surveys_views.py
Заменяет старые admin_surveys_ops_view / api_admin_search_surveys /
api_admin_survey_details / api_admin_delete_survey — их из views.py удалить.

Все ручки:
    GET  /ops/surveys/                                  страница
    GET  /api/admin/surveys/overview/?range=30D         KPI, динамика, срезы, топы
    GET  /api/admin/surveys/catalog/?q=&sort=&page=     каталог с фильтрами
    GET  /api/admin/surveys/export.csv?...              тот же каталог в CSV
    GET  /api/admin/surveys/details/<uuid>/?range=      досье теста
    GET  /api/admin/surveys/details/<uuid>/attempts/    прохождения постранично
    POST /api/admin/surveys/visibility/                 скрыть / вернуть (мягкое удаление)
    POST /api/admin/surveys/flags/                      verified / marketplace / private / show_answers
    POST /api/admin/surveys/delete/                     удалить из БД насовсем

ВНИМАНИЕ про Survey.is_visible: в модели это флаг МЯГКОГО УДАЛЕНИЯ
(True = автор удалил). Наружу отдаём нормальное поле `deleted`.
"""
import csv
import json
import logging
import uuid
from bisect import bisect_right
from collections import Counter
from datetime import date, datetime, time, timedelta
from functools import wraps
from statistics import median
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.db import transaction
from django.db.models import (
    Avg, Case, Count, Exists, ExpressionWrapper, F, FloatField, Func, IntegerField,
    Max, Min, OuterRef, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce, ExtractHour, TruncDate
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AuthUser, FeedbackFromAI, Survey, SurveyUniqueView, TestAttempt, UserAnswers,
)

log = logging.getLogger("askify_app")
MSK = ZoneInfo("Europe/Moscow")

RANGE_DAYS = {"7D": 7, "30D": 30, "90D": 90, "1Y": 365}
PER_PAGE_CHOICES = (25, 50, 100)
EXPORT_LIMIT = 20000
QUESTION_ANALYSIS_LIMIT = 3000  # последних попыток для разбора по вопросам

_MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря"]


# =====================================================================
#  Доступ
# =====================================================================

def admin_api(view):
    """Только суперюзер. Для API — JSON 403, а не редирект на логин (фронт ждёт JSON)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        u = request.user
        if not (u.is_authenticated and u.is_active and u.is_superuser):
            return JsonResponse({"ok": False, "error": "Нет доступа"}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


def admin_page(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        u = request.user
        if not (u.is_authenticated and u.is_active and u.is_superuser):
            from django.shortcuts import redirect
            return redirect("login")
        return view(request, *args, **kwargs)
    return wrapper


# =====================================================================
#  Периоды и корзины
# =====================================================================

def _today():
    return timezone.localdate(timezone=MSK)


def _dt(d):
    """Начало суток по Москве (aware)."""
    return datetime.combine(d, time.min, tzinfo=MSK)


def _fmt_day(d):
    return d.strftime("%d.%m")


def _title_day(d):
    return f"{d.day} {_MONTHS_GEN[d.month - 1]} {d.year}"


def _build_buckets(start, end, kind):
    out = []
    if kind == "day":
        d = start
        while d <= end:
            out.append({"start": d, "end": d, "label": _fmt_day(d), "title": _title_day(d)})
            d += timedelta(days=1)
    elif kind == "week":
        # недели считаем от конца: последняя корзина = последние 7 дней
        e = end
        tmp = []
        while e >= start:
            s = max(start, e - timedelta(days=6))
            tmp.append({"start": s, "end": e, "label": _fmt_day(s),
                        "title": f"{_title_day(s)} — {_title_day(e)}"})
            e = s - timedelta(days=1)
        out = list(reversed(tmp))
    else:  # month
        y, m = start.year, start.month
        first = True
        while (y, m) <= (end.year, end.month):
            ms = date(y, m, 1)
            nm = date(y + (m == 12), (m % 12) + 1, 1)
            me = nm - timedelta(days=1)
            label = _MONTHS_SHORT[m - 1] + (f" ’{str(y)[2:]}" if first or m == 1 else "")
            out.append({"start": max(ms, start), "end": min(me, end), "label": label,
                        "title": f"{_MONTHS_SHORT[m - 1]} {y}"})
            first = False
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _bucket_kind(days):
    if days <= 62:
        return "day"
    if days <= 400:
        return "week"
    return "month"


def make_period(start, end):
    days = (end - start).days + 1
    kind = _bucket_kind(days)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    buckets = _build_buckets(start, end, kind)
    return {
        "start": start, "end": end, "days": days, "kind": kind,
        "prev_start": prev_start, "prev_end": prev_end,
        "start_dt": _dt(start), "end_dt": _dt(end + timedelta(days=1)),
        "prev_start_dt": _dt(prev_start), "prev_end_dt": _dt(start),
        "buckets": buckets,
    }


def resolve_period(request):
    today = _today()
    rng = (request.GET.get("range") or "30D").upper()
    start = end = None
    if rng == "CUSTOM":
        s = parse_date(request.GET.get("start_date") or "")
        e = parse_date(request.GET.get("end_date") or "")
        if s and e:
            start, end = min(s, e), min(max(s, e), today)
        else:
            rng = "30D"
    if rng == "ALL":
        first = Survey.objects.aggregate(m=Min("created_at"))["m"]
        start = timezone.localtime(first, MSK).date() if first else today - timedelta(days=29)
        end = today
    elif rng in RANGE_DAYS:
        start, end = today - timedelta(days=RANGE_DAYS[rng] - 1), today
    elif start is None:
        rng = "30D"
        start, end = today - timedelta(days=29), today
    p = make_period(start, end)
    p["range"] = rng
    return p


def period_json(p):
    return {
        "range": p.get("range"),
        "start": p["start"].isoformat(), "end": p["end"].isoformat(),
        "prev_start": p["prev_start"].isoformat(), "prev_end": p["prev_end"].isoformat(),
        "days": p["days"], "bucket": p["kind"],
        "labels": [b["label"] for b in p["buckets"]],
        "titles": [b["title"] for b in p["buckets"]],
    }


def bucketize(day_map, p):
    bs = p["buckets"]
    starts = [b["start"] for b in bs]
    out = [0] * len(bs)
    for d, v in day_map.items():
        if d is None:
            continue
        i = bisect_right(starts, d) - 1
        if 0 <= i < len(bs) and d <= bs[i]["end"]:
            out[i] += v or 0
    return out


def day_map(qs, field, start_dt, end_dt, agg=None):
    """{дата по МСК: значение}. По умолчанию Count('pk')."""
    rows = (
        qs.filter(**{f"{field}__gte": start_dt, f"{field}__lt": end_dt})
        .annotate(_d=TruncDate(field, tzinfo=MSK))
        .values("_d")
        .annotate(_v=agg or Count("pk"))
    )
    return {r["_d"]: r["_v"] for r in rows}


def pct_delta(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def pp_delta(cur, prev):
    """Разница в процентных пунктах (для долей и баллов)."""
    if cur is None or prev is None:
        return None
    return round(cur - prev, 1)


# =====================================================================
#  Общие выражения
# =====================================================================

# NULLIF: total_questions=0 (старые/битые попытки) -> NULL вместо "division by zero".
# Avg() и Q(_p__gte=...) такие строки молча пропускают.
PCT_EXPR = ExpressionWrapper(
    F("score") * 100.0 / Func(F("total_questions"), Value(0), function="NULLIF", output_field=IntegerField()),
    output_field=FloatField(),
)


def _registered_author_q():
    """Автор зарегистрирован = у AuthUser с этим id_staff есть email и он не архивный."""
    return Exists(
        AuthUser.objects.filter(id_staff=OuterRef("id_staff"))
        .exclude(email__isnull=True)
        .exclude(email="")
        .exclude(email__icontains="letychka-archive")
    )


def authors_map(staff_ids):
    ids = {s for s in staff_ids if s}
    if not ids:
        return {}
    out = {}
    for u in AuthUser.objects.filter(id_staff__in=ids).only("id", "id_staff", "username", "email"):
        guest = not u.email
        name = u.username or "—"
        if guest:
            name = "Гость"
        elif len(name) > 32:
            name = name[:30] + "…"
        out[u.id_staff] = {"name": name, "email": u.email or "", "is_guest": guest,
                           "user_id": u.id, "id_staff": str(u.id_staff)}
    return out


def _author(amap, sid):
    return amap.get(sid) or {"name": "Удалён", "email": "", "is_guest": True,
                             "user_id": None, "id_staff": str(sid) if sid else ""}


def _source_of(s):
    gp = s.generation_params or {}
    if gp.get("source_file"):
        return "file"
    if s.source_text:
        return "text"
    return "unknown"


SOURCE_LABELS = {"file": "Файл", "text": "Текст", "unknown": "Нет данных"}
DIFFICULTY_LABELS = {"easy": "Лёгкая", "medium": "Средняя", "hard": "Сложная"}


def _msk(dt, fmt="%d.%m.%Y %H:%M"):
    return timezone.localtime(dt, MSK).strftime(fmt) if dt else None


def _iso(dt):
    return timezone.localtime(dt, MSK).isoformat() if dt else None


# =====================================================================
#  Страница
# =====================================================================

@admin_page
def admin_surveys_ops_view(request):
    return render(request, "admin/admin_surveys_ops.html", {
        "page_title": "Тесты | Ситуационный центр Летучки",
    })


# =====================================================================
#  Обзор: KPI, динамика, срезы, топы
# =====================================================================

@admin_api
@require_GET
def api_admin_surveys_overview(request):
    p = resolve_period(request)
    cache_key = f"surveys_ops:overview:{p['start']}:{p['end']}"
    if request.GET.get("fresh") != "1":
        cached = cache.get(cache_key)
        if cached:
            return JsonResponse(cached)

    s_dt, e_dt = p["start_dt"], p["end_dt"]
    ps_dt, pe_dt = p["prev_start_dt"], p["prev_end_dt"]

    surveys = Survey.objects.all()
    alive = surveys.filter(is_visible=False)
    attempts = TestAttempt.objects.all()
    views = SurveyUniqueView.objects.all()

    # ---- Ряды по корзинам: текущий и прошлый период ----
    def series(qs, field):
        cur = bucketize(day_map(qs, field, s_dt, e_dt), p)
        prev_p = make_period(p["prev_start"], p["prev_end"])
        prev = bucketize(day_map(qs, field, ps_dt, pe_dt), prev_p)
        # прошлый период может разбиться на другое число корзин — подгоняем по длине
        prev = (prev + [0] * len(cur))[:len(cur)]
        return cur, prev

    created_s, created_prev_s = series(surveys, "created_at")
    views_s, views_prev_s = series(views, "timestamp")
    att_s, att_prev_s = series(attempts, "created_at")

    created_cur, created_prev = sum(created_s), surveys.filter(created_at__gte=ps_dt, created_at__lt=pe_dt).count()
    views_cur, views_prev = sum(views_s), views.filter(timestamp__gte=ps_dt, timestamp__lt=pe_dt).count()
    att_cur, att_prev = sum(att_s), attempts.filter(created_at__gte=ps_dt, created_at__lt=pe_dt).count()

    conv_cur = round(att_cur / views_cur * 100, 1) if views_cur else None
    conv_prev = round(att_prev / views_prev * 100, 1) if views_prev else None

    def avg_pct(qs):
        v = qs.exclude(total_questions=0).aggregate(a=Avg(PCT_EXPR))["a"]
        return round(v, 1) if v is not None else None

    score_cur = avg_pct(attempts.filter(created_at__gte=s_dt, created_at__lt=e_dt))
    score_prev = avg_pct(attempts.filter(created_at__gte=ps_dt, created_at__lt=pe_dt))

    in_period = surveys.filter(created_at__gte=s_dt, created_at__lt=e_dt)
    in_prev = surveys.filter(created_at__gte=ps_dt, created_at__lt=pe_dt)
    authors_cur = in_period.values("id_staff").distinct().count()
    authors_prev = in_prev.values("id_staff").distinct().count()

    agg = in_period.annotate(
        _has_att=Exists(TestAttempt.objects.filter(survey=OuterRef("pk")))
    ).aggregate(
        avg_q=Avg("questions_count"),
        deleted=Count("pk", filter=Q(is_visible=True)),
        dead=Count("pk", filter=Q(is_visible=False, view_count=0)),
        with_att=Count("pk", filter=Q(_has_att=True)),
    )
    totals = surveys.aggregate(
        all=Count("pk"),
        alive=Count("pk", filter=Q(is_visible=False)),
        views=Coalesce(Sum("view_count"), 0),
    )
    totals["attempts"] = attempts.count()

    # Ряд «всего тестов в базе» на конец каждой корзины (накопительно)
    base_before = surveys.filter(created_at__lt=s_dt).count()
    cum, acc = [], base_before
    for v in created_s:
        acc += v
        cum.append(acc)

    # ---- Срезы по тестам, созданным в периоде ----
    models = list(
        in_period.values("model_name").annotate(c=Count("pk")).order_by("-c")[:8]
    )
    model_items = [{"key": m["model_name"] or "", "label": m["model_name"] or "Не указана", "value": m["c"]} for m in models]

    diff_rows = in_period.values("generation_params__difficulty").annotate(c=Count("pk")).order_by("-c")
    difficulty = [{"key": r["generation_params__difficulty"] or "",
                   "label": DIFFICULTY_LABELS.get(r["generation_params__difficulty"], "Нет данных"),
                   "value": r["c"]} for r in diff_rows]

    src = in_period.aggregate(
        file=Count("pk", filter=Q(generation_params__has_key="source_file")),
        text=Count("pk", filter=~Q(generation_params__has_key="source_file") & Q(source_text__isnull=False) & ~Q(source_text="")),
    )
    src_unknown = created_cur - src["file"] - src["text"]
    source = [{"key": "file", "label": "Файл", "value": src["file"]},
              {"key": "text", "label": "Текст", "value": src["text"]},
              {"key": "unknown", "label": "Нет данных", "value": max(src_unknown, 0)}]

    reg = in_period.annotate(_reg=_registered_author_q()).aggregate(
        registered=Count("pk", filter=Q(_reg=True)), guest=Count("pk", filter=Q(_reg=False)))
    author_type = [{"key": "registered", "label": "Зарегистрированные", "value": reg["registered"]},
                   {"key": "guest", "label": "Гости", "value": reg["guest"]}]

    qsize_bins = [("1–5", 1, 5), ("6–10", 6, 10), ("11–15", 11, 15), ("16–20", 16, 20), ("21–30", 21, 30), ("30+", 31, 10_000)]
    qsize_agg = in_period.aggregate(**{f"b{i}": Count("pk", filter=Q(questions_count__gte=a, questions_count__lte=b))
                                       for i, (_, a, b) in enumerate(qsize_bins)})
    qsize = {"labels": [l for l, _, _ in qsize_bins], "data": [qsize_agg[f"b{i}"] for i in range(len(qsize_bins))]}

    att_period = attempts.filter(created_at__gte=s_dt, created_at__lt=e_dt).exclude(total_questions=0)
    score_agg = att_period.annotate(_p=PCT_EXPR).aggregate(**{
        f"s{i}": Count("pk", filter=Q(_p__gte=i * 10, _p__lt=(i + 1) * 10 if i < 9 else 100.01)) for i in range(10)
    })
    scores = {"labels": [f"{i * 10}–{i * 10 + 10}" for i in range(10)], "data": [score_agg[f"s{i}"] for i in range(10)]}

    def hours(qs, field):
        rows = (qs.filter(**{f"{field}__gte": s_dt, f"{field}__lt": e_dt})
                .annotate(_h=ExtractHour(field, tzinfo=MSK)).values("_h").annotate(c=Count("pk")))
        m = {r["_h"]: r["c"] for r in rows}
        return [m.get(h, 0) for h in range(24)]

    hours_payload = {"labels": [f"{h:02d}" for h in range(24)],
                     "created": hours(surveys, "created_at"),
                     "attempts": hours(attempts, "created_at")}

    # ---- Топы ----
    def top_rows(qs_rows, metric_key, sub_fn):
        ids = [r["survey_id"] for r in qs_rows]
        objs = {s.pk: s for s in Survey.objects.filter(pk__in=ids).only(
            "pk", "survey_id", "title", "id_staff", "created_at", "view_count", "questions_count", "is_visible")}
        amap = authors_map([o.id_staff for o in objs.values()])
        out = []
        for r in qs_rows:
            s = objs.get(r["survey_id"])
            if not s:
                continue
            out.append({
                "survey_id": str(s.survey_id), "title": s.title,
                "author": _author(amap, s.id_staff)["name"],
                "created": _msk(s.created_at, "%d.%m.%Y"),
                "metric": r[metric_key], "sub": sub_fn(r, s), "deleted": s.is_visible,
            })
        return out

    trending = top_rows(
        list(views.filter(timestamp__gte=s_dt, timestamp__lt=e_dt).values("survey_id")
             .annotate(c=Count("pk")).order_by("-c")[:12]),
        "c", lambda r, s: f"всего {s.view_count}")
    top_attempts = top_rows(
        list(attempts.filter(created_at__gte=s_dt, created_at__lt=e_dt).values("survey_id")
             .annotate(c=Count("pk"), a=Avg(PCT_EXPR)).order_by("-c")[:12]),
        "c", lambda r, s: f"ср. балл {round(r['a'] or 0)}%")
    hardest = top_rows(
        list(att_period.values("survey_id").annotate(c=Count("pk"), a=Avg(PCT_EXPR))
             .filter(c__gte=5).order_by("a")[:12]),
        "a", lambda r, s: f"{r['c']} прохождений")
    for h in hardest:
        h["metric"] = round(h["metric"] or 0, 1)
    fresh_hits = top_rows(
        [{"survey_id": s["pk"], "v": s["view_count"]} for s in
         in_period.filter(is_visible=False, view_count__gt=0).order_by("-view_count").values("pk", "view_count")[:12]],
        "v", lambda r, s: f"создан {_msk(s.created_at, '%d.%m')}")

    payload = {
        "ok": True,
        "generated_at": timezone.localtime(timezone.now(), MSK).strftime("%H:%M"),
        "period": period_json(p),
        "kpi": {
            "created": {"value": created_cur, "prev": created_prev, "delta": pct_delta(created_cur, created_prev),
                        "series": created_s, "prev_series": created_prev_s},
            "views": {"value": views_cur, "prev": views_prev, "delta": pct_delta(views_cur, views_prev),
                      "series": views_s, "prev_series": views_prev_s},
            "attempts": {"value": att_cur, "prev": att_prev, "delta": pct_delta(att_cur, att_prev),
                         "series": att_s, "prev_series": att_prev_s},
            "conversion": {"value": conv_cur, "prev": conv_prev, "delta": pp_delta(conv_cur, conv_prev)},
            "score": {"value": score_cur, "prev": score_prev, "delta": pp_delta(score_cur, score_prev)},
            "authors": {"value": authors_cur, "prev": authors_prev, "delta": pct_delta(authors_cur, authors_prev)},
            "avg_questions": round(agg["avg_q"] or 0, 1),
            "dead": {"value": agg["dead"], "share": round(agg["dead"] / created_cur * 100, 1) if created_cur else None},
            "deleted": {"value": agg["deleted"], "share": round(agg["deleted"] / created_cur * 100, 1) if created_cur else None},
            "with_attempts": {"value": agg["with_att"], "share": round(agg["with_att"] / created_cur * 100, 1) if created_cur else None},
            "per_author": round(created_cur / authors_cur, 1) if authors_cur else None,
        },
        "totals": {**totals, "cumulative": cum},
        "breakdowns": {
            "models": model_items, "difficulty": difficulty, "source": source,
            "author_type": author_type, "qsize": qsize, "scores": scores, "hours": hours_payload,
        },
        "tops": {"trending": trending, "attempts": top_attempts, "hardest": hardest, "fresh": fresh_hits},
    }
    cache.set(cache_key, payload, 120)
    return JsonResponse(payload)


# =====================================================================
#  Каталог
# =====================================================================

SORTS = {
    "-created": ("-created_at",), "created": ("created_at",),
    "-updated": ("-updated_at",),
    "-views": ("-view_count", "-created_at"), "views": ("view_count", "-created_at"),
    "-views_period": ("-_views_period", "-view_count"),
    "-attempts": ("-_attempts", "-created_at"), "attempts": ("_attempts", "-created_at"),
    "-attempts_period": ("-_attempts_period", "-_attempts"),
    "-score": ("-_score", "-_attempts"), "score": ("_score", "-_attempts"),
    "-conversion": ("-_conversion", "-_attempts"),
    "-questions": ("-questions_count", "-created_at"), "questions": ("questions_count", "-created_at"),
    "-last_attempt": ("-_last_attempt", "-created_at"),
    "title": ("title",),
}


def _int(v, default=None, lo=None, hi=None):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def catalog_queryset(request, p):
    """Отфильтрованный queryset БЕЗ тяжёлых аннотаций + описание применённых фильтров."""
    g = request.GET
    qs = Survey.objects.all()

    status = g.get("status", "active")
    if status == "active":
        qs = qs.filter(is_visible=False)
    elif status == "deleted":
        qs = qs.filter(is_visible=True)

    # Дата создания: свой фильтр, независимый от периода метрик
    created = g.get("created", "all")
    today = _today()
    c_from = c_to = None
    if created == "custom":
        c_from, c_to = parse_date(g.get("cfrom") or ""), parse_date(g.get("cto") or "")
    elif created == "today":
        c_from = today
    elif created == "yesterday":
        c_from = c_to = today - timedelta(days=1)
    elif created in ("7d", "30d", "90d", "365d"):
        c_from = today - timedelta(days=int(created[:-1]) - 1)
    elif created == "period":
        c_from, c_to = p["start"], p["end"]
    if c_from:
        qs = qs.filter(created_at__gte=_dt(c_from))
    if c_to:
        qs = qs.filter(created_at__lt=_dt(c_to + timedelta(days=1)))

    q = (g.get("q") or "").strip()
    if q:
        try:
            u = uuid.UUID(q)
            qs = qs.filter(Q(survey_id=u) | Q(id_staff=u))
        except ValueError:
            if "@" in q:
                qs = qs.filter(id_staff__in=AuthUser.objects.filter(email__icontains=q).values("id_staff"))
            else:
                qs = qs.filter(
                    Q(title__icontains=q)
                    | Q(description__icontains=q)
                    | Q(id_staff__in=AuthUser.objects.filter(username__icontains=q).values("id_staff"))
                )

    author = g.get("author")
    if author:
        try:
            qs = qs.filter(id_staff=uuid.UUID(author))
        except ValueError:
            pass

    model = g.get("model")
    if model == "__none__":
        qs = qs.filter(Q(model_name__isnull=True) | Q(model_name=""))
    elif model:
        qs = qs.filter(model_name=model)

    diff = g.get("difficulty")
    if diff == "__none__":
        qs = qs.filter(~Q(generation_params__has_key="difficulty"))
    elif diff:
        qs = qs.filter(generation_params__difficulty=diff)

    source = g.get("source")
    if source == "file":
        qs = qs.filter(generation_params__has_key="source_file")
    elif source == "text":
        qs = qs.exclude(generation_params__has_key="source_file").exclude(source_text__isnull=True).exclude(source_text="")
    elif source == "unknown":
        qs = qs.exclude(generation_params__has_key="source_file").filter(Q(source_text__isnull=True) | Q(source_text=""))

    atype = g.get("author_type")
    if atype in ("registered", "guest"):
        qs = qs.annotate(_reg=_registered_author_q()).filter(_reg=(atype == "registered"))

    has_att = g.get("attempts")
    if has_att in ("yes", "no"):
        ex = Exists(TestAttempt.objects.filter(survey=OuterRef("pk")))
        qs = qs.filter(ex) if has_att == "yes" else qs.filter(~ex)

    views_f = g.get("views")
    if views_f == "zero":
        qs = qs.filter(view_count=0)
    elif views_f == "some":
        qs = qs.filter(view_count__gt=0)
    elif views_f == "100":
        qs = qs.filter(view_count__gte=100)

    qmin, qmax = _int(g.get("qmin")), _int(g.get("qmax"))
    if qmin is not None:
        qs = qs.filter(questions_count__gte=qmin)
    if qmax is not None:
        qs = qs.filter(questions_count__lte=qmax)

    for flag in ("is_in_marketplace", "is_verified", "is_private"):
        v = g.get(flag)
        if v in ("1", "0"):
            qs = qs.filter(**{flag: v == "1"})

    return qs


def annotate_metrics(qs, p):
    att = TestAttempt.objects.filter(survey=OuterRef("pk"))
    att_cnt = att.values("survey").annotate(c=Count("pk")).values("c")[:1]
    att_cnt_p = (att.filter(created_at__gte=p["start_dt"], created_at__lt=p["end_dt"])
                 .values("survey").annotate(c=Count("pk")).values("c")[:1])
    att_score = (att.exclude(total_questions=0).values("survey")
                 .annotate(a=Avg(PCT_EXPR)).values("a")[:1])
    att_last = att.order_by("-created_at").values("created_at")[:1]
    views_p = (SurveyUniqueView.objects.filter(survey=OuterRef("pk"), timestamp__gte=p["start_dt"],
                                               timestamp__lt=p["end_dt"])
               .values("survey").annotate(c=Count("pk")).values("c")[:1])
    qs = qs.annotate(
        _attempts=Coalesce(Subquery(att_cnt, output_field=IntegerField()), Value(0)),
        _attempts_period=Coalesce(Subquery(att_cnt_p, output_field=IntegerField()), Value(0)),
        _views_period=Coalesce(Subquery(views_p, output_field=IntegerField()), Value(0)),
        _score=Subquery(att_score, output_field=FloatField()),
        _last_attempt=Subquery(att_last),
    ).annotate(
        _conversion=Case(
            When(view_count__gt=0, then=ExpressionWrapper(F("_attempts") * 100.0 / F("view_count"), output_field=FloatField())),
            default=Value(None), output_field=FloatField(),
        )
    )
    return qs


def _ordered(qs, sort):
    keys = SORTS.get(sort) or SORTS["-created"]
    order = []
    for k in keys:
        desc = k.startswith("-")
        name = k.lstrip("-")
        expr = F(name).desc(nulls_last=True) if desc else F(name).asc(nulls_last=True)
        order.append(expr)
    order.append(F("pk").desc())
    return qs.order_by(*order)


def serialize_row(s, amap):
    a = _author(amap, s.id_staff)
    gp = s.generation_params or {}
    return {
        "survey_id": str(s.survey_id),
        "title": s.title,
        "description": s.description or "",
        "author": a,
        "created_at": _iso(s.created_at),
        "created": _msk(s.created_at),
        "updated": _msk(s.updated_at),
        "questions": s.questions_count,
        "views": s.view_count,
        "views_period": s._views_period,
        "attempts": s._attempts,
        "attempts_period": s._attempts_period,
        "score": round(s._score, 1) if s._score is not None else None,
        "conversion": round(s._conversion, 1) if s._conversion is not None else None,
        "last_attempt": _msk(s._last_attempt),
        "model": s.model_name or "",
        "difficulty": gp.get("difficulty") or "",
        "source": _source_of(s),
        "source_file": gp.get("source_file") or "",
        "deleted": s.is_visible,
        "is_private": s.is_private,
        "is_verified": s.is_verified,
        "is_in_marketplace": s.is_in_marketplace,
        "show_answers": s.show_answers,
    }


LIST_FIELDS = ("pk", "survey_id", "title", "description", "id_staff", "created_at", "updated_at",
               "questions_count", "view_count", "model_name", "generation_params", "source_text",
               "is_visible", "is_private", "is_verified", "is_in_marketplace", "show_answers")


def _facets():
    data = cache.get("surveys_ops:facets")
    if data:
        return data
    models = list(Survey.objects.exclude(model_name__isnull=True).exclude(model_name="")
                  .values("model_name").annotate(c=Count("pk")).order_by("-c")[:40])
    status = Survey.objects.aggregate(active=Count("pk", filter=Q(is_visible=False)),
                                      deleted=Count("pk", filter=Q(is_visible=True)), all=Count("pk"))
    data = {"models": [{"value": m["model_name"], "count": m["c"]} for m in models], "status": status}
    cache.set("surveys_ops:facets", data, 300)
    return data


@admin_api
@require_GET
def api_admin_surveys_catalog(request):
    p = resolve_period(request)
    qs = catalog_queryset(request, p)

    per = _int(request.GET.get("per"), 50)
    per = per if per in PER_PAGE_CHOICES else 50
    total = qs.count()
    pages = max(1, -(-total // per))
    page = _int(request.GET.get("page"), 1, 1, pages)

    rows = list(
        _ordered(annotate_metrics(qs.only(*LIST_FIELDS), p), request.GET.get("sort", "-created"))
        [(page - 1) * per: page * per]
    )
    amap = authors_map([s.id_staff for s in rows])

    # сводка по выдаче — чтобы видеть «вес» среза, а не только список
    summary = qs.aggregate(views=Coalesce(Sum("view_count"), 0), questions=Avg("questions_count"))
    summary["attempts"] = TestAttempt.objects.filter(survey__in=qs.values("pk")).count() if total <= 50000 else None
    summary["questions"] = round(summary["questions"] or 0, 1)

    return JsonResponse({
        "ok": True,
        "items": [serialize_row(s, amap) for s in rows],
        "total": total, "page": page, "pages": pages, "per": per,
        "summary": summary,
        "facets": _facets(),
        "period": {"start": p["start"].isoformat(), "end": p["end"].isoformat()},
    })


@admin_api
@require_GET
def api_admin_surveys_export(request):
    p = resolve_period(request)
    qs = _ordered(annotate_metrics(catalog_queryset(request, p).only(*LIST_FIELDS), p),
                  request.GET.get("sort", "-created"))[:EXPORT_LIMIT]

    class Echo:
        def write(self, v):
            return v

    def rows():
        w = csv.writer(Echo(), delimiter=";")
        yield "\ufeff"  # BOM, чтобы Excel открыл кириллицу
        yield w.writerow(["UUID", "Название", "Автор", "Email", "Гость", "Создан", "Обновлён", "Вопросов",
                          "Просмотры всего", f"Просмотры {p['start']}..{p['end']}", "Прохождений всего",
                          "Прохождений за период", "Средний балл %", "Конверсия %", "Модель", "Сложность",
                          "Источник", "Удалён", "Маркетплейс", "Проверен", "Ссылка"])
        buf = []
        for s in qs.iterator(chunk_size=500):
            buf.append(s)
            if len(buf) == 500:
                yield from _flush(buf, w)
                buf = []
        if buf:
            yield from _flush(buf, w)

    def _flush(buf, w):
        amap = authors_map([s.id_staff for s in buf])
        for s in buf:
            r = serialize_row(s, amap)
            yield w.writerow([
                r["survey_id"], r["title"], r["author"]["name"], r["author"]["email"],
                "да" if r["author"]["is_guest"] else "нет", r["created"], r["updated"], r["questions"],
                r["views"], r["views_period"], r["attempts"], r["attempts_period"],
                r["score"] if r["score"] is not None else "", r["conversion"] if r["conversion"] is not None else "",
                r["model"], DIFFICULTY_LABELS.get(r["difficulty"], ""), SOURCE_LABELS[r["source"]],
                "да" if r["deleted"] else "", "да" if r["is_in_marketplace"] else "",
                "да" if r["is_verified"] else "", request.build_absolute_uri(f"/c/{r['survey_id']}/"),
            ])

    resp = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="letychka_tests_{_today():%Y%m%d}.csv"'
    log.info(f"ADMIN SURVEYS EXPORT by {request.user.username}: {request.GET.urlencode()}")
    return resp


# =====================================================================
#  Досье теста
# =====================================================================

def _norm_answers(v):
    if v is None:
        return frozenset()
    if isinstance(v, (list, tuple, set)):
        return frozenset(str(x).strip() for x in v)
    return frozenset([str(v).strip()])


def question_breakdown(survey, attempts_qs):
    """
    Разбор по вопросам: доля верных, самый популярный неверный ответ.
    answers_json хранит {текст вопроса: ответ}; сопоставляем по тексту.
    Сравнение — по множеству, поэтому корректно и для multiple
    (в submit_answers это сравнение сейчас сломано — см. аудит).
    """
    try:
        questions = survey.get_normalized_questions()
    except Exception:
        questions = []
    idx = {q["question"]: i for i, q in enumerate(questions)}
    stats = [{"total": 0, "correct": 0, "wrong": Counter()} for _ in questions]
    analysed = 0
    for raw in attempts_qs.order_by("-created_at").values_list("answers_json", flat=True)[:QUESTION_ANALYSIS_LIMIT]:
        try:
            ans = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(ans, dict):
            continue
        analysed += 1
        for q_text, given in ans.items():
            i = idx.get(q_text)
            if i is None:
                continue
            st = stats[i]
            st["total"] += 1
            if _norm_answers(given) == frozenset(questions[i]["correct_answers"]):
                st["correct"] += 1
            else:
                st["wrong"][", ".join(sorted(_norm_answers(given))) or "—"] += 1
    out = []
    for i, q in enumerate(questions):
        st = stats[i]
        top_wrong = st["wrong"].most_common(1)
        out.append({
            "index": i + 1,
            "question": q["question"],
            "type": q["type"],
            "options": q["options"],
            "correct": q["correct_answers"],
            "answered": st["total"],
            "rate": round(st["correct"] / st["total"] * 100, 1) if st["total"] else None,
            "top_wrong": {"answer": top_wrong[0][0], "count": top_wrong[0][1]} if top_wrong else None,
        })
    return out, analysed


def _attempt_row(a):
    pct = round(a.score * 100 / a.total_questions) if a.total_questions else 0
    return {"id": a.id, "name": a.student_name or "Аноним", "score": a.score, "total": a.total_questions,
            "pct": pct, "date": _msk(a.created_at)}


@admin_api
@require_GET
def api_admin_survey_details(request, survey_id):
    try:
        sid = uuid.UUID(str(survey_id))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Невалидный UUID теста"}, status=400)
    s = Survey.objects.filter(survey_id=sid).first()
    if not s:
        return JsonResponse({"ok": False, "error": "Тест не найден"}, status=404)

    gp = resolve_period(request)
    created_d = timezone.localtime(s.created_at, MSK).date()
    # график: с начала периода, но не раньше создания теста
    p = make_period(max(gp["start"], created_d), max(gp["end"], created_d))

    attempts = TestAttempt.objects.filter(survey=s)
    views = SurveyUniqueView.objects.filter(survey=s)

    att_total = attempts.count()
    att_period = attempts.filter(created_at__gte=gp["start_dt"], created_at__lt=gp["end_dt"]).count()
    views_period = views.filter(timestamp__gte=gp["start_dt"], timestamp__lt=gp["end_dt"]).count()
    views_logged = views.count()

    pcts = [round(sc * 100 / tq, 1) for sc, tq in attempts.exclude(total_questions=0).values_list("score", "total_questions")[:20000]]
    agg = attempts.aggregate(students=Count("student_name", distinct=True), last=Max("created_at"), first=Min("created_at"))
    last_view = views.aggregate(m=Max("timestamp"))["m"]

    def share(pred):
        return round(sum(1 for x in pcts if pred(x)) / len(pcts) * 100, 1) if pcts else None

    att_s = bucketize(day_map(attempts, "created_at", p["start_dt"], p["end_dt"]), p)
    views_s = bucketize(day_map(views, "timestamp", p["start_dt"], p["end_dt"]), p)

    hours_rows = attempts.annotate(_h=ExtractHour("created_at", tzinfo=MSK)).values("_h").annotate(c=Count("pk"))
    hm = {r["_h"]: r["c"] for r in hours_rows}

    score_bins = [0] * 10
    for x in pcts:
        score_bins[min(int(x // 10), 9)] += 1

    questions, analysed = question_breakdown(s, attempts)

    amap = authors_map([s.id_staff])
    author = _author(amap, s.id_staff)
    author_stats = Survey.objects.filter(id_staff=s.id_staff).aggregate(
        tests=Count("pk"), alive=Count("pk", filter=Q(is_visible=False)), views=Coalesce(Sum("view_count"), 0))
    author_stats["attempts"] = TestAttempt.objects.filter(survey__id_staff=s.id_staff).count()

    feedbacks = FeedbackFromAI.objects.filter(survey_id=s.survey_id).count()
    gp_params = s.generation_params or {}

    return JsonResponse({
        "ok": True,
        "survey": {
            "survey_id": str(s.survey_id), "title": s.title, "description": s.description or "",
            "created": _msk(s.created_at), "updated": _msk(s.updated_at),
            "age_days": (_today() - created_d).days,
            "model": s.model_name or "", "questions_count": s.questions_count,
            "deleted": s.is_visible, "is_private": s.is_private, "is_verified": s.is_verified,
            "is_in_marketplace": s.is_in_marketplace, "show_answers": s.show_answers,
            "difficulty": gp_params.get("difficulty") or "", "question_types": gp_params.get("question_types") or [],
            "shuffle": bool(gp_params.get("shuffle_questions")), "source": _source_of(s),
            "source_file": gp_params.get("source_file") or "",
            "source_text": (s.source_text or "")[:20000], "source_len": len(s.source_text or ""),
            "generation_params": gp_params, "feedbacks": feedbacks,
        },
        "author": {**author, **author_stats},
        "kpi": {
            "views": s.view_count, "views_logged": views_logged, "views_period": views_period,
            "attempts": att_total, "attempts_period": att_period,
            "conversion": round(att_total / s.view_count * 100, 1) if s.view_count else None,
            "avg": round(sum(pcts) / len(pcts), 1) if pcts else None,
            "median": round(median(pcts), 1) if pcts else None,
            "passed": share(lambda x: x >= 50), "perfect": share(lambda x: x >= 100),
            "students": agg["students"], "first_attempt": _msk(agg["first"]), "last_attempt": _msk(agg["last"]),
            "last_view": _msk(last_view),
        },
        "series": {**period_json(p), "attempts": att_s, "views": views_s},
        "scores": {"labels": [f"{i * 10}–{i * 10 + 10}" for i in range(10)], "data": score_bins},
        "hours": {"labels": [f"{h:02d}" for h in range(24)], "data": [hm.get(h, 0) for h in range(24)]},
        "questions": questions, "questions_analysed": analysed,
        "attempts": {"items": [_attempt_row(a) for a in attempts.order_by("-created_at")[:30]],
                     "total": att_total, "page": 1, "per": 30},
    })


@admin_api
@require_GET
def api_admin_survey_attempts(request, survey_id):
    try:
        sid = uuid.UUID(str(survey_id))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Невалидный UUID"}, status=400)
    s = Survey.objects.filter(survey_id=sid).only("pk").first()
    if not s:
        return JsonResponse({"ok": False, "error": "Тест не найден"}, status=404)
    per = 30
    qs = TestAttempt.objects.filter(survey=s)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(student_name__icontains=q)
    order = {"score": ("-score", "-created_at"), "-score": ("score", "-created_at")}.get(request.GET.get("sort"), ("-created_at",))
    total = qs.count()
    page = _int(request.GET.get("page"), 1, 1)
    items = [_attempt_row(a) for a in qs.order_by(*order)[(page - 1) * per: page * per]]
    return JsonResponse({"ok": True, "items": items, "total": total, "page": page, "per": per})


# =====================================================================
#  Действия
# =====================================================================

def _body(request):
    try:
        return json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return {}


def _get_survey(data):
    try:
        return Survey.objects.filter(survey_id=uuid.UUID(str(data.get("survey_id")))).first()
    except (TypeError, ValueError):
        return None


def _drop_caches():
    cache.delete("surveys_ops:facets")
    # overview живёт 2 минуты — не страшно, но фронт после действий шлёт fresh=1


@admin_api
@require_POST
def api_admin_survey_visibility(request):
    data = _body(request)
    s = _get_survey(data)
    if not s:
        return JsonResponse({"ok": False, "error": "Тест не найден"}, status=404)
    deleted = bool(data.get("deleted"))
    s.is_visible = deleted  # is_visible == «удалён»
    s.save(update_fields=["is_visible", "updated_at"])
    _drop_caches()
    log.info(f"ADMIN SURVEY {'HIDE' if deleted else 'RESTORE'}: {request.user.username} -> {s.survey_id} «{s.title}»")
    return JsonResponse({"ok": True, "deleted": s.is_visible})


FLAG_FIELDS = ("is_verified", "is_in_marketplace", "is_private", "show_answers")


@admin_api
@require_POST
def api_admin_survey_flags(request):
    data = _body(request)
    s = _get_survey(data)
    if not s:
        return JsonResponse({"ok": False, "error": "Тест не найден"}, status=404)
    field = data.get("field")
    if field not in FLAG_FIELDS:
        return JsonResponse({"ok": False, "error": "Недопустимое поле"}, status=400)
    setattr(s, field, bool(data.get("value")))
    s.save(update_fields=[field, "updated_at"])
    log.info(f"ADMIN SURVEY FLAG: {request.user.username} {s.survey_id} {field}={getattr(s, field)}")
    return JsonResponse({"ok": True, "field": field, "value": getattr(s, field)})


@admin_api
@require_POST
def api_admin_delete_survey(request):
    """Удаление из БД насовсем. Требует confirm == survey_id (защита от случайного клика)."""
    data = _body(request)
    s = _get_survey(data)
    if not s:
        return JsonResponse({"ok": False, "error": "Тест не найден"}, status=404)
    if str(data.get("confirm")) != str(s.survey_id):
        return JsonResponse({"ok": False, "error": "Удаление не подтверждено"}, status=400)
    title, sid = s.title, s.survey_id
    with transaction.atomic():
        attempts = TestAttempt.objects.filter(survey=s).count()
        UserAnswers.objects.filter(survey_id=sid).delete()
        FeedbackFromAI.objects.filter(survey_id=sid).delete()
        s.delete()  # TestAttempt, SurveyUniqueView, Question — каскадом
    _drop_caches()
    log.warning(f"ADMIN SURVEY DESTROY: {request.user.username} удалил {sid} «{title}», попыток {attempts}")
    return JsonResponse({"ok": True, "message": f"Тест «{title}» удалён вместе с {attempts} прохождениями"})
