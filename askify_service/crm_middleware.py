from django.core.cache import cache
 
from askify_service.models import UserIPHistory, _request_ip

from django.core.cache import cache
 
from .models import UserIPHistory, _request_ip
 
 
class TrackUserIPMiddleware:
    TTL = 60 * 60
 
    def __init__(self, get_response):
        self.get_response = get_response
 
    def __call__(self, request):
        response = self.get_response(request)
        try:
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                ip = _request_ip(request)
                if ip and cache.add(f"crm:ipseen:{user.pk}:{ip}", 1, self.TTL):
                    UserIPHistory.touch(user, ip, request.META.get("HTTP_USER_AGENT", ""))
        except Exception:
            pass
        return response
