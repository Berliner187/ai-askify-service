"""
Сервис email-рассылок CRM.

Здесь только чистая логика без HTTP:
  * segment_queryset()   — кто попадает в сегмент (только подписанные, с email, не заблокированные, не гости);
  * build_message()      — готовое письмо (HTML + текст + заголовок отписки) для конкретного пользователя;
  * mailing_stats()      — сводка по рассылке одним запросом.

Используется в crm_views.py (запуск, тест, предпросмотр) и crm_tasks.py (отправка в Celery).
"""
import html as html_lib
import re
import uuid
from types import SimpleNamespace
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.signing import Signer
from django.db.models import Count, Q
from django.db.models.functions import Length
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .models import (
    AuthUser, BlockedUsers, Mailing, MailingRecipient, Payment, Subscription, Survey,
)

SITE_URL = getattr(settings, "SITE_URL", "https://letychka.ru").rstrip("/")
SEGMENTS = dict(Mailing.SEGMENT_CHOICES)

# Подсказки для UI: что значит каждый сегмент
SEGMENT_HINTS = {
    "all": "Все, у кого есть почта и кто не отписался",
    "active_subs": "Подписка действует прямо сейчас",
    "inactive_subs": "Подписки нет или она закончилась",
    "no_tests": "Зарегистрировались, но не создали ни одного теста",
    "paying": "Хотя бы одна успешная оплата",
    "never_paid": "Ни одной успешной оплаты",
    "new_7d": "Регистрация за последние 7 дней",
    "dormant_30d": "Последний вход больше 30 дней назад",
    "expiring_7d": "Подписка закончится в ближайшую неделю",
    "has_balance": "На балансе остались пакетные тесты",
}

PLACEHOLDERS = {
    "{name}": "имя пользователя (username)",
    "{email}": "почта",
    "{balance}": "тестов на балансе",
}


def norm_uuid(v):
    """id_staff/staff_id в старых таблицах (перенос из SQLite) может лежать строкой.
    Приводим к UUID, чтобы сравнивать в Python, а не в SQL (uuid = text в Postgres не работает)."""
    if not v:
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v).strip())
    except (ValueError, AttributeError):
        return None


def id_list(qs, field):
    """Список уникальных UUID из колонки — подставляется в __in как параметры, а не подзапрос."""
    out = set()
    for v in qs.order_by().values_list(field, flat=True).distinct():
        u = norm_uuid(v)
        if u:
            out.add(u)
    return list(out)


def blocked_staff_ids():
    return id_list(BlockedUsers.objects.exclude(id_staff=None), "id_staff")


def payer_ids():
    return id_list(Payment.objects.filter(status="completed"), "staff_id")


def active_sub_ids(until=None):
    now = timezone.now()
    qs = Subscription.objects.filter(status="active", end_date__gt=now)
    if until:
        qs = qs.filter(end_date__lte=until)
    return id_list(qs, "staff_id")


def author_ids():
    return id_list(Survey.objects.all(), "id_staff")


def segment_queryset(segment):
    """Пользователи сегмента, которым МОЖНО писать."""
    now = timezone.now()
    qs = (
        AuthUser.objects.filter(is_active=True, is_subscribed=True, email__contains="@")
        .annotate(_ulen=Length("username"))
        .filter(_ulen__lte=50)
        .exclude(username__startswith="guest_")
    )
    blocked = blocked_staff_ids()
    if blocked:
        qs = qs.exclude(id_staff__in=blocked)

    if segment == "active_subs":
        qs = qs.filter(id_staff__in=active_sub_ids())
    elif segment == "inactive_subs":
        qs = qs.exclude(id_staff__in=active_sub_ids())
    elif segment == "no_tests":
        qs = qs.exclude(id_staff__in=author_ids())
    elif segment == "paying":
        qs = qs.filter(id_staff__in=payer_ids())
    elif segment == "never_paid":
        qs = qs.exclude(id_staff__in=payer_ids())
    elif segment == "new_7d":
        qs = qs.filter(date_joined__gte=now - timedelta(days=7))
    elif segment == "dormant_30d":
        edge = now - timedelta(days=30)
        qs = qs.filter(Q(last_login__lt=edge) | Q(last_login__isnull=True, date_joined__lt=edge))
    elif segment == "expiring_7d":
        qs = qs.filter(id_staff__in=active_sub_ids(until=now + timedelta(days=7)))
    elif segment == "has_balance":
        qs = qs.filter(test_balance__gt=0)
    return qs


def unsubscribe_url(user):
    token = Signer().sign(str(user.pk))
    try:
        path = reverse("unsubscribe", args=[token])
    except Exception:
        path = f"/unsubscribe/{token}/"
    return f"{SITE_URL}{path}"


def _personalize(text, user):
    if not text:
        return text
    name = html_lib.escape(user.username or "") if user else ""
    return (
        text.replace("{name}", name or "друг")
        .replace("{email}", html_lib.escape(user.email or "") if user else "")
        .replace("{balance}", str(getattr(user, "test_balance", 0) or 0))
    )


def _looks_like_html(text):
    return bool(re.search(r"<(p|br|div|h[1-6]|ul|ol|li|a|b|strong|table|img)\b", text or "", re.I))


def body_to_html(text):
    """Админ может написать HTML или обычный текст с переносами — оба варианта корректны."""
    if _looks_like_html(text):
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(
        f'<p style="margin:0 0 16px">{html_lib.escape(p).replace(chr(10), "<br>")}</p>' for p in paragraphs
    )


def as_payload(data):
    """Словарь из формы → объект с теми же полями, что у Mailing (для теста и предпросмотра)."""
    return SimpleNamespace(
        subject=(data.get("subject") or "").strip(),
        preheader=(data.get("preheader") or "").strip(),
        message_body=(data.get("message_body") or "").strip(),
        button_text=(data.get("button_text") or "").strip(),
        button_url=(data.get("button_url") or "").strip(),
    )


def render_mailing_html(mailing, user):
    ctx = {
        "subject": _personalize(mailing.subject, user),
        "preheader": _personalize(getattr(mailing, "preheader", "") or "", user),
        "body_html": _personalize(body_to_html(mailing.message_body), user),
        "button_text": mailing.button_text or "",
        "button_url": mailing.button_url or "",
        "unsubscribe_url": unsubscribe_url(user) if user and user.pk else "#",
        "site_url": SITE_URL,
        "year": timezone.now().year,
    }
    return render_to_string("emails/crm_mailing.html", ctx)


def build_message(mailing, user, connection=None, to_email=None):
    html = render_mailing_html(mailing, user)
    text = strip_tags(re.sub(r"<br\s*/?>|</p>", "\n", body_to_html(_personalize(mailing.message_body, user))))
    if mailing.button_text and mailing.button_url:
        text += f"\n\n{mailing.button_text}: {mailing.button_url}"
    unsub = unsubscribe_url(user)
    text += f"\n\nОтписаться от писем: {unsub}"
    from_email = (
        getattr(settings, "CRM_MAILING_FROM", None)
        or getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", None)
    )
    msg = EmailMultiAlternatives(
        subject=_personalize(mailing.subject, user),
        body=text.strip(),
        from_email=from_email,
        to=[to_email or user.email],
        connection=connection,
        headers={"List-Unsubscribe": f"<{unsub}>"},
    )
    msg.attach_alternative(html, "text/html")
    return msg


def mailing_stats_qs():
    """Рассылки с посчитанными статусами получателей — один запрос на список."""
    return Mailing.objects.annotate(
        n_total=Count("recipients"),
        n_sent=Count("recipients", filter=Q(recipients__status="sent")),
        n_failed=Count("recipients", filter=Q(recipients__status="failed")),
        n_pending=Count("recipients", filter=Q(recipients__status="pending")),
    )


def enqueue_recipients(mailing, segment):
    """Фиксирует список получателей в момент запуска: статистика честная с первой секунды,
    а пользователи, зарегистрированные позже, в старую рассылку не попадают."""
    rows = segment_queryset(segment).values_list("id", "email")
    batch, total = [], 0
    for uid, email in rows.iterator(chunk_size=2000):
        batch.append(MailingRecipient(mailing=mailing, user_id=uid, email=email, channel="email"))
        if len(batch) >= 1000:
            MailingRecipient.objects.bulk_create(batch, ignore_conflicts=True)
            total += len(batch)
            batch = []
    if batch:
        MailingRecipient.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)
    return total
