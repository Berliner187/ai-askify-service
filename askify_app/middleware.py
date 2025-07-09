from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect

from askify_service.models import BlockedUsers
from askify_service.utils import get_client_ip, get_staff_id
from asgiref.sync import sync_to_async
from askify_app.settings import DEBUG

from datetime import datetime
import time
from django.core.cache import cache
from django.http import JsonResponse

from functools import wraps
from askify_service.models import Subscription, Payment
from django.utils import timezone

import logging


tracer_l = logging.getLogger('askify_app')


class BlockIPMiddleware:
    ALLOWED_URLS = [
        '/docs/public-offer/', '/', '/docs/user-agreement/', '/docs/privacy-policy/',
        '/profile/', '/logout/'
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = get_client_ip(request)
        # self.limit(request, ip)

        # current_path = request.path
        #
        # if ip in BlockedUsers.objects.values_list('ip_address', flat=True):
        #     if (current_path in self.ALLOWED_URLS) or ('profile' in current_path):
        #         return self.get_response(request)
        #     context = {
        #         'error_code': "403 Forbidden",
        #         'error_message': "Forbidden/Доступ запрещён",
        #         'username': request.user.username if request.user.username else None
        #     }
        #     return render(request, 'error.html', context)
        #
        if not DEBUG:
            host = request.META.get('HTTP_HOST', '')
            referer = request.META.get('HTTP_REFERER', '')

            allowed_hosts = ['letychka.ru', 'www.letychka.ru', 'localhost:8000', '127.0.0.1:8000']
            allowed_referers = ['https://letychka.ru', 'https://www.letychka.ru', 'https://localhost:8000', 'https://127.0.0.1:8000']

            if host not in allowed_hosts and not any(referer.startswith(ref) for ref in allowed_referers):
                return HttpResponseForbidden('Zugriff verweigert. Nur letychka.ru ist erlaubt.')
        #
        return self.get_response(request)

    def limit(self, request, ip):
        cache_key = f"rate_limit_{ip}"

        current_time = time.time()
        request_data = cache.get(cache_key, (0, current_time))

        request_count, first_request_time = request_data

        if current_time - first_request_time > 60:
            request_count = 0
            first_request_time = current_time

        request_count += 1

        if request_count > 64:
            try:
                BlockedUsers.objects.get_or_create(
                    ip_address=ip,
                    reason='Too many requests'
                )
            except Exception:
                pass

            return JsonResponse({'error': 'Too many requests'}, status=429)

        cache.set(cache_key, (request_count, first_request_time), timeout=60)
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
    def _wrapped_view(request, *args, **kwargs):
        staff_id = get_staff_id(request)

        try:
            subscription = Subscription.objects.get(staff_id=staff_id)
            print(subscription.end_date < timezone.now(), subscription.status != 'active')

            if subscription.end_date < timezone.now() or subscription.status != 'active':
                subscription.status = 'inactive'
                subscription.save()
                return redirect('payment')

            if subscription.status == 'inactive':
                return redirect('payment')

        except Subscription.DoesNotExist:
            return redirect('payment')

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def check_legal_process(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        """ Проброс легальности запроса """
        allowed_hosts = ['letychka.ru', 'www.letychka.ru', 'localhost:8000', '127.0.0.1:8000']
        host = request.META.get('HTTP_HOST', 'Unknown')
        print(host)
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
            print(log_message)

            # return HttpResponseForbidden('Zugriff verweigert. Nur letychka.ru ist erlaubt.')
            return redirect('blocked_view')

        blocked_ips = BlockedUsers.objects.values_list('ip_address', flat=True)
        client_ip = get_client_ip(request)
        if client_ip in blocked_ips:
            # return HttpResponseForbidden('Zugriff verweigert. Ihre IP ist blockiert.')
            return redirect('blocked_view')

        return view_func(request, *args, **kwargs)
    return _wrapped_view
