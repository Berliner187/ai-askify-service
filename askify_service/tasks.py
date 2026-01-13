import traceback
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.core.signing import Signer
from django.db.models import Count

import requests
import html2text

from smtplib import SMTPException

from .models import Mailing, MailingRecipient, AuthUser, AuthAdditionalUser, Survey, Subscription, PromoCode, Payment
from askify_app.settings import TELEGRAM_BOT_TOKEN, EMAIL_HOST_USER


signer = Signer()


@shared_task
def send_templated_email(user_id, subject, template_name, context=None):
    """
    Универсальная задача для отправки email на основе Django-шаблона.
    """
    try:
        user = AuthUser.objects.get(id=user_id)
        if not user.email:
            print(f"User {user.username} (ID: {user_id}) has no email. Skipping.")
            return

        if context is None:
            context = {}

        context['user'] = user

        html_message = render_to_string(template_name, context)

        send_mail(
            subject=subject,
            message='',
            from_email=EMAIL_HOST_USER,
            recipient_list=[user.email],
            fail_silently=False,
            html_message=html_message
        )
        print(f"Email '{subject}' sent to {user.email}")

    except AuthUser.DoesNotExist:
        print(f"User with ID {user_id} not found.")
    except Exception as e:
        print(f"Failed to send email to user {user_id}. Error: {e}")
        raise e


@shared_task
def check_inactive_new_users():
    """
    Проверяет новых пользователей, которые не создали ни одного теста.
    """
    twenty_minutes_ago = timezone.now() - timedelta(minutes=20)
    one_hour_ago = timezone.now() - timedelta(hours=1)

    new_users = AuthUser.objects.filter(
        date_joined__gte=one_hour_ago,
        date_joined__lte=twenty_minutes_ago
    )

    for user in new_users:
        if not user.is_staff and not Survey.objects.filter(id_staff=user.id_staff).exists():
            print(f"User {user.username} is inactive. Queuing activation email.")

            send_templated_email.delay(
                user_id=user.id,
                subject='👋 Забыли создать свой первый тест?',
                template_name='emails/activation_reminder.html',
                context={'bonus': 'WELCOME10'}
            )


@shared_task
def send_super_simple_test_email(recipient):
    """
    Отправляет самое тупое текстовое письмо, которое только можно.
    Никаких шаблонов, никакого HTML.
    """
    try:
        send_mail(
            'Проверка Celery',
            'Это тестовое сообщение, отправленное из задачи Celery. 123.',
            'support@letychka.ru',
            [recipient],
            fail_silently=False,
        )
        print(f"!!! SUPER SIMPLE TEST EMAIL SENT to {recipient} !!!")
        return "OK"
    except Exception as e:
        print(f"!!! SUPER SIMPLE TEST FAILED: {e} !!!")
        raise e


@shared_task(bind=True, autoretry_for=(SMTPException, TimeoutError), retry_backoff=True,
             retry_kwargs={'max_retries': 5}, rate_limit='12/m')
def send_manual_email_task(self, recipient_email, subject, html_body, button_text, button_url):
    """
    Celery-задача, которая выполняет фактическую отправку кастомного письма из админки.
    Умеет автоматически повторять попытку в случае временных SMTP-ошибок.
    """
    try:
        user = AuthUser.objects.filter(email=recipient_email).first()

        context = {
            'user': user,
            'subject': subject,
            'main_content': html_body,
            'button_text': button_text,
            'button_url': button_url,
        }

        final_html_message = render_to_string('emails/manual_dispatch.html', context)

        send_mail(
            subject=subject,
            message='',
            from_email=EMAIL_HOST_USER,
            recipient_list=[recipient_email],
            fail_silently=False,
            html_message=final_html_message
        )

        print(f"SUCCESS: Manual email '{subject}' sent to {recipient_email}")
        return f"Successfully sent to {recipient_email}"

    except Exception as exc:
        error_traceback = traceback.format_exc()
        print(f"!!! ERROR in send_manual_email_task for {recipient_email} !!!")
        print(error_traceback)
        print("---------------------------------------------------------")

        raise exc


@shared_task(bind=True)
def send_one_message_task(self, recipient_id, mailing_id):
    """
    Отправляет одно сообщение одному юзеру.
    """
    try:
        recipient = MailingRecipient.objects.get(id=recipient_id)
        user = recipient.user
        mailing = recipient.mailing

        signed_user_id = signer.sign(user.pk)
        unsubscribe_url = f"https://letychka.ru/unsubscribe/{signed_user_id}/"

        channel = None

        if user.email:
            try:
                context = {
                    'user': user, 'subject': mailing.subject,
                    'main_content': mailing.message_body, 'button_text': mailing.button_text,
                    'button_url': mailing.button_url, 'unsubscribe_url': unsubscribe_url
                }

                html_message = render_to_string('emails/manual_dispatch.html', context)
                send_mail(
                    subject=mailing.subject, message='', from_email=EMAIL_HOST_USER,
                    recipient_list=[user.email], fail_silently=False, html_message=html_message
                )
                channel = 'email'
            except SMTPException as e:
                raise self.retry(exc=e, countdown=60)

        else:
            additional_info = AuthAdditionalUser.objects.filter(user=user).first()
            if additional_info and additional_info.id_telegram:
                try:
                    import re

                    h = html2text.HTML2Text()
                    h.body_width = 0
                    text_body = h.handle(mailing.message_body)

                    message = f"*{mailing.subject}*\n\n{text_body}"
                    if mailing.button_text and mailing.button_url:
                        message += f"\n\n[{mailing.button_text}]({mailing.button_url})"

                        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

                        payload = {
                            'chat_id': additional_info.id_telegram,
                            'text': message,
                            'parse_mode': 'Markdown'
                        }

                        requests.post(url, json=payload)

                    channel = 'telegram'
                except Exception as e:
                    raise e

        if channel:
            recipient.status = 'sent'
            recipient.channel = channel
            recipient.sent_at = timezone.now()
            recipient.save()
        else:
            raise ValueError("No contact channel found (Email or Telegram)")

    except Exception as e:
        recipient.status = 'failed'
        recipient.error_message = str(e)
        recipient.save()
        print(f"Failed to send message for recipient {recipient_id}. Error: {e}")


@shared_task
def start_mailing_task(mailing_id):
    """
    Находит юзеров, создает для них записи и запускает задачи-работяги.
    """
    try:
        mailing = Mailing.objects.get(id=mailing_id)
        mailing.status = 'processing'
        mailing.sent_at = timezone.now()
        mailing.save()

        base_users_qs = AuthUser.objects.filter(is_staff=False, is_active=True, is_subscribed=True)

        target_users_qs = None

        if mailing.target_segment == 'all':
            target_users_qs = base_users_qs

        elif mailing.target_segment == 'inactive_subs':
            users_with_inactive_subs = Subscription.objects.filter(
                status='inactive'
            ).values_list('staff_id', flat=True).distinct()
            target_users_qs = base_users_qs.filter(id_staff__in=users_with_inactive_subs)

        elif mailing.target_segment == 'active_subs':
            users_with_active_subs = Subscription.objects.filter(
                status='active',
                end_date__gte=timezone.now()
            ).values_list('staff_id', flat=True).distinct()
            target_users_qs = base_users_qs.filter(id_staff__in=users_with_active_subs)

        elif mailing.target_segment == 'no_tests':
            users_with_tests = Survey.objects.values_list('id_staff', flat=True).distinct()
            target_users_qs = base_users_qs.exclude(id_staff__in=users_with_tests)

        if target_users_qs is None:
            raise ValueError(f"Unknown segment: {mailing.target_segment}")

        user_ids = list(target_users_qs.values_list('id', flat=True))

        if not user_ids:
            mailing.status = 'completed'
            mailing.save()
            print(f"Mailing {mailing_id} completed immediately: 0 users found in segment '{mailing.target_segment}'.")
            return

        recipients = [MailingRecipient(mailing=mailing, user_id=user_id) for user_id in user_ids]
        MailingRecipient.objects.bulk_create(recipients, ignore_conflicts=True)

        for recipient in MailingRecipient.objects.filter(mailing=mailing):
            send_one_message_task.delay(recipient.id, mailing.id)

        # Здесь можно проверить статус через N часов и пометит рассылку как 'completed'

    except Mailing.DoesNotExist:
        print(f"Mailing with id {mailing_id} not found.")


@shared_task
def send_magic_link_email(user_id, token):
    try:
        user = AuthUser.objects.get(id=user_id)
        if not user.email: return

        subject = 'Ваша ссылка для входа в Летучку'
        login_url = f"https://letychka.ru/auth/magic-link/{token}/"

        message_body = (
            f"Здравствуйте, {user.username}!\n\n"
            f"Вот Ваша ссылка для быстрого входа в аккаунт. Она действует 15 минут и работает только один раз.\n\n"
            f"Просто перейдите по ней, чтобы войти:\n"
            f"{login_url}\n\n"
            f"Если Вы не запрашивали эту ссылку, просто проигнорируйте это письмо."
        )

        send_mail(subject, message_body, settings.DEFAULT_FROM_EMAIL, [user.email])
        print(f"Sent magic link to {user.email}")
    except AuthUser.DoesNotExist:
        pass
