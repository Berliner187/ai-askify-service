from django.urls import re_path
from django.urls import path
from django.views.generic import TemplateView

from .views import *
from askify_app.settings import DEBUG

from askify_service.views import telegram_magic_auth, telegram_code_auth, bot_generate_code, bot_generate_link


urlpatterns = [
    path('', index, name='home'),
    path('dlya-prepodavateley/', for_prepods, name='for_prepods'),
    path('testirovanie-online/', pro_landing, name='pro_landing'),

    path('create/', page_create_survey, name='create'),
    path('api-create-survey/', ManageSurveysView.as_view(), name='api-create-survey'),
    path('api-non-auth/create-survey/', GenerationSurveysView.as_view(), name='api-create-survey'),

    path('survey/<str:survey_id>/', TakeSurvey.as_view(), name='survey'),
    path('survey/<str:survey_id>/download/', download_survey_pdf, name='download-survey_pdf'),
    path('result/<str:survey_id>/', result_view, name='result'),
    path('result/<uuid:survey_id>/download/', download_results_pdf, name='download-results_pdf'),

    path('c/<str:survey_id>/', preview_test, name='preview_test'),
    path('t/<str:survey_id>/', take_test, name='take_test'),
    path('c/<str:survey_id>/result/', redirect_to_dashboard, name='preview_test_inside'),
    path('c/<str:survey_id>/dashboard/', view_results, name='preview_test_result'),

    path('arena/', arena_view, name='arena'),
    path('api/arena/next-question/', get_next_question, name='api_get_next_question'),
    path('api/arena/submit-answer/', submit_arena_answer, name='api_submit_arena_answer'),

    path('register-view/<str:survey_id>/', register_survey_view, name='register_survey_view'),
    path('api/surveys/<uuid:survey_id>/toggle-answers/', toggle_answers, name='toggle-answers'),
    path('api/t/<str:survey_id>/submit/', submit_answers, name='submit_answers'),
    path('api/c/<uuid:survey_id>/result/export/excel/', export_results_to_excel, name='export_results_to_excel'),

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
    path('api/admin/block_ip/', block_ip_api, name='api_block_ip'),
    path('api/admin/promote_user/', promote_user_api, name='api_promote_user'),
    path('api/admin/add_api_key/', add_api_key_api, name='api_add_key'),
    path('api/admin/activate_api_key/', activate_api_key_api, name='api_activate_key'),
    path('admin/activate-key/', activate_api_key, name='activate_api_key'),
    path('db_viewer/', db_viewer, name='db_viewer'),
    path('db-search/', db_search, name='db-search'),

    path('profile/<str:username>/', profile_view, name='profile'),
    path('profile/', redirect_to_profile, name='profile_redirect'),

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

    path('api/ghost_disconnect/', terminate_session, name='ghost_disconnect'),

    path("api/user-stats/", user_stats_api, name="user_stats_api"),
    path('api/user-profile/', user_profile_api, name='user_profile_api'),
    path('api/personal_charts/', personal_charts_data_api, name='personal_charts_api'),
    path('api/student_charts/', student_charts_data_api, name='student_charts_api'),
    path('api/test-charts/<uuid:survey_id>/', single_test_charts_api, name='single_test_charts_api'),
    path('api/admin-live-stats', api_admin_live_stats, name='api_admin_live_stats'),

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

    path('stats2975/crm/', user_ops_center_view, name='user_ops_center'),
    path('api/admin/search-users/', search_users_api, name='api_search_users'),
    path('api/admin/user-details/<int:user_id>/', get_user_details_api, name='api_get_user_details'),
    path('api/admin/new-users/', get_new_users_api, name='api_get_new_users'),
    path('api/admin/send-manual-email/', send_manual_email_api, name='api_send_manual_email'),
    path('unsubscribe/<str:signed_user_id>/', unsubscribe_view, name='unsubscribe'),

    path('api/admin/mailings/start/', start_mailing_api, name='api_start_mailing'),
    path('api/admin/mailings/history/', get_mailing_history_api, name='api_get_mailing_history'),

    path('secure/api/v1/ops/black-ops-launch/<str:secret>/', black_ops_launch, name='deploy_webhook'),
    path('healthz/', health_check_view, name='health_check'),

    path('api/bot/generate-login-code/', bot_generate_code),
    path('api/bot/generate-magic-link/', bot_generate_link),

    path('auth/telegram/callback/<str:token>/', telegram_magic_auth, name='tg_magic_login'),
    path('auth/code/', telegram_code_auth, name='tg_code_login'),

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
