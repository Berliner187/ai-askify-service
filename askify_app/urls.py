from django.contrib import admin
from django.urls import path, include

from .settings import DEBUG


urlpatterns = [
    path('scammer1337/', admin.site.urls),
    path('', include('askify_service.urls')),
]
