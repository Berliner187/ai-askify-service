from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect

from askify_service.models import BlockedUsers
from askify_service.utils import get_client_ip, get_staff_id
from asgiref.sync import sync_to_async

from functools import wraps
from askify_service.models import Subscription, Payment
from django.utils import timezone


class BlockIPMiddleware:
    ALLOWED_URLS = [
        '/docs/public-offer/', '/', '/docs/user-agreement/', '/docs/privacy-policy/',
        '/profile/', '/logout/'
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = get_client_ip(request)

        current_path = request.path

        if ip in BlockedUsers.objects.values_list('ip_address', flat=True):

            if (current_path in self.ALLOWED_URLS) or ('profile' in current_path):
                return self.get_response(request)

            context = {
                'error_code': "403 Forbidden",
                'error_message': "Forbidden/Доступ запрещён",
                'username': request.user.username if request.user.username else None
            }
            return render(request, 'error.html', context)
            # return HttpResponseForbidden("Отказано.")
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
            if subscription.end_date < timezone.now() or subscription.status != 'active':
                subscription.status = 'inactive'
                subscription.save()
                return redirect('payment')
        except Subscription.DoesNotExist:
            return redirect('payment')

        return view_func(request, *args, **kwargs)
    return _wrapped_view
