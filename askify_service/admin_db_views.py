"""
askify_service/admin_db_views.py

Вьюхи страницы «Трафик-контрол»: живой трафик, база данных, производительность.
Заменяют admin_traffic_live_view и api_admin_traffic_live из views.py
(старые функции из views.py удалить, в urls.py импортировать отсюда).

Доступ только суперпользователю.
"""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import db_insights, perf_monitor
from .models import DbSnapshot, TrafficLog

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser)


@superuser_required
def admin_traffic_live_view(request):
    return render(request, "admin/admin_traffic_live.html", {
        "page_title": "Трафик-контрол | ЦУП Летучки",
        "statements_on": db_insights.statements_available(),
    })


# --------------------------------------------------------------------------
# Трафик: было ~80 SQL на опрос, стало 6
# --------------------------------------------------------------------------

def _delta(cur, prev):
    if prev == 0:
        pct = 100.0 if cur > 0 else 0.0
    else:
        pct = round((cur - prev) / prev * 100, 1)
    return {"val": pct, "is_positive": pct >= 0, "str": f"+{pct}%" if pct > 0 else f"{pct}%"}


@superuser_required
@require_GET
def api_admin_traffic_live(request):
    now = timezone.now()
    today_start = now.astimezone(MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = now - today_start
    y_start, a_start = today_start - timedelta(days=1), today_start - timedelta(days=7)
    y_end, a_end = y_start + elapsed, a_start + elapsed

    win = {
        "t": Q(created_at__gte=today_start, created_at__lte=now),
        "y": Q(created_at__gte=y_start, created_at__lte=y_end),
        "a": Q(created_at__gte=a_start, created_at__lte=a_end),
    }
    human, bot = Q(is_bot=False), Q(is_bot=True)
    mobile = Q(user_agent__iregex=r"(mobile|iphone|android|ipad)")

    # 1 запрос: все срезы сегодня/вчера/АППН + мобильные
    agg = TrafficLog.objects.filter(
        Q(created_at__gte=a_start, created_at__lte=a_end)
        | Q(created_at__gte=y_start, created_at__lte=y_end)
        | Q(created_at__gte=today_start)
    ).aggregate(
        **{f"{w}_real": Count("id", filter=win[w] & human) for w in win},
        **{f"{w}_bots": Count("id", filter=win[w] & bot) for w in win},
        **{f"{w}_uniq": Count("ip", filter=win[w] & human, distinct=True) for w in win},
        t_mobile=Count("id", filter=win["t"] & human & mobile),
    )

    # 1 запрос: RPS и онлайн
    live = TrafficLog.objects.filter(created_at__gte=now - timedelta(minutes=5)).aggregate(
        last_min=Count("id", filter=Q(created_at__gte=now - timedelta(seconds=60))),
        online_real=Count("ip", filter=human, distinct=True),
        online_bots=Count("ip", filter=bot, distinct=True),
    )

    # 1 запрос: таймлайн 30 мин, шаг 2 мин
    table = TrafficLog._meta.db_table
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT floor(EXTRACT(EPOCH FROM (%s - created_at)) / 120)::int AS b,
                   count(*) FILTER (WHERE NOT is_bot), count(*) FILTER (WHERE is_bot)
            FROM {table} WHERE created_at > %s GROUP BY 1
        """, [now, now - timedelta(minutes=60)])
        by_b = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    labels, real, bots = [], [], []
    for i in range(29, -1, -1):
        labels.append((now - timedelta(minutes=i * 2)).astimezone(MOSCOW_TZ).strftime("%H:%M"))
        r, b = by_b.get(i, (0, 0))
        real.append(r)
        bots.append(b)

    # 1 запрос: топ страниц, 1 запрос: лента
    top_pages = list(
        TrafficLog.objects.filter(win["t"] & human)
        .values("path").annotate(hits=Count("id")).order_by("-hits")[:8]
    )
    feed = []
    for log in TrafficLog.objects.only("ip", "path", "user_agent", "is_bot", "created_at").order_by("-created_at")[:30]:
        ua = (log.user_agent or "").lower()
        if "iphone" in ua or "ipad" in ua:
            ua_short = "iOS Safari"
        elif "android" in ua:
            ua_short = "Android Web"
        elif log.is_bot:
            ua_short = "Bot / Crawler"
        elif "yandex" in ua:
            ua_short = "Yandex"
        elif "chrome" in ua:
            ua_short = "Chrome"
        else:
            ua_short = "Desktop"
        feed.append({
            "ip": log.ip, "path": log.path, "is_bot": log.is_bot, "ua": ua_short,
            "time": log.created_at.astimezone(MOSCOW_TZ).strftime("%H:%M:%S"),
        })

    # 1 запрос: топ IP за сегодня (люди и боты отдельно)
    top_ips = list(
        TrafficLog.objects.filter(win["t"])
        .values("ip", "is_bot").annotate(hits=Count("id"), pages=Count("path", distinct=True))
        .order_by("-hits")[:12]
    )

    t_real, t_bots = agg["t_real"], agg["t_bots"]
    total = t_real + t_bots
    mob = agg["t_mobile"]

    def tele(key):
        return {"current": agg[f"t_{key}"], "yesterday": agg[f"y_{key}"],
                "dod": _delta(agg[f"t_{key}"], agg[f"y_{key}"]),
                "appn": agg[f"a_{key}"], "wow": _delta(agg[f"t_{key}"], agg[f"a_{key}"])}

    return JsonResponse({
        "rps": round(live["last_min"] / 60.0, 2),
        "online_real": live["online_real"],
        "online_bots": live["online_bots"],
        "clean_ratio": round(t_real / total * 100, 1) if total else 100.0,
        "bot_ratio": round(t_bots / total * 100, 1) if total else 0.0,
        "device_stats": {
            "mobile_pct": round(mob / t_real * 100, 1) if t_real else 0.0,
            "desktop_pct": round((t_real - mob) / t_real * 100, 1) if t_real else 0.0,
        },
        "telemetry": {"uniques": tele("uniq"), "real_hits": tele("real"), "bot_hits": tele("bots")},
        "top_pages": top_pages,
        "top_ips": top_ips,
        "timeline": {"labels": labels, "real": real, "bots": bots},
        "feed": feed,
    })


# --------------------------------------------------------------------------
# База данных
# --------------------------------------------------------------------------

@superuser_required
def api_admin_db_snapshot(request):
    """GET — последний (или ?id=) снимок; POST — снять новый."""
    if request.method == "POST":
        snap = DbSnapshot.take()
    else:
        sid = request.GET.get("id")
        snap = (DbSnapshot.objects.filter(id=sid).first() if sid
                else DbSnapshot.objects.order_by("-created_at").first())
        if snap is None:
            snap = DbSnapshot.take()
    return JsonResponse({
        "id": snap.id,
        "created_at": snap.created_at.isoformat(),
        "data": snap.data,
    })


@superuser_required
@require_GET
def api_admin_db_history(request):
    """Лёгкая история: размер базы и таблиц по всем снимкам — для графиков роста."""
    rows = DbSnapshot.objects.order_by("created_at").values("id", "created_at", "db_size", "brief")
    return JsonResponse({"items": [
        {"id": r["id"], "ts": r["created_at"].isoformat(), "db_size": r["db_size"], "tables": r["brief"]}
        for r in rows
    ]})


@superuser_required
@require_GET
def api_admin_db_activity(request):
    return JsonResponse(db_insights.collect_activity())


@superuser_required
@require_POST
def api_admin_db_count(request):
    try:
        name = json.loads(request.body or "{}").get("table", "")
        return JsonResponse(db_insights.exact_count(name))
    except Exception as e:
        return JsonResponse({"error": str(e)[:300]}, status=400)


@superuser_required
@require_GET
def api_admin_db_statements(request):
    return JsonResponse(db_insights.collect_statements(limit=60))


@superuser_required
@require_POST
def api_admin_db_statements_reset(request):
    return JsonResponse({"ok": db_insights.reset_statements()})


# --------------------------------------------------------------------------
# Производительность Django
# --------------------------------------------------------------------------

@superuser_required
def api_admin_perf(request):
    if request.method == "POST":
        perf_monitor.reset_stats()
        return JsonResponse({"ok": True})
    hours = max(1, min(48, int(request.GET.get("hours", 24))))
    return JsonResponse(perf_monitor.read_stats(hours))
