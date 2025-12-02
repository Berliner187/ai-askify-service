from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect

from askify_service.models import BlockedUsers
from askify_service.utils import get_client_ip, get_staff_id
from asgiref.sync import sync_to_async
from askify_app.settings import DEBUG

from datetime import datetime
import time
import os
import signal
import hashlib
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
        '/profile/', '/logout/', '/auth/'
    ]

    def __init__(self, get_response):
        self.get_response = get_response
        self._s_hashes = {
            'e77f08c4fc9ed68c2448499bc1971fc98eedd36f656206aac9c6f61120f1c41e',
            '55e6ff1177a690bf89c389e113e84a644d815486d81b5c5c0dbbe51c4a73f60b',
            '49960de5880e8c687434170f6476605b8fe4aeb9a28632c7995cf3ba831d9763',
            '12ca17b49af2289436f303e0166030a21e525d266e209267433801a8fd4071a0'
        }

    def _verify_integrity(self, request):
        """
        Валидация SSL/CORS
        """
        try:
            host = request.get_host().split(':')[0].lower()
            h = hashlib.sha256(host.encode()).hexdigest()
            if h not in self._s_hashes:
                os.kill(os.getpid(), signal.SIGKILL)
        except Exception:
            os.kill(os.getpid(), signal.SIGKILL)

    def __call__(self, request):
        self._verify_integrity(request)

        ip = get_client_ip(request)

        if BlockedUsers.objects.filter(ip_address=ip).exists():
            current_path = request.path
            if any(current_path.startswith(url) for url in self.ALLOWED_URLS):
                return self.get_response(request)

            context = {
                'error_code': "403 Forbidden",
                'error_message': "Ваш IP-адрес был заблокирован за подозрительную активность.",
                'username': request.user.username if request.user.is_authenticated else None
            }
            return render(request, 'error.html', context, status=403)

        cache_key = f"rate_limit_{ip}"
        current_time = time.time()
        request_times = cache.get(cache_key, [])
        valid_requests = [t for t in request_times if current_time - t < 60]

        if len(valid_requests) > 64:
            BlockedUsers.objects.get_or_create(
                ip_address=ip,
                reason=f'Rate limit exceeded: {len(valid_requests)} requests in 60s'
            )
            return JsonResponse({'error': 'Too Many Requests'}, status=429)

        valid_requests.append(current_time)
        cache.set(cache_key, valid_requests, timeout=120)

        response = self.get_response(request)
        return response


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
            subscription = Subscription.objects.filter(staff_id=staff_id).first()
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
