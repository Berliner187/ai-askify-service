from django.urls import path
from .views import *


urlpatterns = [
    path('', index, name='home'),
    path('create/', page_create_survey, name='create'),
    path('api-create-survey/', generate_survey, name='api-create-survey'),
    path('survey/<str:survey_id>/', take_survey, name='survey'),
    path('result/<str:survey_id>/', result_view, name='result'),
    path('drop-survey/<str:survey_id>/', drop_survey, name='drop-survey'),
    path('history/', page_history_surveys, name='history'),
    path('survey/<str:survey_id>/download/', download_survey_pdf, name='download-survey_pdf'),
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('stats2975/', admin_stats, name='stats2975'),
    path('profile/<str:username>/', profile_view, name='profile'),
    path('subscriptions/', subscription_list, name='subscription_list'),
    path('success_payment/<str:payment_id>/', success_payment, name='success_payment'),
]


def custom_404_view(request, exception):
    return render(request, 'error.html', status=404)


def custom_500_view(request):
    return render(request, 'error.html', status=500)


handler404 = custom_404_view
handler500 = custom_500_view
