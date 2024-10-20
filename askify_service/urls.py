from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('create/', views.page_create_test, name='create'),
    path('api-create-survey/', views.generate_survey, name='api-create-survey')
]
