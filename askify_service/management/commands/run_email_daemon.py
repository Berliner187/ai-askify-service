import time
import imaplib
import email
from email.header import decode_header
import logging

from django.core.management.base import BaseCommand
from django.conf import settings

from bs4 import BeautifulSoup

tracer_l = logging.getLogger('askify_app')

# Мусорные отправители и темы, которые не надо швырять в логгер
IGNORE_SENDERS = ["mail delivery system", "mailer-daemon", "postmaster"]
IGNORE_SUBJECTS = ["mail delivery failed", "warning: message", "undelivered mail", "delayed"]


def decode_str(header_val):
    if not header_val:
        return ""
    decoded_list = decode_header(header_val)
    result = ""
    for decoded_string, charset in decoded_list:
        if isinstance(decoded_string, bytes):
            result += decoded_string.decode(charset or "utf-8", errors="replace")
        else:
            result += decoded_string
    return result


def get_message_body(msg):
    html_body = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
            
            elif content_type == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload:
                    html_body = payload.decode("utf-8", errors="replace")
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode("utf-8", errors="replace")
            if content_type == "text/html":
                html_body = text
            else:
                return text

    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    return ""


class Command(BaseCommand):
    help = "Фоновый демон проверки почты IMAP для пересылки сообщений в tracer_l"

    def handle(self, *args, **options):
        host = getattr(settings, 'EMAIL_HOST', 'mail.hosting.reg.ru')
        user = getattr(settings, 'EMAIL_HOST_USER', None)
        password = getattr(settings, 'EMAIL_HOST_PASSWORD', None)

        if not user or not password:
            tracer_l.error("[EMAIL DAEMON] EMAIL_HOST_USER или EMAIL_HOST_PASSWORD не заданы в settings.")
            return

        tracer_l.warning(f"[EMAIL DAEMON] Демон запущен. Проверка ящика: {user}")

        while True:
            try:
                mail = imaplib.IMAP4_SSL(host, 993)
                mail.login(user, password)
                mail.select("INBOX")

                status, messages = mail.search(None, 'UNSEEN')
                if status == 'OK' and messages[0]:
                    email_ids = messages[0].split()
                    for e_id in email_ids:
                        _, msg_data = mail.fetch(e_id, '(RFC822)')
                        for response_part in msg_data:
                            if isinstance(response_part, tuple):
                                msg = email.message_from_bytes(response_part[1])
                                subject = decode_str(msg["Subject"])
                                from_addr = decode_str(msg["From"])

                                # === ВОТ СУДА ВСТАВЛЯЕТСЯ ФИЛЬТР ===
                                from_lower = from_addr.lower()
                                subj_lower = subject.lower()

                                if any(s in from_lower for s in IGNORE_SENDERS) or any(s in subj_lower for s in IGNORE_SUBJECTS):
                                    # Тихо помечаем прочитанным и идем к следующему письму
                                    mail.store(e_id, '+FLAGS', '\\Seen')
                                    continue
                                # ===================================

                                body = get_message_body(msg)[:600]

                                alert_msg = (
                                    f"📩 [НОВОЕ ПИСЬМО НА ПОЧТЕ]\n"
                                    f"От: {from_addr}\n"
                                    f"Тема: {subject}\n"
                                    f"Текст:\n{body}"
                                )
                                tracer_l.warning(alert_msg)

                        # Помечаем прочитанным
                        mail.store(e_id, '+FLAGS', '\\Seen')

                mail.logout()

            except Exception as e:
                tracer_l.error(f"[EMAIL DAEMON ERROR] Сбой проверки IMAP: {e}")

            time.sleep(30)
