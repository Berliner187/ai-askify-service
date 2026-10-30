from django.apps import AppConfig
from django.conf import settings


class AskifyServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'askify_service'

    def ready(self):
        from askify_app import middleware
