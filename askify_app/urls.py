from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path('scammer1337/', admin.site.urls),
    path('', include('askify_service.urls')),
]
