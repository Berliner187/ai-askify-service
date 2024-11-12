from django.urls import path
from .views import *


urlpatterns = [
    path('', index, name='home'),
    path('create/', page_create_survey, name='create'),
    path('api-create-survey/', ManageSurveysView.as_view(), name='api-create-survey'),
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
    path('docs/<slug:slug>/', document_view, name='document_view'),

    path('api/auth/vk/', vk_auth, name='vk_auth'),
    path('callback/', vk_callback, name='vk_callback'),

    path('success_payment/', success_payment, name='success_payment_view'),
    path('payment/success/', payment_success, name='payment_success'),
    path('payment/success/<str:payment_id>/', success_payment, name='success_payment_detail'),
    path('get_ip/', get_ip, name='get_ip'),
    path('payment/', payment_success, name='payment'),
    path('api/payment/confirm/', confirm_payment, name='confirm_payment'),

    path('upload/', FileUploadView.as_view(), name='file_upload'),

    # path('unblock-ip/<str:ip_address>/', unblock_ip, name='unblock_ip'),
    path('block-user/<str:id_staff>/', block_by_staff_id, name='block_by_staff_id'),
    path('unblock-user/<str:id_staff>/', unblock_by_staff_id, name='unblock_by_staff_id'),

    path('block-ip/<str:ip_address>/', block_by_ip, name='block_ip'),
    path('unblock-ip/<str:ip_address>/', unblock_by_ip, name='unblock_ip')
]
