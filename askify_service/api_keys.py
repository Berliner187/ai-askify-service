from .models import APIKey


def get_active_key(purpose: str):
    return APIKey.objects.filter(purpose=purpose, is_active=True).first().key
