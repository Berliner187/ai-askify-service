import uuid
import hashlib
from django.conf import settings
from askify_service.models import AuthUser, Survey


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    return ip


def get_or_create_guest_user(request):
    if request.user.is_authenticated:
        auth_user = AuthUser.objects.filter(user=request.user).first()
        return auth_user.id_staff if auth_user else request.user.id, False

    if not request.session.session_key:
        request.session.save()

    session_key = request.session.session_key
    device_id = request.COOKIES.get('letychka_device_id') or session_key

    composite_seed = f"guest_{session_key}_{device_id}"
    guest_hash = hashlib.sha256(composite_seed.encode()).hexdigest()[:32]

    auth_user, created = AuthUser.objects.get_or_create(
        hash_user_id=guest_hash,
        defaults={
            'username': f"guest_{uuid.uuid4().hex[:8]}",
            'is_active': True,
        }
    )

    request.session['guest_staff_id'] = str(auth_user.id_staff)
    return auth_user.id_staff, True
