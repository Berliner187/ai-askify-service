from django.contrib import admin
from django.urls import path, include

from .settings import DEBUG


urlpatterns = [
    path('scammer1337/', admin.site.urls),
    path('', include('askify_service.urls')),
]

# if DEBUG:
#     import debug_toolbar
#     urlpatterns = [
#         path('__debug__/', include(debug_toolbar.urls))
#     ] + urlpatterns
