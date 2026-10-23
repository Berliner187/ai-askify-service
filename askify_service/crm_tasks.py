"""
Celery-задачи рассылок CRM.

ВАЖНО: чтобы воркер увидел эти задачи, добавьте в конец tasks.py одну строку:
    from .crm_tasks import *  # noqa: F401,F403

Как работает отправка:
  1. crm_views.start_mailing создаёт Mailing и сразу фиксирует всех получателей (MailingRecipient, status=pending).
  2. crm_dispatch_mailing отправляет пачку до CHUNK писем через одно SMTP-соединение,
     соблюдая лимит CRM_MAILING_RATE_PER_MIN, и ставит себя в очередь снова, пока есть pending.
     Короткие прогоны не упираются в time limit воркера и быстро реагируют на паузу/отмену.
  3. Сетевые сбои SMTP не превращают письмо в «ошибку»: получатель остаётся в очереди,
     задача повторит его через минуту (до MAX_ATTEMPTS попыток).
  4. Блокировка в кэше не даёт двум воркерам слать одну рассылку параллельно (нет дублей писем).
"""
import logging
import smtplib
import socket
import time

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import get_connection
from django.utils import timezone

from .models import Mailing, MailingRecipient
from .crm_mailing import build_message

log = logging.getLogger("askify_app")

CHUNK = 150
MAX_ATTEMPTS = 3
TRANSIENT = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    ConnectionError,
    socket.timeout,
    TimeoutError,
)


def _rate_delay():
    per_min = int(getattr(settings, "CRM_MAILING_RATE_PER_MIN", 90) or 90)
    return 60.0 / max(1, per_min)


def _lock_key(mailing_id):
    return f"crm:mailing:lock:{mailing_id}"


def finalize_mailing(mailing_id):
    m = Mailing.objects.filter(id=mailing_id).first()
    if not m or m.status in ("paused", "canceled"):
        return
    rec = m.recipients
    if rec.filter(status="pending").exists():
        return
    total = rec.count()
    sent = rec.filter(status="sent").count()
    m.status = "failed" if total and not sent else "completed"
    m.finished_at = timezone.now()
    m.save(update_fields=["status", "finished_at"])
    log.info(f"MAILING #{m.id} finished: {sent}/{total} sent")


@shared_task(bind=True, ignore_result=True, acks_late=True)
def crm_dispatch_mailing(self, mailing_id):
    if not cache.add(_lock_key(mailing_id), "1", timeout=20 * 60):
        return "locked"
    requeue_in = None
    try:
        requeue_in = _send_chunk(mailing_id)
    finally:
        cache.delete(_lock_key(mailing_id))
    if requeue_in is not None:
        crm_dispatch_mailing.apply_async((mailing_id,), countdown=requeue_in)
    return "ok"


def _send_chunk(mailing_id):
    """Отправляет одну пачку. Возвращает через сколько секунд продолжить или None, если всё."""
    m = Mailing.objects.filter(id=mailing_id).first()
    if not m or m.status in ("paused", "canceled", "completed", "draft"):
        return None

    now = timezone.now()
    if m.status == "scheduled" and m.scheduled_at and m.scheduled_at > now:
        # проснулись раньше срока (например, после рестарта воркера) — ждём дальше
        return max(5, int((m.scheduled_at - now).total_seconds()))

    if m.status != "processing" or not m.sent_at:
        m.status = "processing"
        m.sent_at = m.sent_at or now
        m.save(update_fields=["status", "sent_at"])

    ids = list(
        m.recipients.filter(status="pending").order_by("id").values_list("id", flat=True)[:CHUNK]
    )
    if not ids:
        finalize_mailing(mailing_id)
        return None

    delay = _rate_delay()
    conn = get_connection(fail_silently=False)
    transient_hit = False
    try:
        for i, rid in enumerate(ids):
            if i and i % 15 == 0:
                st = Mailing.objects.filter(id=mailing_id).values_list("status", flat=True).first()
                if st in ("paused", "canceled"):
                    return None

            r = MailingRecipient.objects.select_related("user").filter(id=rid, status="pending").first()
            if not r:
                continue
            u = r.user
            if not u.is_subscribed or not u.email or "@" not in u.email:
                r.status, r.error_message = "failed", "Пропущен: отписался или нет почты"
                r.save(update_fields=["status", "error_message"])
                continue

            r.attempts += 1
            try:
                build_message(m, u, connection=conn).send()
                r.status, r.sent_at, r.error_message = "sent", timezone.now(), None
            except TRANSIENT as e:
                # соединение упало: письмо не теряем, пробуем позже
                try:
                    conn.close()
                except Exception:
                    pass
                conn = get_connection(fail_silently=False)
                if r.attempts >= MAX_ATTEMPTS:
                    r.status, r.error_message = "failed", f"SMTP недоступен: {e}"[:1000]
                else:
                    r.error_message = f"Повтор: {e}"[:1000]
                    transient_hit = True
                Mailing.objects.filter(id=mailing_id).update(last_error=f"{timezone.now():%H:%M} {e}"[:1000])
            except smtplib.SMTPRecipientsRefused as e:
                r.status, r.error_message = "failed", f"Адрес отклонён: {list(e.recipients.values())[:1]}"[:1000]
            except Exception as e:  # SMTPDataError, ошибки шаблона и т.п.
                r.status, r.error_message = "failed", str(e)[:1000]
            r.save(update_fields=["status", "sent_at", "error_message", "attempts"])

            if transient_hit:
                break
            time.sleep(delay)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if transient_hit:
        return 60
    if MailingRecipient.objects.filter(mailing_id=mailing_id, status="pending").exists():
        return 1
    finalize_mailing(mailing_id)
    return None
