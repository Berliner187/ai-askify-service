"""
Периоды статистики профиля: 7 / 30 / 90 / 180 дней, год, всё время.
Чистый Python, без Django.
"""
import calendar
from bisect import bisect_right
from datetime import date, timedelta
from math import ceil

PERIODS = ("7", "30", "90", "180", "365", "all")
DEFAULT_PERIOD = "7"

PERIOD_LABELS = {
    "7": "7 дней",
    "30": "30 дней",
    "90": "90 дней",
    "180": "180 дней",
    "365": "год",
    "all": "всё время",
}

_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря"]
_MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн",
                 "июл", "авг", "сен", "окт", "ноя", "дек"]
_MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
               "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def normalize_period(raw, is_premium=True):
    """Из GET-параметра -> валидный период. Без премиума доступна только неделя."""
    p = str(raw or DEFAULT_PERIOD).strip().lower()
    if p not in PERIODS:
        p = DEFAULT_PERIOD
    return p if is_premium else DEFAULT_PERIOD


def _day(d):
    return f"{d.day} {_MONTHS_SHORT[d.month - 1]}"


def _range_title(a, b):
    if a == b:
        return f"{a.day} {_MONTHS_GEN[a.month - 1]}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {_MONTHS_GEN[b.month - 1]}"
    return f"{a.day} {_MONTHS_GEN[a.month - 1]} – {b.day} {_MONTHS_GEN[b.month - 1]}"


def build_plan(period, today, first_activity=None):
    """Возвращает dict: kind, start, end, days, buckets[{start,end,label,title}]."""
    if period == "all":
        first = min(first_activity or today, today)
        span = max((today - first).days + 1, 7)
    elif period == "365":
        m, y = today.month - 11, today.year
        if m <= 0:
            m, y = m + 12, y - 1
        span = (today - date(y, m, 1)).days + 1
    else:
        span = int(period)

    if period in ("7", "30") or (period == "all" and span <= 45):
        kind = "day"
    elif period in ("90", "180") or (period == "all" and span <= 210):
        kind = "week"
    elif period == "365" or (period == "all" and span <= 1100):
        kind = "month"
    else:
        kind = "year"

    start = today - timedelta(days=span - 1)
    buckets = []

    if kind == "day":
        for i in range(span):
            d = start + timedelta(days=i)
            buckets.append({"start": d, "end": d, "label": _day(d),
                            "title": _range_title(d, d)})

    elif kind == "week":
        n = ceil(span / 7)
        start = today - timedelta(days=7 * n - 1)
        for k in range(n):
            e = today - timedelta(days=7 * (n - 1 - k))
            s = e - timedelta(days=6)
            buckets.append({"start": s, "end": e, "label": _day(s),
                            "title": _range_title(s, e)})

    elif kind == "month":
        if period == "365":
            m, y = today.month - 11, today.year
            if m <= 0:
                m, y = m + 12, y - 1
            start = date(y, m, 1)
        y, m, i = start.year, start.month, 0
        while (y, m) <= (today.year, today.month):
            ms, me = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            label = _MONTHS_SHORT[m - 1]
            if i == 0 or m == 1:
                label += f" ’{str(y)[2:]}"
            buckets.append({"start": max(ms, start), "end": min(me, today), "label": label,
                            "title": f"{_MONTHS_NOM[m - 1]} {y}"})
            m, i = m + 1, i + 1
            if m > 12:
                m, y = 1, y + 1

    else:  # year
        for y in range(start.year, today.year + 1):
            buckets.append({"start": max(date(y, 1, 1), start), "end": min(date(y, 12, 31), today),
                            "label": str(y), "title": f"{y} год"})

    return {"kind": kind, "start": start, "end": today,
            "days": (today - start).days + 1, "buckets": buckets}


def bucketize(day_map, plan):
    """{date: count} -> [count на корзину]. Даты вне плана игнорируются."""
    bs = plan["buckets"]
    starts = [b["start"] for b in bs]
    out = [0] * len(bs)
    for d, c in day_map.items():
        if d is None:
            continue
        i = bisect_right(starts, d) - 1
        if 0 <= i < len(bs) and d <= bs[i]["end"]:
            out[i] += c or 0
    return out


def chart_payload(plan, day_map):
    """Готовый кусок JSON для одного графика."""
    bs = plan["buckets"]
    return {
        "labels": [b["label"] for b in bs],
        "titles": [b["title"] for b in bs],
        "starts": [b["start"].isoformat() for b in bs],
        "data": bucketize(day_map, plan),
    }


def meta_payload(plan, period, is_premium):
    return {
        "period": period,
        "label": PERIOD_LABELS[period],
        "kind": plan["kind"],
        "days": plan["days"],
        "from": plan["start"].isoformat(),
        "to": plan["end"].isoformat(),
        "premium": bool(is_premium),
    }
