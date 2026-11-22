# ===================================================================================
# admin_dashboard.py — ДВА места
#
# 1) В блоке импортов django.db.models (строка `from django.db.models import Avg, Count, F, Max, Min, Q, Sum`)
#    замени её на:
#
#        from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Max, Min, Q, Sum
#
# 2) Весь код ниже вставь В САМЫЙ КОНЕЦ файла (после get_cached_weather).
# ===================================================================================

LOST_AFTER_MIN = 3   # задача в статусе «queued» дольше стольких минут считается потерянной (воркер не отработал)


def _fl(value, digits: int = 4) -> float:
    return round(float(value or 0), digits)


@require_GET
@superuser_json
def admin_dashboard_ads_api(request):
    """Статистика рекламы Gradius за период: запросы, получено, показано, клики, заработок (оценка)."""
    from .ads import _credentials, ads_enabled
    from .models import AdEvent

    now = timezone.now()
    today = timezone.localdate()
    period = _parse_period(request, today)
    rng, prev = period.range, period.prev_range
    n = len(period.keys)

    FOUND = Q(status="found")
    LOST = Q(status="queued", created_at__lt=now - timedelta(minutes=LOST_AFTER_MIN))
    click_money = ExpressionWrapper(F("click_price") * F("click_count"), output_field=DecimalField(max_digits=18, decimal_places=6))

    def _agg(qs):
        return qs.aggregate(
            requests=Count("pk"),
            found=Count("pk", filter=FOUND),
            empty=Count("pk", filter=Q(status="empty")),
            error=Count("pk", filter=Q(status="error")),
            lost=Count("pk", filter=LOST),
            earned=Sum("show_price", filter=FOUND),
            shown_tests=Count("pk", filter=FOUND & Q(shown_count__gt=0)),
            earned_shown=Sum("show_price", filter=FOUND & Q(shown_count__gt=0)),
            shown=Sum("shown_count"),
            clicks=Sum("click_count"),
            clicked_tests=Count("pk", filter=FOUND & Q(click_count__gt=0)),
            click_money=Sum(click_money),
            avg_ms=Avg("latency_ms", filter=Q(latency_ms__isnull=False)),
        )

    qs_cur = AdEvent.objects.filter(created_at__date__range=rng)
    qs_prev = AdEvent.objects.filter(created_at__date__range=prev)
    cur, old = _agg(qs_cur), _agg(qs_prev)
    gens_cur = Survey.objects.filter(created_at__date__range=rng).count()
    gens_prev = Survey.objects.filter(created_at__date__range=prev).count()

    answered = cur["found"] + cur["empty"]
    failed = cur["error"] + cur["lost"]
    earned_total = _fl(cur["earned"], 4)
    click_earned = _fl(cur["click_money"], 4)

    # ---------- Ряды для графиков ----------
    s_found, s_empty, s_failed, s_req = period.zeros(), period.zeros(), period.zeros(), period.zeros()
    s_earned, s_shown, s_clicks = period.zeros(), period.zeros(), period.zeros()
    rows = _by_day(
        qs_cur, "created_at",
        r=Count("pk"),
        f=Count("pk", filter=FOUND),
        e=Count("pk", filter=Q(status="empty")),
        x=Count("pk", filter=Q(status="error") | LOST),
        s=Sum("show_price", filter=FOUND),
        v=Sum("shown_count"),
        c=Sum("click_count"),
    )
    for row in rows:
        i = period.slot(row["_day"])
        if i is None:
            continue
        s_req[i] += row["r"]
        s_found[i] += row["f"]
        s_empty[i] += row["e"]
        s_failed[i] += row["x"]
        s_earned[i] += float(row["s"] or 0)
        s_shown[i] += float(row["v"] or 0)
        s_clicks[i] += float(row["c"] or 0)

    # ---------- Разрезы ----------
    def _split(field, labels):
        out = []
        for r in (
            qs_cur.order_by().values(field).annotate(
                c=Count("pk"),
                f=Count("pk", filter=FOUND),
                em=Count("pk", filter=Q(status="empty")),
                er=Count("pk", filter=Q(status="error")),
                s=Sum("show_price", filter=FOUND),
                v=Sum("shown_count"),
                ck=Sum("click_count"),
                ms=Avg("latency_ms", filter=Q(latency_ms__isnull=False)),
            )
        ):
            key = r[field]
            out.append({
                "key": str(key),
                "label": labels.get(key, str(key)),
                "requests": r["c"],
                "found": r["f"],
                "empty": r["em"],
                "error": r["er"],
                "earned": _fl(r["s"]),
                "shown": int(r["v"] or 0),
                "clicks": int(r["ck"] or 0),
                "avg_ms": int(r["ms"] or 0),
            })
        return sorted(out, key=lambda x: -x["requests"])

    audience = _split("is_guest", {True: "Гости без регистрации", False: "Зарегистрированные"})
    sources = _split("source", {"text": "Из текста", "file": "Из файла"})

    # ---------- Ошибки ----------
    errors = [
        {"code": r["error_code"] or "unknown", "count": r["c"]}
        for r in qs_cur.filter(status="error").order_by().values("error_code").annotate(c=Count("pk")).order_by("-c")[:6]
    ]
    if cur["lost"]:
        errors.insert(0, {"code": "lost", "count": cur["lost"]})

    # ---------- Лента последних рекламных попыток ----------
    feed_rows = list(AdEvent.objects.order_by("-created_at")[:12])
    uuids = []
    for e in feed_rows:
        try:
            uuids.append(uuid.UUID(e.survey_id))
        except ValueError:
            pass
    titles = {str(s.survey_id): s.title for s in Survey.objects.filter(survey_id__in=uuids).only("survey_id", "title")}
    feed = [
        {
            "title": titles.get(e.survey_id) or "Тест удалён или служебный",
            "time": _local_str(e.created_at, "%d.%m %H:%M"),
            "status": "lost" if (e.status == "queued" and e.created_at < now - timedelta(minutes=LOST_AFTER_MIN)) else e.status,
            "error_code": e.error_code,
            "price": _fl(e.show_price, 6),
            "click_price": _fl(e.click_price, 6),
            "shown": e.shown_count,
            "clicks": e.click_count,
            "snippet": e.snippet,
            "source": e.source,
            "guest": e.is_guest,
            "ms": e.latency_ms,
        }
        for e in feed_rows
    ]

    # ---------- За всё время ----------
    life = AdEvent.objects.aggregate(
        n=Count("pk"),
        found=Count("pk", filter=FOUND),
        earned=Sum("show_price", filter=FOUND),
        first=Min("created_at"),
        last=Max("created_at"),
        last_found=Max("created_at", filter=FOUND),
    )

    return JsonResponse({
        "ok": True,
        "generated_at": _local_str(now, "%H:%M:%S"),
        "period": period.as_dict(),
        "config": {"enabled": ads_enabled(), "token_set": bool(_credentials()[0])},
        "kpi": {
            "requests": _metric(cur["requests"], old["requests"]),
            "found": _metric(cur["found"], old["found"]),
            "empty": cur["empty"],
            "error": cur["error"],
            "lost": cur["lost"],
            "failed": failed,
            "fill_rate": _rate(cur["found"], answered),
            "error_rate": _rate(failed, cur["requests"]),
            "earned": _metric(earned_total, _fl(old["earned"], 4), 4),
            "earned_shown": _fl(cur["earned_shown"], 4),
            "click_earned": click_earned,
            "avg_price": round(earned_total / cur["found"], 6) if cur["found"] else None,
            "shown": _metric(cur["shown"] or 0, old["shown"] or 0),
            "shown_tests": cur["shown_tests"],
            "clicks": _metric(cur["clicks"] or 0, old["clicks"] or 0),
            "clicked_tests": cur["clicked_tests"],
            "ctr": _rate(cur["clicks"] or 0, cur["shown"] or 0),
            "avg_ms": int(cur["avg_ms"] or 0),
            "generations": _metric(gens_cur, gens_prev),
        },
        "series": {
            "requests": [int(v) for v in s_req],
            "found": [int(v) for v in s_found],
            "empty": [int(v) for v in s_empty],
            "failed": [int(v) for v in s_failed],
            "earned": _round_list(s_earned, 4),
            "shown": [int(v) for v in s_shown],
            "clicks": [int(v) for v in s_clicks],
        },
        "audience": audience,
        "sources": sources,
        "errors": errors,
        "feed": feed,
        "totals": {
            "events": life["n"],
            "found": life["found"],
            "earned": _fl(life["earned"], 4),
            "first": _local_str(life["first"], "%d.%m.%Y"),
            "last": _local_str(life["last"], "%d.%m %H:%M"),
            "last_found": _local_str(life["last_found"], "%d.%m %H:%M"),
        },
    })
