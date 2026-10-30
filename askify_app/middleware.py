from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect

from askify_service.models import BlockedUsers
from askify_service.utils import get_client_ip, get_staff_id
from asgiref.sync import sync_to_async
from askify_app.settings import DEBUG

from datetime import datetime
import os
from django.core.cache import cache
from django.http import JsonResponse
import environ

from functools import wraps
from askify_service.models import Subscription, Payment
from django.utils import timezone
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from askify_app.settings import BASE_DIR
import logging


tracer_l = logging.getLogger('askify_app')


env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))


BLOCKED_KEY = "blocked_ips:v1"


def blocked_ips() -> frozenset:
    ips = cache.get(BLOCKED_KEY)
    if ips is None:
        ips = frozenset(BlockedUsers.objects.values_list("ip_address", flat=True))
        cache.set(BLOCKED_KEY, ips, 300)
    return ips

@receiver([post_save, post_delete], sender=BlockedUsers)
def _invalidate(**kwargs):
    cache.delete(BLOCKED_KEY)


class BlockIPMiddleware:
    ALLOWED_PREFIXES = ("/docs/", "/profile/", "/blocked/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path != "/" and not path.startswith(self.ALLOWED_PREFIXES):
            if get_client_ip(request) in blocked_ips():
                return render(request, "error.html", {
                    "error_code": "403 Forbidden",
                    "error_message": "Доступ запрещён",
                }, status=403)
        return self.get_response(request)


def check_blocked(view_func):
    def _wrapped_view(request, *args, **kwargs):
        ip = get_client_ip(request)

        if BlockedUsers.objects.filter(ip_address=ip).exists():
            return HttpResponseForbidden("IP is blocked")

        if request.user.is_authenticated:
            if BlockedUsers.objects.filter(ip_address=get_client_ip(request)).exists():
                return HttpResponseForbidden("Account is blocked")

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def subscription_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        staff_id = get_staff_id(request)
        now = timezone.now()
        active = Subscription.objects.filter(
            staff_id=staff_id, status="active", end_date__gt=now
        ).exists()
        if not active:
            Subscription.objects.filter(
                staff_id=staff_id, status="active", end_date__lte=now
            ).update(status="inactive")
            return redirect("payment")
        return view_func(request, *args, **kwargs)
    return _wrapped


def check_legal_process(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        """ Проброс легальности запроса """
        allowed_hosts = env.list('ALLOWED_HOSTS') + ['localhost:8000', '127.0.0.1:8000']
        host = request.META.get('HTTP_HOST', 'Unknown')
        if host not in allowed_hosts:
            ip = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
            referer = request.META.get('HTTP_REFERER', 'Direct')
            host = request.META.get('HTTP_HOST', 'Unknown')
            url = request.get_full_path()
            method = request.method
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cookies = request.COOKIES

            log_message = (
                f"IP: {ip}\n"
                f"User-Agent: {user_agent}\n"
                f"Referer: {referer}\n"
                f"Host: {host}\n"
                f"URL: {url}\n"
                f"Method: {method}\n"
                f"Timestamp: {timestamp}\n"
                f"Cookies: {cookies}"
            )
            tracer_l.info(log_message)

            # return HttpResponseForbidden('Zugriff verweigert. Nur letychka.ru ist erlaubt.')
            return redirect('blocked_view')

        blocked_ips = BlockedUsers.objects.values_list('ip_address', flat=True)
        client_ip = get_client_ip(request)
        if client_ip in blocked_ips:
            # return HttpResponseForbidden('Zugriff verweigert. Ihre IP ist blockiert.')
            return redirect('blocked_view')

        return view_func(request, *args, **kwargs)
    return _wrapped_view
