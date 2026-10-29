"""
Сводка на странице «История»: сдачи / просмотры / новые тесты / живые тесты за период
+ сравнение с предыдущим таким же периодом.

Чистый Python (без Django), как и stats_periods.py — легко тестируется.
Вьюха достаёт из БД «день -> количество» за окно [prev_start .. end] и отдаёт сюда.

Что считаем:
    attempts  — сдачи (TestAttempt.created_at)
    views     — уникальные просмотры (SurveyUniqueView.timestamp)
    created   — новые тесты (Survey.created_at)
    live      — «живые» тесты: тесты, у которых за период была хотя бы одна сдача
                (считается отдельным DISTINCT-запросом, из дневных рядов не получить)
Конверсию «сдачи / просмотры» намеренно не считаем: сдача сама регистрирует просмотр,
просмотры уникальные — процент врёт.
"""
from datetime import timedelta

from .stats_periods import build_plan, bucketize, meta_payload

GHOST_KINDS = ("day", "week")  # «прошлый период» призраком рисуем только там, где корзины совпадают


def window(period, today, first_activity=None):
    """plan + границы текущего и предыдущего окон (одинаковой длины)."""
    plan = build_plan(period, today, first_activity)
    span = plan["days"]
    has_prev = period != "all"
    cur = (plan["start"], plan["end"])
    prev = (plan["start"] - timedelta(days=span), plan["start"] - timedelta(days=1)) if has_prev else None
    return plan, cur, prev, span


def _split(day_map, start, span, end):
    """Режет карту на текущее окно [start..end] и предыдущее [start-span .. start-1]; остальное игнорируем."""
    prev_start = start - timedelta(days=span)
    cur, prev = {}, {}
    for d, c in (day_map or {}).items():
        if d is None:
            continue
        if start <= d <= end:
            cur[d] = c or 0
        elif prev_start <= d < start:
            prev[d] = c or 0
    return cur, prev


def assemble_summary(period, plan, span, att_map, views_map, created_map,
                     live_cur, live_prev, total_tests, is_premium=True):
    """Собирает JSON. *_map — {date: count} за окно [prev_start .. end] (для 'all' — только текущее)."""
    start, end = plan["start"], plan["end"]
    has_prev = period != "all"

    a_cur, a_prev = _split(att_map, start, span, end)
    v_cur, v_prev = _split(views_map, start, span, end)
    c_cur, c_prev = _split(created_map, start, span, end)

    def tot(m):
        return int(sum(m.values()))

    totals = {"attempts": tot(a_cur), "views": tot(v_cur), "created": tot(c_cur), "live": int(live_cur or 0)}
    prev = None
    if has_prev:
        prev = {"attempts": tot(a_prev), "views": tot(v_prev), "created": tot(c_prev), "live": int(live_prev or 0)}

    ghost = None
    if has_prev and plan["kind"] in GHOST_KINDS:
        shift = timedelta(days=span)
        ghost = bucketize({d + shift: c for d, c in a_prev.items()}, plan)

    bs = plan["buckets"]
    return {
        "premium": bool(is_premium),
        "meta": meta_payload(plan, period, is_premium),
        "labels": [b["label"] for b in bs],
        "titles": [b["title"] for b in bs],
        "attempts": bucketize(a_cur, plan),
        "views": bucketize(v_cur, plan),
        "created": bucketize(c_cur, plan),
        "ghost": ghost,
        "totals": totals,
        "prev": prev,
        "total_tests": int(total_tests or 0),
    }
