"""
Лёгкий профайлер Django-маршрутов для продакшена.

На каждый запрос считает: время ответа, число SQL-запросов, время в БД,
дубли SQL (признак N+1). Агрегаты складываются в кэш (Redis) по часовым
корзинам, в базу ничего не пишется. Хранится 48 часов.

Подключение (settings.py), ближе к началу MIDDLEWARE:
    "askify_service.perf_monitor.PerfMonitorMiddleware",

Настройки (необязательные):
    PERF_MONITOR_ENABLED = True
    PERF_MONITOR_SAMPLE_RATE = 1.0     # доля запросов, которые меряем
    PERF_MONITOR_SLOW_MS = 800         # порог «медленного» запроса
    PERF_MONITOR_SKIP_PREFIXES = ("/static/", "/media/", "/api/admin/")

Важно: нужен общий для всех воркеров кэш (Redis/Memcached). С LocMemCache
каждый воркер gunicorn увидит только свою долю запросов.
"""
import random
import re
import time
from collections import Counter

from django.conf import settings
from django.core.cache import cache
from django.db import connection

BUCKET_SEC = 3600
KEEP_HOURS = 48
TTL = (KEEP_HOURS + 2) * 3600
SLOW_KEEP = 50

_num_re = re.compile(r"\b\d+\b|'[^']*'")


def _cfg(name, default):
    return getattr(settings, name, default)


def _bucket(ts=None):
    return int((ts or time.time()) // BUCKET_SEC)


class _QueryCounter:
    __slots__ = ("count", "ms", "shapes")

    def __init__(self):
        self.count = 0
        self.ms = 0.0
        self.shapes = Counter()

    def __call__(self, execute, sql, params, many, context):
        t0 = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.ms += (time.perf_counter() - t0) * 1000
            self.count += 1
            self.shapes[_num_re.sub("?", sql)[:300]] += 1


def _incr(key, delta):
    try:
        cache.incr(key, delta)
    except ValueError:
        if not cache.add(key, delta, TTL):
            cache.incr(key, delta)


def _set_max(key, value):
    cur = cache.get(key) or 0
    if value > cur:
        cache.set(key, value, TTL)


class PerfMonitorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = _cfg("PERF_MONITOR_ENABLED", True)
        self.rate = float(_cfg("PERF_MONITOR_SAMPLE_RATE", 1.0))
        self.slow_ms = int(_cfg("PERF_MONITOR_SLOW_MS", 800))
        self.skip = tuple(_cfg("PERF_MONITOR_SKIP_PREFIXES", ("/static/", "/media/", "/favicon", "/api/admin/")))

    def __call__(self, request):
        if not self.enabled or request.path.startswith(self.skip) or (
            self.rate < 1 and random.random() > self.rate
        ):
            return self.get_response(request)

        qc = _QueryCounter()
        t0 = time.perf_counter()
        with connection.execute_wrapper(qc):
            response = self.get_response(request)
        total_ms = (time.perf_counter() - t0) * 1000

        try:
            self._record(request, response, total_ms, qc)
        except Exception:
            pass  # мониторинг никогда не ломает ответ
        return response

    def _record(self, request, response, total_ms, qc):
        match = getattr(request, "resolver_match", None)
        route = (match.route if match and match.route else None) or (
            match.view_name if match else None) or "<unresolved>"
        route = f"{request.method} /{route.lstrip('/')}"[:200]
        b = _bucket()
        base = f"perf:{b}:{route}"

        routes_key = f"perf:{b}:routes"
        routes = cache.get(routes_key) or set()
        if route not in routes:
            routes.add(route)
            cache.set(routes_key, routes, TTL)

        dup = sum(n - 1 for n in qc.shapes.values() if n > 1)
        _incr(f"{base}:n", 1)
        _incr(f"{base}:ms", int(total_ms))
        _incr(f"{base}:q", qc.count)
        _incr(f"{base}:dbms", int(qc.ms))
        _incr(f"{base}:dup", dup)
        if response.status_code >= 500:
            _incr(f"{base}:e5", 1)
        elif response.status_code >= 400:
            _incr(f"{base}:e4", 1)
        if total_ms >= self.slow_ms:
            _incr(f"{base}:slow", 1)
        _set_max(f"{base}:maxms", int(total_ms))
        _set_max(f"{base}:maxq", qc.count)
        # гистограмма для перцентилей
        edge = next((e for e in (25, 50, 100, 200, 400, 800, 1600, 3200) if total_ms < e), 99999)
        _incr(f"{base}:h{edge}", 1)

        if total_ms >= self.slow_ms or qc.count >= 50 or dup >= 10:
            top_dup = qc.shapes.most_common(1)[0] if qc.shapes else ("", 0)
            slow = cache.get("perf:slowlog") or []
            slow.insert(0, {
                "ts": time.time(),
                "route": route,
                "path": request.path[:200],
                "ms": round(total_ms, 1),
                "db_ms": round(qc.ms, 1),
                "queries": qc.count,
                "dup": dup,
                "top_sql": top_dup[0][:300] if top_dup[1] > 1 else "",
                "top_sql_n": top_dup[1],
                "status": response.status_code,
            })
            cache.set("perf:slowlog", slow[:SLOW_KEEP], TTL)


HIST_EDGES = (25, 50, 100, 200, 400, 800, 1600, 3200, 99999)


def _pctl(hist, total, p):
    if not total:
        return None
    need = total * p
    acc = 0
    for e in HIST_EDGES:
        acc += hist.get(e, 0)
        if acc >= need:
            return e
    return HIST_EDGES[-1]


def read_stats(hours=24):
    """Агрегаты по маршрутам за последние N часов + почасовая серия."""
    now_b = _bucket()
    buckets = list(range(now_b - hours + 1, now_b + 1))
    fields = ["n", "ms", "q", "dbms", "dup", "e4", "e5", "slow", "maxms", "maxq"] + [f"h{e}" for e in HIST_EDGES]

    per_route = {}
    series = []
    for b in buckets:
        routes = cache.get(f"perf:{b}:routes") or set()
        keys = [f"perf:{b}:{r}:{f}" for r in routes for f in fields]
        vals = cache.get_many(keys) if keys else {}
        bn = bms = bq = 0
        for r in routes:
            g = lambda f: vals.get(f"perf:{b}:{r}:{f}") or 0
            agg = per_route.setdefault(r, {f: 0 for f in fields})
            for f in fields:
                if f in ("maxms", "maxq"):
                    agg[f] = max(agg[f], g(f))
                else:
                    agg[f] += g(f)
            bn += g("n"); bms += g("ms"); bq += g("q")
        series.append({
            "ts": b * BUCKET_SEC,
            "requests": bn,
            "avg_ms": round(bms / bn, 1) if bn else 0,
            "avg_queries": round(bq / bn, 1) if bn else 0,
        })

    items = []
    for r, a in per_route.items():
        n = a["n"]
        if not n:
            continue
        hist = {e: a[f"h{e}"] for e in HIST_EDGES}
        items.append({
            "route": r,
            "requests": n,
            "avg_ms": round(a["ms"] / n, 1),
            "p50_ms": _pctl(hist, n, 0.5),
            "p95_ms": _pctl(hist, n, 0.95),
            "max_ms": a["maxms"],
            "avg_queries": round(a["q"] / n, 1),
            "max_queries": a["maxq"],
            "avg_db_ms": round(a["dbms"] / n, 1),
            "db_share_pct": round(a["dbms"] / a["ms"] * 100, 1) if a["ms"] else 0,
            "dup_per_req": round(a["dup"] / n, 1),
            "errors_4xx": a["e4"],
            "errors_5xx": a["e5"],
            "slow": a["slow"],
            "total_time_s": round(a["ms"] / 1000, 1),
        })
    items.sort(key=lambda x: x["total_time_s"], reverse=True)
    return {
        "hours": hours,
        "routes": items,
        "series": series,
        "slowlog": cache.get("perf:slowlog") or [],
        "cache_backend": settings.CACHES.get("default", {}).get("BACKEND", ""),
    }


def reset_stats():
    now_b = _bucket()
    for b in range(now_b - KEEP_HOURS, now_b + 1):
        routes = cache.get(f"perf:{b}:routes") or set()
        cache.delete(f"perf:{b}:routes")
        for r in routes:
            cache.delete_many([f"perf:{b}:{r}:{f}" for f in
                               ["n", "ms", "q", "dbms", "dup", "e4", "e5", "slow", "maxms", "maxq"]
                               + [f"h{e}" for e in HIST_EDGES]])
    cache.delete("perf:slowlog")
