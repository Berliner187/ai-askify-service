from django.urls import path
from .views import *


urlpatterns = [
    path('', index, name='home'),
    path('create/', page_create_survey, name='create'),
    path('api-create-survey/', generate_survey, name='api-create-survey'),
    # path('api/surveys/', get_all_surveys, name='get_all_surveys'),
    path('survey/<str:survey_id>/', take_survey, name='survey'),
    path('result/<str:survey_id>/', result_view, name='result'),
    path('drop-survey/<str:survey_id>/', drop_survey, name='drop-survey'),
    path('history/', page_create_survey, name='history'),
]
