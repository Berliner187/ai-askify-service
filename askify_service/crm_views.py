"""
API центра управления пользователями (CRM, /stats2975/crm/).

Подключение — см. urls.py (блок «CRM»). Все ответы JSON вида {"ok": true, ...} или {"ok": false, "error": "..."}.
Чтение доступно staff, всё, что меняет данные (блокировки, рассылки), — только superuser.
"""
import ipaddress
import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps

from django.db import transaction
from django.db.models import (
    Count, DecimalField, Exists, F, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value,
)
from django.db.models.functions import Coalesce, Length, TruncDate
from django.http import JsonResponse
from django.utils import timezone

from . import views as legacy
from .crm_mailing import (
    PLACEHOLDERS, SEGMENT_HINTS, SEGMENTS, active_sub_ids, as_payload, author_ids, blocked_staff_ids,
    build_message, enqueue_recipients, mailing_stats_qs, norm_uuid, payer_ids, render_mailing_html,
    segment_queryset,
)
from .models import (
    AuthUser, BlockedUsers, Mailing, MailingRecipient, Payment, Subscription, Survey,
    TestAttempt, UserIPHistory,
)
from .utils import get_client_ip

log = logging.getLogger("askify_app")
MSK = legacy.MOSCOW_TZ
GUEST_USERNAME_LEN = 50


# --------------------------------------------------------------------------- #
#  Общие помощники
# --------------------------------------------------------------------------- #
def _fail(message, status=400, **extra):
    return JsonResponse({"ok": False, "error": message, **extra}, status=status)


def _body(request):
    try:
        return json.loads(request.body or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def staff_api(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return _fail("Нет доступа. Войдите под администратором.", 403)
        return view(request, *args, **kwargs)
    return wrapper


def superuser_api(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return _fail("Действие доступно только суперпользователю.", 403)
        if request.method != "POST":
            return _fail("Только POST", 405)
        return view(request, *args, **kwargs)
    return wrapper


def _rub(kopecks):
    return round(float(kopecks or 0) / 100.0, 2)


def _msk(dt):
    return dt.astimezone(MSK) if dt else None


def _fmt(dt, pattern="%d.%m.%Y %H:%M"):
    return _msk(dt).strftime(pattern) if dt else None


def _ago(dt, now=None):
    if not dt:
        return None
    now = now or timezone.now()
    sec = (now - dt).total_seconds()
    if sec < 0:
        return "только что"
    if sec < 60:
        return "только что"
    if sec < 3600:
        return f"{int(sec // 60)} мин назад"
    if sec < 86400:
        return f"{int(sec // 3600)} ч назад"
    days = int(sec // 86400)
    if days == 1:
        return "вчера"
    if days < 31:
        return f"{days} дн назад"
    return _fmt(dt, "%d.%m.%Y")


def _until(dt, now=None):
    """Сколько осталось до момента: «2 ч 15 мин», «3 дн»."""
    if not dt:
        return "навсегда"
    now = now or timezone.now()
    sec = int((dt - now).total_seconds())
    if sec <= 0:
        return "истекла"
    if sec < 3600:
        return f"{max(1, sec // 60)} мин"
    if sec < 86400:
        h, m = sec // 3600, (sec % 3600) // 60
        return f"{h} ч {m} мин" if m else f"{h} ч"
    return f"{sec // 86400} дн"


def _ua_short(ua):
    u = (ua or "").lower()
    if not u:
        return "—"
    os_ = "iOS" if ("iphone" in u or "ipad" in u) else "Android" if "android" in u else \
        "Windows" if "windows" in u else "macOS" if "mac os" in u else "Linux" if "linux" in u else ""
    br = "Яндекс" if "yabrowser" in u else "Edge" if "edg/" in u else "Opera" if "opr/" in u else \
        "Chrome" if "chrome" in u else "Firefox" if "firefox" in u else "Safari" if "safari" in u else ""
    return " · ".join(x for x in (br, os_) if x) or ua[:40]


def _daily_series(qs, field, days, value=None):
    """Значения по дням (МСК) за последние N дней: список чисел, старые → новые."""
    today = timezone.now().astimezone(MSK).date()
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=MSK)
    rows = (
        qs.filter(**{f"{field}__gte": start_dt})
        .annotate(d=TruncDate(field, tzinfo=MSK)).values("d")
        .annotate(v=Sum(value) if value else Count("id"))
    )
    by_day = {r["d"]: r["v"] or 0 for r in rows}
    labels, values = [], []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        v = by_day.get(d, 0)
        values.append(_rub(v) if value else int(v))
    return labels, values


def _pct(new, old):
    if not old:
        return None if not new else 100.0
    return round((new - old) / old * 100.0, 1)


# --------------------------------------------------------------------------- #
#  Обзор
# --------------------------------------------------------------------------- #
@staff_api
def crm_overview_api(request):
    now = timezone.now()
    today = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    real_users = AuthUser.objects.annotate(
        _ulen=Length("username")
    ).filter(
        _ulen__lte=GUEST_USERNAME_LEN,
        is_staff=False
    ).exclude(
        username__startswith="guest_"
    )
    paid = Payment.objects.filter(status="completed")

    new_today = real_users.filter(date_joined__gte=today).count()
    new_7 = real_users.filter(date_joined__gte=now - timedelta(days=7)).count()
    new_prev_7 = real_users.filter(date_joined__gte=now - timedelta(days=14), date_joined__lt=now - timedelta(days=7)).count()
    rev_30 = paid.filter(created_at__gte=now - timedelta(days=30)).aggregate(s=Sum("amount"))["s"] or 0
    rev_prev_30 = paid.filter(created_at__gte=now - timedelta(days=60), created_at__lt=now - timedelta(days=30)).aggregate(s=Sum("amount"))["s"] or 0
    rev_all = paid.aggregate(s=Sum("amount"))["s"] or 0
    payers = paid.values("staff_id").distinct().count()
    users_total = real_users.count()
    repeat_payers = paid.values("staff_id").annotate(c=Count("id")).filter(c__gte=2).count()

    # Топ по LTV
    top_rows = list(paid.values("staff_id").annotate(s=Sum("amount"), c=Count("id"), last=Max("created_at")).order_by("-s")[:8])
    users_map = {u.id_staff: u for u in AuthUser.objects.filter(
        id_staff__in=[x for x in (norm_uuid(r["staff_id"]) for r in top_rows) if x])}
    top_ltv = []
    for r in top_rows:
        u = users_map.get(norm_uuid(r["staff_id"]))
        if not u:
            continue
        top_ltv.append({
            "id": u.id, "username": u.username, "email": u.email or "",
            "ltv": _rub(r["s"]), "payments": r["c"], "last_payment": _ago(r["last"], now),
        })

    # Последние оплаты
    recent = list(paid.order_by("-created_at").select_related("subscription")[:8])
    pay_users = {u.id_staff: u for u in AuthUser.objects.filter(
        id_staff__in=[x for x in (norm_uuid(p.staff_id) for p in recent) if x])}
    recent_payments = []
    for p in recent:
        u = pay_users.get(norm_uuid(p.staff_id))
        recent_payments.append({
            "user_id": u.id if u else None,
            "username": u.username if u else "удалён",
            "amount": _rub(p.amount),
            "plan": legacy._pulse_plan_label(p.subscription.plan_name if p.subscription_id else ""),
            "ago": _ago(p.created_at, now),
            "date": _fmt(p.created_at),
        })

    reg_labels, reg_values = _daily_series(real_users, "date_joined", 14)
    _, rev_values = _daily_series(paid, "created_at", 14, value="amount")

    active_subs = Subscription.objects.filter(status="active", end_date__gt=now).count()
    expiring = Subscription.objects.filter(status="active", end_date__gt=now, end_date__lte=now + timedelta(days=7)).count()

    activated_7 = real_users.filter(date_joined__gte=now - timedelta(days=7)).filter(
        id_staff__in=author_ids()).count()

    return JsonResponse({
        "ok": True,
        "generated_at": _fmt(now, "%H:%M"),
        "kpi": {
            "users_total": users_total,
            "new_today": new_today,
            "new_7d": new_7,
            "new_7d_delta": _pct(new_7, new_prev_7),
            "activated_7d": activated_7,
            "revenue_30d": _rub(rev_30),
            "revenue_30d_delta": _pct(float(rev_30), float(rev_prev_30)),
            "revenue_all": _rub(rev_all),
            "payers": payers,
            "repeat_payers": repeat_payers,
            "conversion": round(payers / users_total * 100, 2) if users_total else 0,
            "avg_ltv": round(_rub(rev_all) / payers, 2) if payers else 0,
            "active_subs": active_subs,
            "expiring_7d": expiring,
            "blocked_active": BlockedUsers.objects.count(),
            "mail_reachable": segment_queryset("all").count(),
        },
        "series": {"labels": reg_labels, "registrations": reg_values, "revenue": rev_values},
        "top_ltv": top_ltv,
        "recent_payments": recent_payments,
    })


# --------------------------------------------------------------------------- #
#  Пользователи
# --------------------------------------------------------------------------- #
USER_SEGMENTS = [
    ("all", "Все"),
    ("new_7d", "Новые 7 дн"),
    ("paying", "Платящие"),
    ("active_subs", "С подпиской"),
    ("has_balance", "С балансом"),
    ("no_tests", "0 тестов"),
    ("dormant_30d", "Спящие 30 дн"),
    ("blocked", "Заблокированы"),
    ("staff", "Команда"),
]
USER_SORTS = {
    "joined": ("-date_joined",),
    "ltv": ("-revenue", "-date_joined"),
    "tests": ("-tests_cnt", "-date_joined"),
    "login": (F("last_login").desc(nulls_last=True),),
    "balance": ("-test_balance", "-date_joined"),
}


def _users_segment(qs, seg, now):
    if seg == "new_7d":
        return qs.filter(date_joined__gte=now - timedelta(days=7))
    if seg == "paying":
        return qs.filter(id_staff__in=payer_ids())
    if seg == "active_subs":
        return qs.filter(id_staff__in=active_sub_ids())
    if seg == "has_balance":
        return qs.filter(test_balance__gt=0)
    if seg == "no_tests":
        return qs.exclude(id_staff__in=author_ids())
    if seg == "dormant_30d":
        edge = now - timedelta(days=30)
        return qs.filter(Q(last_login__lt=edge) | Q(last_login__isnull=True, date_joined__lt=edge))
    if seg == "blocked":
        return qs.filter(id_staff__in=blocked_staff_ids())
    if seg == "staff":
        return qs.filter(Q(is_staff=True) | Q(is_superuser=True))
    return qs


def _users_search(qs, q):
    q = (q or "").strip()
    if not q:
        return qs
    if q.startswith("#") and q[1:].isdigit():
        return qs.filter(id=int(q[1:]))
    try:
        ipaddress.ip_address(q)
        ids = list(UserIPHistory.objects.filter(ip_address=q).values_list("user_id", flat=True))
        staff = [x for x in (norm_uuid(v) for v in BlockedUsers.all_objects.filter(ip_address=q)
                             .values_list("id_staff", flat=True)) if x]
        return qs.filter(Q(id__in=ids) | Q(id_staff__in=staff))
    except ValueError:
        pass
    cond = Q(username__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
    as_uuid = norm_uuid(q)
    if as_uuid:
        cond |= Q(id_staff=as_uuid)
    if q.isdigit():
        cond |= Q(id=int(q))
    return qs.filter(cond)


def _money_maps():
    """LTV и число оплат по staff_id — один агрегирующий запрос, ключи нормализованы в UUID."""
    rev, cnt = {}, {}
    for row in (Payment.objects.filter(status="completed").order_by()
                .values("staff_id").annotate(s=Sum("amount"), c=Count("id"))):
        k = norm_uuid(row["staff_id"])
        if k:
            rev[k] = rev.get(k, 0) + float(row["s"] or 0)
            cnt[k] = cnt.get(k, 0) + row["c"]
    return rev, cnt


def _tests_map(staff_ids=None):
    qs = Survey.objects.order_by()
    if staff_ids is not None:
        qs = qs.filter(id_staff__in=staff_ids)
    out = {}
    for row in qs.values("id_staff").annotate(c=Count("id"), last=Max("created_at")):
        k = norm_uuid(row["id_staff"])
        if k:
            prev = out.get(k)
            out[k] = (row["c"] + (prev[0] if prev else 0), max(filter(None, [row["last"], prev[1] if prev else None]), default=None))
    return out


@staff_api
def crm_users_api(request):
    now = timezone.now()
    seg = request.GET.get("segment", "all")
    sort = request.GET.get("sort", "joined")
    q = request.GET.get("q", "")
    show_guests = request.GET.get("guests") == "1"
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    page_size = 30

    base = AuthUser.objects.all()
    if not show_guests:
        base = base.annotate(_ulen=Length("username")).filter(_ulen__lte=GUEST_USERNAME_LEN)
    qs = _users_search(_users_segment(base, seg, now), q)

    rev_map, cnt_map = _money_maps()
    total = qs.count()
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    lo, hi = (page - 1) * page_size, page * page_size

    if sort in ("ltv", "tests"):
        # сортировка по вычисляемым метрикам — в Python (пользователей тысячи, это быстро)
        pairs = list(qs.values_list("id", "id_staff", "date_joined"))
        if sort == "ltv":
            key = lambda r: (rev_map.get(norm_uuid(r[1]), 0), r[2])
        else:
            tmap_all = _tests_map()
            key = lambda r: ((tmap_all.get(norm_uuid(r[1])) or (0, None))[0], r[2])
        pairs.sort(key=key, reverse=True)
        page_ids = [r[0] for r in pairs[lo:hi]]
        by_id = {u.id: u for u in AuthUser.objects.filter(id__in=page_ids)}
        users = [by_id[i] for i in page_ids if i in by_id]
    else:
        order = {
            "joined": ("-date_joined",),
            "login": (F("last_login").desc(nulls_last=True),),
            "balance": ("-test_balance", "-date_joined"),
        }.get(sort, ("-date_joined",))
        users = list(qs.order_by(*order)[lo:hi])

    staff_ids = [u.id_staff for u in users]
    tmap = _tests_map(staff_ids)
    subs = {}
    for sb in Subscription.objects.filter(staff_id__in=staff_ids):
        subs[norm_uuid(sb.staff_id)] = sb
    blocked = set(blocked_staff_ids())
    last_ip = {}
    for uid, ip in (UserIPHistory.objects.filter(user_id__in=[u.id for u in users])
                    .order_by("user_id", "-last_seen").values_list("user_id", "ip_address")):
        last_ip.setdefault(uid, ip)

    items = []
    for u in users:
        k = u.id_staff
        sb = subs.get(k)
        sub_active = bool(sb and sb.end_date and sb.end_date > now)
        tests_cnt, last_test = tmap.get(k, (0, None))
        items.append({
            "id": u.id,
            "username": u.username,
            "email": u.email or "",
            "id_staff": str(u.id_staff),
            "joined": _fmt(u.date_joined, "%d.%m.%Y"),
            "joined_ago": _ago(u.date_joined, now),
            "last_login_ago": _ago(u.last_login, now),
            "last_test_ago": _ago(last_test, now),
            "ltv": _rub(rev_map.get(k, 0)),
            "payments": cnt_map.get(k, 0),
            "tests": tests_cnt,
            "balance": u.test_balance,
            "plan": (sb.plan_name or "") if sub_active else "",
            "sub_active": sub_active,
            "sub_end": _fmt(sb.end_date, "%d.%m.%Y") if sub_active else None,
            "is_blocked": k in blocked,
            "is_staff": u.is_staff or u.is_superuser,
            "is_subscribed": u.is_subscribed,
            "last_ip": last_ip.get(u.id),
        })

    payload = {"ok": True, "total": total, "page": page, "pages": pages, "page_size": page_size, "items": items}
    if request.GET.get("counts") == "1":
        payload["segments"] = [
            {"code": code, "label": label, "count": _users_search(_users_segment(base, code, now), q).count()}
            for code, label in USER_SEGMENTS
        ]
    return JsonResponse(payload)


def _blocks_for(user, ips):
    """Блокировки пользователя: по его IP или по привязке id_staff. Таблица маленькая — фильтруем в Python."""
    ips = set(ips)
    return [b for b in BlockedUsers.all_objects.all()
            if b.ip_address in ips or (b.id_staff and norm_uuid(b.id_staff) == user.id_staff)]


def _user_ips_payload(user, now=None):
    now = now or timezone.now()
    hist = list(UserIPHistory.objects.filter(user=user)[:25])
    ips = [h.ip_address for h in hist]
    blocks = {b.ip_address: b for b in _blocks_for(user, ips)}
    shared = dict(
        UserIPHistory.objects.filter(ip_address__in=ips).exclude(user=user)
        .values("ip_address").annotate(c=Count("user", distinct=True)).values_list("ip_address", "c")
    )
    known = []
    for h in hist:
        b = blocks.get(h.ip_address)
        known.append({
            "ip": h.ip_address,
            "first_seen": _fmt(h.first_seen, "%d.%m.%Y"),
            "last_seen": _ago(h.last_seen, now),
            "hits": h.hits,
            "device": _ua_short(h.user_agent),
            "shared_with": shared.get(h.ip_address, 0),
            "blocked": bool(b and b.is_active),
            "blocked_left": _until(b.expires_at, now) if b and b.is_active else None,
        })
    block_rows = []
    for b in sorted(blocks.values(), key=lambda x: x.created_at, reverse=True):
        if b.id_staff and norm_uuid(b.id_staff) != user.id_staff and b.ip_address not in ips:
            continue
        block_rows.append({
            "id": b.id, "ip": b.ip_address, "active": b.is_active,
            "reason": b.reason or "", "created": _fmt(b.created_at),
            "expires": _fmt(b.expires_at) if b.expires_at else None,
            "left": _until(b.expires_at, now) if b.is_active else "истекла",
            "created_by": b.created_by,
        })
    return {"known_ips": known, "blocks": block_rows, "is_blocked": any(r["active"] for r in block_rows)}


@staff_api
def crm_user_ips_api(request, user_id):
    user = AuthUser.objects.filter(id=user_id).first()
    if not user:
        return _fail("Пользователь не найден", 404)
    return JsonResponse({"ok": True, "user": {"id": user.id, "username": user.username, "email": user.email or "",
                                               "is_staff": user.is_staff or user.is_superuser},
                         **_user_ips_payload(user)})


@staff_api
def crm_user_details_api(request, user_id):
    """Досье = существующий get_user_details_api + IP, блокировки и метрики активности."""
    resp = legacy.get_user_details_api(request, user_id)
    if resp.status_code != 200:
        return resp
    data = json.loads(resp.content)
    user = AuthUser.objects.get(id=user_id)
    now = timezone.now()

    surveys = Survey.objects.filter(id_staff=user.id_staff)
    payments = Payment.objects.filter(staff_id=user.id_staff)
    paid = payments.filter(status="completed")
    first_pay = paid.order_by("created_at").values_list("created_at", flat=True).first()
    last_test = surveys.order_by("-created_at").values_list("created_at", flat=True).first()
    rev_30 = paid.filter(created_at__gte=now - timedelta(days=30)).aggregate(s=Sum("amount"))["s"] or 0
    months_alive = max(1.0, (now - user.date_joined).days / 30.0)
    tests_total = data.get("badges", {}).get("surveys_created", 0) or 0

    data["ok"] = True
    data["is_superuser"] = user.is_superuser
    data["activity"] = {
        **data.get("activity", {}),
        "tests_7d": surveys.filter(created_at__gte=now - timedelta(days=7)).count(),
        "tests_30d": surveys.filter(created_at__gte=now - timedelta(days=30)).count(),
        "tests_per_month": round(tests_total / months_alive, 1),
        "last_test_ago": _ago(last_test, now),
        "last_login_ago": _ago(user.last_login, now),
        "joined_ago": _ago(user.date_joined, now),
        "students_7d": TestAttempt.objects.filter(survey__id_staff=user.id_staff, created_at__gte=now - timedelta(days=7)).count(),
    }
    data["money"] = {
        "revenue_30d": _rub(rev_30),
        "pending": payments.filter(status="pending").count(),
        "failed": payments.filter(status="failed").count(),
        "days_to_first_payment": (first_pay - user.date_joined).days if first_pay else None,
        "monthly_value": round(_rub(paid.aggregate(s=Sum("amount"))["s"] or 0) / months_alive, 2),
    }
    data.update(_user_ips_payload(user, now))
    return JsonResponse(data)


# --------------------------------------------------------------------------- #
#  Блокировки по IP
# --------------------------------------------------------------------------- #
MAX_BLOCK_HOURS = 24 * 3650


def _parse_ips(raw):
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[\s,;]+", str(raw or ""))
    valid, invalid = [], []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            ip = str(ipaddress.ip_address(p))
            if ip not in valid:
                valid.append(ip)
        except ValueError:
            invalid.append(p)
    return valid, invalid


@superuser_api
def crm_block_api(request):
    data = _body(request)
    ips, invalid = _parse_ips(data.get("ips"))
    if invalid:
        return _fail(f"Не похоже на IP: {', '.join(invalid[:5])}", invalid=invalid)
    if not ips:
        return _fail("Укажите хотя бы один IP-адрес.")
    if len(ips) > 50:
        return _fail("За раз можно заблокировать не больше 50 адресов.")

    hours = data.get("hours")
    if hours in (None, "", "forever", 0, "0"):
        expires_at = None
    else:
        try:
            hours = int(hours)
        except (TypeError, ValueError):
            return _fail("Срок блокировки указан неверно.")
        if hours <= 0 or hours > MAX_BLOCK_HOURS:
            return _fail("Срок должен быть от 1 часа до 10 лет.")
        expires_at = timezone.now() + timedelta(hours=hours)

    user = None
    if data.get("user_id"):
        user = AuthUser.objects.filter(id=data.get("user_id")).first()
        if not user:
            return _fail("Пользователь не найден", 404)
        if user.is_staff or user.is_superuser:
            return _fail("Нельзя заблокировать администратора.")

    own_ip = get_client_ip(request)
    if own_ip in ips:
        return _fail(f"{own_ip} — ваш текущий IP. Так вы закроете доступ себе.")
    team_ips = set(UserIPHistory.objects.filter(ip_address__in=ips)
                   .filter(Q(user__is_staff=True) | Q(user__is_superuser=True))
                   .values_list("ip_address", flat=True))
    if team_ips and not data.get("force"):
        return _fail(f"С этих адресов заходила команда: {', '.join(sorted(team_ips))}. Уберите их из списка.",
                     team_ips=sorted(team_ips))
    if any(ipaddress.ip_address(ip).is_loopback for ip in ips):
        return _fail("Локальный адрес (127.0.0.1 / ::1) блокировать нельзя.")

    reason = (data.get("reason") or "").strip()[:500] or "Блокировка из CRM"
    now = timezone.now()
    with transaction.atomic():
        for ip in ips:
            BlockedUsers.all_objects.update_or_create(
                ip_address=ip,
                defaults={
                    "id_staff": user.id_staff if user else None,
                    "reason": reason,
                    "expires_at": expires_at,
                    "created_by": request.user.username,
                    "created_at": now,
                },
            )
    log.warning(f"CRM BLOCK: {request.user.username} → {', '.join(ips)} "
                f"({'навсегда' if not expires_at else 'до ' + _fmt(expires_at)})"
                f"{' user=' + user.username if user else ''}: {reason}")
    until = "навсегда" if not expires_at else f"до {_fmt(expires_at)}"
    who = f"«{user.username}» " if user else ""
    return JsonResponse({
        "ok": True, "blocked": ips, "expires_at": _fmt(expires_at) if expires_at else None,
        "message": f"{who}заблокирован по {len(ips)} IP {until}".strip().capitalize(),
    })


@superuser_api
def crm_unblock_api(request):
    data = _body(request)
    action = data.get("action", "unblock")
    qs = BlockedUsers.all_objects.none()
    if data.get("id"):
        qs = BlockedUsers.all_objects.filter(id=data["id"])
    elif data.get("ip"):
        qs = BlockedUsers.all_objects.filter(ip_address=str(data["ip"]).strip())
    elif data.get("user_id"):
        u = AuthUser.objects.filter(id=data["user_id"]).first()
        if u:
            ips = list(UserIPHistory.objects.filter(user=u).values_list("ip_address", flat=True))
            qs = BlockedUsers.all_objects.filter(id__in=[b.id for b in _blocks_for(u, ips)])
    if not qs.exists():
        return _fail("Блокировка не найдена", 404)

    now = timezone.now()
    if action == "delete":
        n = qs.count()
        qs.delete()
        return JsonResponse({"ok": True, "message": f"Удалено записей: {n}"})
    if action == "extend":
        try:
            hours = int(data.get("hours") or 24)
        except (TypeError, ValueError):
            return _fail("Срок указан неверно.")
        for b in qs:
            base = b.expires_at if b.expires_at and b.expires_at > now else now
            b.expires_at = base + timedelta(hours=max(1, min(hours, MAX_BLOCK_HOURS)))
            b.save(update_fields=["expires_at"])
        return JsonResponse({"ok": True, "message": "Срок блокировки продлён"})
    n = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).update(expires_at=now)
    log.warning(f"CRM UNBLOCK: {request.user.username} снял {n} блокировок")
    return JsonResponse({"ok": True, "message": "Блокировка снята" if n == 1 else f"Снято блокировок: {n}"})


@staff_api
def crm_blocks_api(request):
    BlockedUsers.purge_expired(older_than_days=30)
    now = timezone.now()
    rows = list(BlockedUsers.all_objects.order_by("-created_at")[:400])
    users = {u.id_staff: u for u in AuthUser.objects.filter(
        id_staff__in=[x for x in (norm_uuid(r.id_staff) for r in rows) if x])}
    ip_users = {}
    for ip, uid, uname in UserIPHistory.objects.filter(ip_address__in=[r.ip_address for r in rows]).values_list(
            "ip_address", "user_id", "user__username"):
        ip_users.setdefault(ip, []).append({"id": uid, "username": uname})
    q = (request.GET.get("q") or "").strip().lower()
    items = []
    for b in rows:
        u = users.get(norm_uuid(b.id_staff))
        linked = [{"id": u.id, "username": u.username}] if u else ip_users.get(b.ip_address, [])[:3]
        item = {
            "id": b.id, "ip": b.ip_address, "active": b.is_active, "forever": b.expires_at is None,
            "users": linked, "reason": b.reason or "", "created": _fmt(b.created_at), "created_ago": _ago(b.created_at, now),
            "expires": _fmt(b.expires_at) if b.expires_at else None,
            "left": _until(b.expires_at, now) if b.is_active else "истекла",
            "created_by": b.created_by or "—",
        }
        if q and q not in (b.ip_address + " " + " ".join(x["username"] for x in linked) + " " + (b.reason or "")).lower():
            continue
        items.append(item)
    active = [i for i in items if i["active"]]
    return JsonResponse({
        "ok": True,
        "items": items,
        "stats": {
            "active": len(active),
            "forever": sum(1 for i in active if i["forever"]),
            "temporary": sum(1 for i in active if not i["forever"]),
            "expired": len(items) - len(active),
        },
    })


# --------------------------------------------------------------------------- #
#  Рассылки
# --------------------------------------------------------------------------- #
@staff_api
def crm_mailing_segments_api(request):
    return JsonResponse({
        "ok": True,
        "segments": [
            {"code": code, "label": label, "hint": SEGMENT_HINTS.get(code, ""), "count": segment_queryset(code).count()}
            for code, label in Mailing.SEGMENT_CHOICES
        ],
        "placeholders": [{"token": k, "label": v} for k, v in PLACEHOLDERS.items()],
    })


def _validate_mail_form(data):
    p = as_payload(data)
    if not p.subject:
        return None, "Укажите тему письма."
    if len(p.subject) > 255:
        return None, "Тема длиннее 255 символов."
    if not p.message_body:
        return None, "Напишите текст письма."
    if bool(p.button_text) != bool(p.button_url):
        return None, "Для кнопки нужны и текст, и ссылка."
    if p.button_url and not re.match(r"^https?://", p.button_url, re.I):
        return None, "Ссылка кнопки должна начинаться с http:// или https://"
    return p, None


@staff_api
def crm_mailing_render_api(request):
    """Предпросмотр письма ровно так, как его увидит получатель (на примере текущего админа)."""
    p, err = _validate_mail_form({**_body(request), "subject": _body(request).get("subject") or "Тема письма",
                                  "message_body": _body(request).get("message_body") or "Текст письма"})
    if err:
        return _fail(err)
    return JsonResponse({"ok": True, "html": render_mailing_html(p, request.user)})


@superuser_api
def crm_mailing_test_api(request):
    data = _body(request)
    p, err = _validate_mail_form(data)
    if err:
        return _fail(err)
    to = (data.get("email") or request.user.email or "").strip()
    if "@" not in to:
        return _fail("У вашего аккаунта нет почты — укажите адрес для теста.")
    try:
        msg = build_message(p, request.user, to_email=to)
        msg.subject = f"[ТЕСТ] {msg.subject}"
        msg.send()
    except Exception as e:
        log.error(f"CRM MAIL TEST FAIL: {e}")
        return _fail(f"Письмо не ушло: {e}", 502)
    return JsonResponse({"ok": True, "message": f"Тестовое письмо отправлено на {to}"})


@superuser_api
def crm_mailing_start_api(request):
    data = _body(request)
    p, err = _validate_mail_form(data)
    if err:
        return _fail(err)
    segment = data.get("target_segment") or "all"
    if segment not in SEGMENTS:
        return _fail("Неизвестный сегмент.")

    scheduled_at = None
    if data.get("scheduled_at"):
        try:
            scheduled_at = datetime.fromisoformat(str(data["scheduled_at"])).replace(tzinfo=MSK)
        except ValueError:
            return _fail("Дата отправки указана неверно.")
        if scheduled_at < timezone.now() + timedelta(minutes=1):
            return _fail("Время отправки уже прошло. Выберите момент в будущем.")

    dup = Mailing.objects.filter(
        subject=p.subject, target_segment=segment, created_at__gte=timezone.now() - timedelta(minutes=10),
    ).exclude(status__in=["canceled", "failed"]).first()
    if dup and not data.get("force"):
        return _fail(f"Такая же рассылка уже запущена {_ago(dup.created_at)} (#{dup.id}). Это дубль?",
                     duplicate_id=dup.id, code="duplicate")

    with transaction.atomic():
        mailing = Mailing.objects.create(
            title=(data.get("title") or "").strip()[:255] or p.subject[:255],
            subject=p.subject, preheader=p.preheader[:255], message_body=p.message_body,
            button_text=p.button_text or None, button_url=p.button_url or None,
            target_segment=segment, created_by=request.user.username,
            scheduled_at=scheduled_at, status="scheduled" if scheduled_at else "queued",
        )
        total = enqueue_recipients(mailing, segment)
        if not total:
            transaction.set_rollback(True)
            return _fail("В этом сегменте сейчас никого нет — отправлять некому.")
        mailing.total_recipients = total
        mailing.save(update_fields=["total_recipients"])

    from .crm_tasks import crm_dispatch_mailing
    try:
        if scheduled_at:
            crm_dispatch_mailing.apply_async((mailing.id,), eta=scheduled_at)
        else:
            crm_dispatch_mailing.delay(mailing.id)
    except Exception as e:
        Mailing.objects.filter(id=mailing.id).update(status="paused", last_error=f"Celery недоступен: {e}"[:1000])
        return _fail(f"Получатели сохранены, но очередь Celery недоступна: {e}. "
                     f"Рассылка #{mailing.id} на паузе — нажмите «Продолжить», когда брокер оживёт.", 503,
                     mailing_id=mailing.id)

    when = f"Отправка {_fmt(scheduled_at)} по Москве" if scheduled_at else "Отправка началась"
    return JsonResponse({"ok": True, "mailing_id": mailing.id, "total": total,
                         "message": f"{when}: {total} получателей."})


def _mailing_row(m, now):
    total = m.n_total or m.total_recipients or 0
    done = m.n_sent + m.n_failed
    elapsed = (now - m.sent_at).total_seconds() if m.sent_at else 0
    end = m.finished_at or now
    rate = (m.n_sent / max(1.0, ((end - m.sent_at).total_seconds() / 60.0))) if m.sent_at and m.n_sent else 0
    eta = None
    if m.status == "processing" and rate > 0 and m.n_pending:
        eta = int(m.n_pending / rate) + 1
    return {
        "id": m.id, "title": m.title, "subject": m.subject,
        "segment": m.target_segment, "segment_label": SEGMENTS.get(m.target_segment, m.target_segment),
        "status": m.status, "status_label": m.get_status_display(),
        "created": _fmt(m.created_at), "created_ago": _ago(m.created_at, now), "created_by": m.created_by,
        "scheduled": _fmt(m.scheduled_at) if m.scheduled_at else None,
        "started": _fmt(m.sent_at) if m.sent_at else None,
        "finished": _fmt(m.finished_at) if m.finished_at else None,
        "duration_min": round(((end - m.sent_at).total_seconds()) / 60, 1) if m.sent_at else None,
        "stats": {"total": total, "sent": m.n_sent, "failed": m.n_failed, "pending": m.n_pending,
                  "progress": round(done / total * 100, 1) if total else 0,
                  "delivery": round(m.n_sent / done * 100, 1) if done else None},
        "rate_per_min": round(rate, 1), "eta_min": eta, "elapsed_min": round(elapsed / 60, 1) if elapsed else 0,
        "last_error": m.last_error or "",
    }


@staff_api
def crm_mailing_history_api(request):
    now = timezone.now()
    rows = [_mailing_row(m, now) for m in mailing_stats_qs().order_by("-created_at")[:40]]
    today = now.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = MailingRecipient.objects.filter(status="sent", sent_at__gte=today).count()
    failed_today = MailingRecipient.objects.filter(status="failed", mailing__sent_at__gte=today).count()
    return JsonResponse({
        "ok": True,
        "history": rows,
        "summary": {
            "sent_today": sent_today, "failed_today": failed_today,
            "running": sum(1 for r in rows if r["status"] in ("queued", "processing")),
            "scheduled": sum(1 for r in rows if r["status"] == "scheduled"),
        },
    })


@staff_api
def crm_mailing_detail_api(request, mailing_id):
    m = mailing_stats_qs().filter(id=mailing_id).first()
    if not m:
        return _fail("Рассылка не найдена", 404)
    now = timezone.now()
    failed = list(m.recipients.filter(status="failed").select_related("user").order_by("-id")[:100])
    errors = (m.recipients.filter(status="failed").values("error_message")
              .annotate(c=Count("id")).order_by("-c")[:6])
    return JsonResponse({
        "ok": True,
        "mailing": {
            **_mailing_row(m, now),
            "preheader": m.preheader, "message_body": m.message_body,
            "button_text": m.button_text or "", "button_url": m.button_url or "",
        },
        "error_groups": [{"error": (e["error_message"] or "—")[:200], "count": e["c"]} for e in errors],
        "failed": [{"user_id": r.user_id, "username": r.user.username, "email": r.email or r.user.email,
                    "error": (r.error_message or "")[:300], "attempts": r.attempts} for r in failed],
    })


@superuser_api
def crm_mailing_control_api(request, mailing_id):
    action = _body(request).get("action")
    m = Mailing.objects.filter(id=mailing_id).first()
    if not m:
        return _fail("Рассылка не найдена", 404)
    from .crm_tasks import crm_dispatch_mailing, finalize_mailing

    if action == "pause":
        if m.status not in ("queued", "processing", "scheduled"):
            return _fail("Поставить на паузу можно только активную рассылку.")
        m.status = "paused"
        m.save(update_fields=["status"])
        return JsonResponse({"ok": True, "message": f"Рассылка #{m.id} на паузе"})

    if action == "resume":
        if m.status not in ("paused", "failed"):
            return _fail("Продолжить можно только рассылку на паузе.")
        m.status = "queued"
        m.save(update_fields=["status"])
        try:
            crm_dispatch_mailing.delay(m.id)
        except Exception as e:
            Mailing.objects.filter(id=m.id).update(status="paused")
            return _fail(f"Celery недоступен: {e}", 503)
        return JsonResponse({"ok": True, "message": f"Рассылка #{m.id} продолжается"})

    if action == "cancel":
        if m.status in ("completed", "canceled"):
            return _fail("Рассылка уже завершена.")
        m.status = "canceled"
        m.finished_at = timezone.now()
        m.save(update_fields=["status", "finished_at"])
        left = m.recipients.filter(status="pending").update(status="failed", error_message="Рассылка отменена")
        return JsonResponse({"ok": True, "message": f"Рассылка #{m.id} отменена, не отправлено: {left}"})

    if action == "retry_failed":
        n = m.recipients.filter(status="failed").exclude(error_message__startswith="Пропущен").update(
            status="pending", error_message=None, attempts=0)
        if not n:
            return _fail("Повторять нечего: ошибок доставки нет.")
        m.status, m.finished_at = "queued", None
        m.save(update_fields=["status", "finished_at"])
        try:
            crm_dispatch_mailing.delay(m.id)
        except Exception as e:
            Mailing.objects.filter(id=m.id).update(status="paused")
            return _fail(f"Celery недоступен: {e}", 503)
        return JsonResponse({"ok": True, "message": f"Повторная отправка {n} писем поставлена в очередь"})

    if action == "send_now" and m.status == "scheduled":
        m.status, m.scheduled_at = "queued", None
        m.save(update_fields=["status", "scheduled_at"])
        crm_dispatch_mailing.delay(m.id)
        return JsonResponse({"ok": True, "message": f"Рассылка #{m.id} отправляется сейчас"})

    if action == "finalize":
        finalize_mailing(m.id)
        return JsonResponse({"ok": True})

    return _fail("Неизвестное действие.")