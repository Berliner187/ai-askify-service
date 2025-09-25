from django.urls import path
from django.views.generic import TemplateView

from .views import *
from askify_app.settings import DEBUG


urlpatterns = [
    path('', index, name='home'),
    path('dlya-prepodavateley/', for_prepods, name='for_prepods'),

    path('create/', page_create_survey, name='create'),
    path('api-create-survey/', ManageSurveysView.as_view(), name='api-create-survey'),
    path('api-non-auth/create-survey/', GenerationSurveysView.as_view(), name='api-create-survey'),

    path('survey/<str:survey_id>/', TakeSurvey.as_view(), name='survey'),
    path('survey/<str:survey_id>/download/', download_survey_pdf, name='download-survey_pdf'),
    path('result/<str:survey_id>/', result_view, name='result'),
    path('result/<uuid:survey_id>/download/', download_results_pdf, name='download-results_pdf'),

    path('c/<str:survey_id>/', preview_test, name='preview_test'),
    path('t/<str:survey_id>/', take_test, name='take_test'),
    path('api/t/<str:survey_id>/submit/', submit_answers, name='submit_answers'),
    path('c/<str:survey_id>/result/', view_results, name='preview_test_result'),

    path('register-view/<str:survey_id>/', register_survey_view, name='register_survey_view'),
    path('api/surveys/<uuid:survey_id>/toggle-answers/', toggle_answers, name='toggle-answers'),

    path('solving-tests/', solving_tests_promo, name='solving_tests_promo'),
    path('for-teachers/', teachers_promo, name='teachers_promo'),
    path('for-medics/', medicine_promo, name='medicine_promo'),

    path('drop-survey/<str:survey_id>/', drop_survey, name='drop-survey'),
    path('history/', page_history_surveys, name='history'),
    path('api/get-history/', api_get_history, name='api_history'),
    path('load-more-surveys/', load_more_surveys, name='load-more-surveys'),

    path('api/quick-register/', quick_register_api, name='api_quick_register'),
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('stats2975/', admin_stats, name='stats2975'),
    path('admin/activate-key/', activate_api_key, name='activate_api_key'),
    path('profile/<str:username>/', profile_view, name='profile'),
    path('db_viewer/', db_viewer, name='db_viewer'),
    path('db-search/', db_search, name='db-search'),

    path('blocked_view/', blocked_view, name='blocked_view'),

    path('docs/<slug:slug>/', document_view, name='document_view'),
    path('media/<slug:slug>/', blog_view, name='media_view'),

    path('vk-auth/', vk_auth, name='vk_auth'),
    path('vk-auth-callback/', vk_auth_callback, name='vk_auth_callback'),

    path('get_ip/', get_ip, name='get_ip'),

    path('available-plans/', available_plans, name='available_plans'),

    path('api/payment/initiate/', PaymentInitiateView.as_view(), name='payment_initiate'),
    path('payment/', create_payment, name='payment'),
    path('payment/success/', PaymentSuccessView.as_view(), name='payment_success'),
    path('payment/fail/', PaymentSuccessView.as_view(), name='payment_fail'),

    path('api/get-demo-tests/', get_demo_tests),
    path('upload/', FileUploadView.as_view(), name='file_upload'),

    path('login/telegram/', phone_number_view, name='auth_telegram'),
    path('verify-code/', verify_code_view, name='verify_code'),

    path('auth/telegram/', TelegramAuthView.as_view(), name='telegram_auth'),

    path('api/ghost_disconnect/', terminate_session, name='ghost_disconnect'),

    path("api/user-stats/", user_stats_api, name="user_stats_api"),
    path('api/user-profile/', user_profile_api, name='user_profile_api'),

    path('api/v1/signal-secure/', confirm_user, name='api_v1_signal_secure'),
    path('api/v2/signal-secure/', confirm_user_v2, name='api_v2_signal_secure'),
    path('api/v2/signal-secure/exchange_keys/', exchange_keys, name='api_v2_exchange_keys'),

    path('api/v2/one_click_auth/<str:token>/<str:token_hash>/', one_click_auth_view, name='one_click_auth'),

    path('block-user/<str:id_staff>/', block_by_staff_id, name='block_by_staff_id'),
    path('unblock-user/<str:id_staff>/', unblock_by_staff_id, name='unblock_by_staff_id'),
    path('block-ip/<str:ip_address>/', block_by_ip, name='block_ip'),
    path('unblock-ip/<str:ip_address>/', unblock_by_ip, name='unblock_ip'),

    path('verify-email/<str:token>/', verify_email, name='verify_email'),

    path('password_reset/', PasswordResetView.as_view(), name='password_reset'),
    path('password_reset_confirm/<uidb64>/<token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password_reset_done/', password_reset_email, name='password_reset_done'),
    path('password_reset_complete/', password_reset_complete, name='password_reset_complete'),

    path('secure/api/v1/ops/black-ops-launch/<str:secret>/', black_ops_launch, name='deploy_webhook'),
    path('healthz/', health_check_view, name='health_check'),

    path('cache-compat.php', lambda r: HttpResponseForbidden()),
    path('admin-post.php', lambda r: HttpResponseForbidden()),
]

if DEBUG:
    urlpatterns += [
        path('test403/', TemplateView.as_view(template_name='askify_service/errors/403.html')),
        path('test404/', TemplateView.as_view(template_name='askify_service/errors/404.html')),
        path('test500/', TemplateView.as_view(template_name='askify_service/errors/500.html')),
    ]

handler400 = 'askify_service.views.handler400'
handler403 = 'askify_service.views.handler403'
handler404 = 'askify_service.views.handler404'
handler500 = 'askify_service.views.handler500'
