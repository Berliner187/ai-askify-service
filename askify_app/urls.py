from django.contrib import admin
from django.urls import path, include
from askify_service.views import generate_survey, page_create_test

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('askify_service.urls')),
]
