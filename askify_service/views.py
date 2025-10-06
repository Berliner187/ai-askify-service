from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from asgiref.sync import sync_to_async
from django.utils.decorators import method_decorator
from django.core import signing
from django.utils.encoding import force_bytes
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.http import HttpResponseForbidden, HttpResponse
from django.db.models import Q
from django.db.models.functions import Length
from django.shortcuts import render, redirect
from django.views import View
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from django.db.models import F, ExpressionWrapper, DurationField
from django.db.models.functions import Abs
from collections import defaultdict
from datetime import date, timedelta
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.csrf import csrf_exempt
from django.db.models.functions import NthValue
from django.utils.safestring import mark_safe
from django.db import connection


from io import BytesIO

from .utils import *
from .models import *
from .forms import *
from .constants import *
from .tracer import *
from .quant import Quant


from askify_app.settings import DEBUG, BASE_DIR, ALLOWED_HOSTS
from askify_app.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

from askify_app.middleware import check_blocked, subscription_required, check_legal_process


import openai
import markdown
import requests
import aiofiles
import PyPDF2
from Crypto.PublicKey import ECC
import vk_api
import chardet
import docx
import PyPDF2
from tempfile import NamedTemporaryFile
import textract
from bs4 import BeautifulSoup
import environ


from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Spacer, PageBreak, SimpleDocTemplate
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT


from datetime import datetime, timedelta, time
import datetime as only_datetime
import base64
import asyncio
import time
import hashlib
import uuid
import random
import os
import re
import hmac
import json
import subprocess
from decimal import Decimal


env = environ.Env()

environ.Env.read_env(os.path.join(BASE_DIR, '.env'))


DEPLOY_SCRIPT_PATH = env('DEPLOY_PATH')


os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"


tracer_l = logging.getLogger('askify_app')
crypto_b = Quant()


@check_legal_process
def index(request):
    start_date = "01.01.2025"

    context = {
        'username': request.user.username if request.user.is_authenticated else 0,
        'total_users': calculate_total_users(start_date, 1200),
        'debug': DEBUG
    }

    return render(request, 'askify_service/index.html', context)


@check_legal_process
def for_prepods(request):
    context = {
        'username': request.user.username if request.user.is_authenticated else 0,
        'debug': DEBUG
    }
    return render(request, 'askify_service/for_prepods.html', context)


# @subscription_required
@login_required
def page_create_survey(request):
    current_id_staff = get_staff_id(request)

    subs = Subscription.objects.get(staff_id=current_id_staff)
    subs.status = subs.check_sub_status()
    tests_count_limit = get_daily_test_limit(subs.plan_name) if subs.status == 'active' else 0

    manage_tokens_limits = ManageTokensLimits(current_id_staff)
    tests_used_today = manage_tokens_limits.get_tests_used_today()
    diff_tests_count_limit = tests_count_limit - tests_used_today

    subscription_level = get_subscription_level(request)

    start_month = date.today().replace(day=1)
    week_ago = date.today() - timedelta(days=7)
    today = date.today()

    all_surveys = Survey.objects.filter().only('survey_id', 'updated_at')
    user_surveys = Survey.objects.filter(id_staff=current_id_staff).only('survey_id', 'questions', 'title', 'updated_at')
    user_answers = UserAnswers.objects.filter(id_staff=current_id_staff)
    feedbacks = FeedbackFromAI.objects.filter(id_staff=current_id_staff)

    total_tests = user_surveys.count()

    stats = UserAnswers.calculate_user_statistics(current_id_staff)

    feedback_agg = feedbacks.aggregate(
        feedback_count=Count('id'),
        unique_models=Count('model_name', distinct=True),
    )

    today_uploads = all_surveys.filter(updated_at__date=today).count()
    tests_this_month = user_surveys.filter(updated_at__gte=start_month).count()
    feedback_last_week = feedbacks.filter(created_at__gte=week_ago).count()

    total_questions = sum(len(json.loads(s.questions)) for s in user_surveys if s.questions)
    avg_questions = total_questions / total_tests if total_tests else 0

    total_answers = user_answers.count()
    avg_correct_answers = user_answers.aggregate(avg=Avg('scored_points'))['avg'] or 0

    surveys_with_feedback = feedbacks.values_list('survey_id', flat=True).distinct().count()
    percent_with_feedback = (surveys_with_feedback / total_tests * 100) if total_tests else 0

    passed_survey_ids = user_answers.values_list('survey_id', flat=True).distinct()
    tests_created_and_passed = user_surveys.filter(survey_id__in=passed_survey_ids).count()

    context = {
        "page_title": "Создать тест",
        'tests_today': max(diff_tests_count_limit, 0),
        'username': get_username(request),
        'subscription_level': subscription_level,
        'subscription_status': subs.status,
        "total_tests": total_tests,
        "passed_tests": stats['passed_tests'],
        "feedback_count": feedback_agg['feedback_count'] or 0,
        "today_uploads": today_uploads,
        "total_questions": total_questions,
        "avg_questions": f"{avg_questions:.1f}" if total_tests else 0,
        "total_answers": total_answers,
        "avg_correct_answers": f"{avg_correct_answers:.1f}" if total_answers else 0,
        "unique_models_count": feedback_agg['unique_models'] or 0,
        "tests_this_month": tests_this_month,
        "feedback_last_week": feedback_last_week,
        "percent_with_feedback": f"{percent_with_feedback:.1f}%" if total_tests else "0%",
        "tests_created_and_passed": tests_created_and_passed,
    }

    return render(request, 'askify_service/text_input.html', context)


@login_required
def user_stats_api(request):
    """
    Полностью переработанная и оптимизированная API-вьюха для статистики пользователя.
    Сводит тысячи потенциальных запросов к ~7 основным.
    """
    staff_id = get_staff_id(request)
    today = date.today()

    try:
        subs = Subscription.objects.get(staff_id=staff_id)
        subs.status = subs.check_sub_status()
        tests_limit = get_daily_test_limit(subs.plan_name) if subs.status == 'active' else 0
    except Subscription.DoesNotExist:
        tests_limit = 0
        
    used_today = ManageTokensLimits(staff_id).get_tests_used_today()
    remaining_tests = max(0, tests_limit - used_today)

    surveys = Survey.objects.filter(id_staff=staff_id)
    answers = UserAnswers.objects.filter(id_staff=staff_id)
    feedbacks = FeedbackFromAI.objects.filter(id_staff=staff_id)

    # ЗАПРОС 1: Вся статистика по тестам (Survey) за один раз
    survey_stats = surveys.aggregate(
        total_tests=Count('id'),
        today_created=Count('id', filter=Q(updated_at__date=today)),
        this_month_count=Count('id', filter=Q(updated_at__gte=today.replace(day=1)))
    )
    total_tests = survey_stats['total_tests']

    # ЗАПРОС 2: Вся статистика по ответам (UserAnswers) за один раз
    answers_stats = answers.aggregate(
        total_answers=Count('id'),
        avg_correct=Coalesce(Avg('scored_points'), 0.0)
    )
    
    # ЗАПРОС 3: Вся статистика по фидбеку (FeedbackFromAI) за один раз
    feedback_stats = feedbacks.aggregate(
        feedback_count=Count('id'),
        unique_models_count=Count('model_name', distinct=True),
        last_week_feedback=Count('id', filter=Q(created_at__gte=today - timedelta(days=7))),
        distinct_surveys_with_feedback=Count('survey_id', distinct=True)
    )

    # ЗАПРОС 4: Самая используемая модель. Это эффективно.
    model_most_used_obj = feedbacks.values('model_name').annotate(c=Count('model_name')).order_by('-c').first()
    model_most_used = format_model_name(model_most_used_obj['model_name']) if model_most_used_obj else "–"

    # ЗАПРОС 5 (ОПТИМИЗИРОВАННЫЙ): Вытаскиваем все JSON-поля за один запрос
    questions_lists = surveys.values_list('questions', flat=True)
    total_questions = sum(len(json.loads(q)) for q in questions_lists if q)

    # ЗАПРОС 6 (ОПТИМИЗИРОВАННЫЙ): Считаем тесты, на которые есть ответы.
    created_and_passed = answers.values('survey_id').distinct().count()

    # ЗАПРОС 7: Внешний вызов, который мы не трогали.
    user_calc_stats = UserAnswers.calculate_user_statistics(staff_id)
    passed_tests = user_calc_stats['passed_tests']
    best_result = user_calc_stats['best_result']

    # --- ЭТАП 5: Финальные расчеты в Python (без запросов к БД) ---
    avg_questions = round(total_questions / total_tests, 1) if total_tests > 0 else 0
    feedback_coverage = (feedback_stats['distinct_surveys_with_feedback'] / total_tests * 100) if total_tests > 0 else 0

    return JsonResponse({
        "tests_remaining_today": remaining_tests,
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "best_result": best_result,
        "feedback_count": feedback_stats['feedback_count'],
        "today_created": survey_stats['today_created'],
        "model_most_used": model_most_used,
        "total_questions": total_questions,
        "avg_questions": avg_questions,
        "total_answers": answers_stats['total_answers'],
        "avg_correct_answers": round(answers_stats['avg_correct'], 1),
        "unique_models_count": feedback_stats['unique_models_count'],
        "tests_this_month": survey_stats['this_month_count'],
        "feedback_last_week": feedback_stats['last_week_feedback'],
        "percent_with_feedback": round(feedback_coverage, 1),
        "avg_tokens_used": 0,
        "tests_created_and_passed": created_and_passed
    })


@login_required
def personal_charts_data_api(request):
    """
    API-эндпоинт для ЛИЧНОЙ статистики создателя тестов.
    """
    staff_id = get_staff_id(request)
    today = timezone.now().date()

    # --- График 1: Динамика создания тестов (остается) ---
    activity_labels = []
    activity_data = []

    # Запрос 1: Получаем количество созданных тестов по дням за неделю
    surveys_last_week = Survey.objects.filter(
        id_staff=staff_id,
        created_at__date__gte=today - timezone.timedelta(days=6)
    ).values('created_at__date').annotate(count=Count('id')).order_by('created_at__date')

    daily_counts = {item['created_at__date']: item['count'] for item in surveys_last_week}

    for i in range(7):
        day = today - timezone.timedelta(days=6 - i)
        activity_labels.append(day.strftime('%d.%m'))
        activity_data.append(daily_counts.get(day, 0))

    # --- График 2: Уникальные просмотры тестов за неделю ---
    views_labels = []
    views_data = []

    # Запрос 2: Расчёт количества уникальных просмотров по дням за неделю
    views_last_week = SurveyUniqueView.objects.filter(
        survey__id_staff=staff_id,
        timestamp__date__gte=today - timezone.timedelta(days=6)
    ).values('timestamp__date').annotate(count=Count('id')).order_by('timestamp__date')

    daily_views = {item['timestamp__date']: item['count'] for item in views_last_week}

    for i in range(7):
        day = today - timezone.timedelta(days=6 - i)
        views_labels.append(day.strftime('%d.%m'))
        views_data.append(daily_views.get(day, 0))

    return JsonResponse({
        'activity_chart': {
            'labels': activity_labels,
            'data': activity_data
        },
        'views_chart': {
            'labels': views_labels,
            'data': views_data
        }
    })


@login_required
def student_charts_data_api(request):
    """
    API-эндпоинт для статистики по прохождениям тестов УЧЕНИКАМИ.
    """
    staff_id = get_staff_id(request)
    today = timezone.now().date()

    user_surveys = Survey.objects.filter(id_staff=staff_id)

    # --- График 1: Распределение результатов ---
    percentage_expression = ExpressionWrapper(
        (F('score') * 100.0) / F('total_questions'),
        output_field=FloatField()
    )

    attempts_with_percentage = TestAttempt.objects.filter(
        survey__in=user_surveys,
        total_questions__gt=0
    ).annotate(
        percentage_score=percentage_expression
    )

    attempts_agg = attempts_with_percentage.aggregate(
        high_scores=Count('id', filter=Q(percentage_score__gte=80)),
        medium_scores=Count('id', filter=Q(percentage_score__gte=50, percentage_score__lt=80)),
        low_scores=Count('id', filter=Q(percentage_score__lt=50))
    )

    scores_data = [
        attempts_agg.get('high_scores', 0),
        attempts_agg.get('medium_scores', 0),
        attempts_agg.get('low_scores', 0)
    ]

    # --- График 2: Активность прохождений ---
    activity_labels = []
    activity_data = []

    attempts_last_week = TestAttempt.objects.filter(
        survey__in=user_surveys,
        created_at__date__gte=today - timezone.timedelta(days=6)
    ).values('created_at__date').annotate(count=Count('id')).order_by('created_at__date')

    daily_attempts = {item['created_at__date']: item['count'] for item in attempts_last_week}

    for i in range(7):
        day = today - timezone.timedelta(days=6 - i)
        activity_labels.append(day.strftime('%d.%m'))
        activity_data.append(daily_attempts.get(day, 0))

    return JsonResponse({
        'scores_chart': {
            'labels': ['Отлично (80-100%)', 'Хорошо (50-79%)', 'Плохо (<50%)'],
            'data': scores_data
        },
        'attempts_activity_chart': {
            'labels': activity_labels,
            'data': activity_data
        }
    })


@login_required
def single_test_charts_api(request, survey_id):
    """
    API-эндпоинт для графиков на странице аналитики КОНКРЕТНОГО теста.
    """
    staff_id = get_staff_id(request)
    today = timezone.now().date()

    # try:
    survey = Survey.objects.get(survey_id=survey_id)
    # except Survey.DoesNotExist:
    #     return JsonResponse({'error': 'Test not found or access denied'}, status=404)

    activity_labels = []
    activity_data = []

    attempts_last_week = TestAttempt.objects.filter(
        survey=survey,
        created_at__date__gte=today - timezone.timedelta(days=6)
    ).values('created_at__date').annotate(count=Count('id')).order_by('created_at__date')

    daily_attempts = {item['created_at__date']: item['count'] for item in attempts_last_week}

    for i in range(7):
        day = today - timezone.timedelta(days=6 - i)
        activity_labels.append(day.strftime('%d.%m'))
        activity_data.append(daily_attempts.get(day, 0))

    # --- График 2: Распределение баллов по группам (0-25%, 26-50% и т.д.) ---
    percentage_expression = ExpressionWrapper(
        (F('score') * 100.0) / F('total_questions'),
        output_field=FloatField()
    )
    attempts_with_percentage = TestAttempt.objects.filter(
        survey=survey, total_questions__gt=0
    ).annotate(percentage_score=percentage_expression)

    scores_distribution = attempts_with_percentage.aggregate(
        group1=Count('id', filter=Q(percentage_score__gte=0, percentage_score__lte=25)),
        group2=Count('id', filter=Q(percentage_score__gt=25, percentage_score__lte=50)),
        group3=Count('id', filter=Q(percentage_score__gt=50, percentage_score__lte=75)),
        group4=Count('id', filter=Q(percentage_score__gt=75, percentage_score__lte=100)),
    )
    distribution_data = [
        scores_distribution.get('group1', 0),
        scores_distribution.get('group2', 0),
        scores_distribution.get('group3', 0),
        scores_distribution.get('group4', 0),
    ]

    return JsonResponse({
        'attempts_activity_chart': {
            'labels': activity_labels,
            'data': activity_data
        },
        'scores_distribution_chart': {
            'labels': ['0-25%', '26-50%', '51-75%', '76-100%'],
            'data': distribution_data
        }
    })


def solving_tests_promo(request):
    return render(request, 'landings/solving-tests.html')


def teachers_promo(request):
    return render(request, 'landings/teachers.html')


def medicine_promo(request):
    return render(request, 'landings/medicine.html')


@login_required
def page_history_surveys(request):
    try:
        surveys_data = get_all_surveys(request, page=1)

        context = {
            'page_title': 'Предыдущие тесты',
            'surveys_data': surveys_data['results'],
            'username': get_username(request),
            'paginator': surveys_data['paginator'],
        }
        tracer_l.info(f"{request.user.username} --- loaded surveys page 1")

    except Exception as fatal:
        context = {
            'page_title': 'Предыдущие тесты',
            'username': get_username(request)
        }
        tracer_l.error(f"{request.user.username} --- {fatal}")

    return render(request, 'askify_service/history.html', context)


@login_required
def api_get_history(request):
    surveys_data = get_all_surveys(request, page=1)
    tracer_l.info(f"{request.user.username} --- loaded surveys page 1")
    return JsonResponse({'data': surveys_data['results']})


@login_required
def load_more_surveys(request):
    if request.method == "GET" and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            page_number = int(request.GET.get('page', 2))
            surveys_data = get_all_surveys(request, page=page_number)

            surveys_list = [
                {
                    'survey_id': survey_id,
                    'title': survey['title'],
                    'update': survey['update'],
                    'tokens': survey['tokens']
                }
                for survey_id, survey in surveys_data['results'].items()
            ]

            has_next = surveys_data['page_obj'].has_next()
            return JsonResponse({
                'surveys': surveys_list,
                'has_next': has_next,
                'next_page': page_number + 1 if has_next else None,
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def drop_survey(request, survey_id):
    survey_obj = Survey.objects.filter(survey_id=uuid.UUID(survey_id)).first()

    if survey_obj and (survey_obj.id_staff == get_staff_id(request)):
        try:
            UserAnswers.objects.filter(survey_id=uuid.UUID(survey_id)).delete()
            TestAttempt.objects.filter(survey__survey_id=uuid.UUID(survey_id)).delete()
            survey_obj.delete()
            tracer_l.info(f"{request.user.username} [ DELETE OK ]")
        except Exception as pass_fail:
            tracer_l.info(f"warn: {request.user.username} {pass_fail}")
        return redirect('history')

    else:
        return JsonResponse({'error': 'No.'})


class ManageTokensLimits:
    def __init__(self, id_staff):
        self.id_staff = id_staff

    def get_usage_tokens(self) -> int:
        staff_id = self.id_staff

        subscription_active = Subscription.objects.get(staff_id=staff_id)
        plan_name = subscription_active.plan_name

        total_used = TokensUsed.objects.filter(id_staff=staff_id).aggregate(
            total_survey_tokens=Sum('tokens_survey_used'),
            total_feedback_tokens=Sum('tokens_feedback_used')
        )

        _total_used = (total_used['total_survey_tokens'] or 0) + (
                total_used['total_feedback_tokens'] or 0)

        if plan_name.lower() == 'стартовый':
            return _total_used
        else:
            today = timezone.now().date()
            tokens_used_today = TokensUsed.objects.filter(id_staff=staff_id, created_at__date=today).aggregate(
                total_survey_tokens=Sum('tokens_survey_used'),
                total_feedback_tokens=Sum('tokens_feedback_used')
            )

            total_used_today = (tokens_used_today['total_survey_tokens'] or 0) + (
                    tokens_used_today['total_feedback_tokens'] or 0)

            return total_used_today

    def get_tests_used_today(self) -> int:
        """
        Возвращает количество тестов, созданных текущим staff_id за сегодня.
        """
        today = timezone.now().date()

        tests_created_today = Survey.objects.filter(
            id_staff=self.id_staff,
            created_at__date=today
        ).count()

        return tests_created_today

    @staticmethod
    def check_token_limits(token_used, token_limit) -> bool:
        if token_used >= token_limit:
            return True
        return False


@sync_to_async
def get_active_api_key(purpose: str):
    return APIKey.objects.filter(purpose=purpose, is_active=True).first()


@sync_to_async
def create_api_key_usage(api_key_id, staff_id, purpose):
    APIKeyUsage.objects.create(
        api_key_id=api_key_id,
        staff_id=staff_id,
        purpose=purpose
    )


# @method_decorator(login_required, name='dispatch')
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(check_blocked, name='dispatch')
# @method_decorator(subscription_required, name='dispatch')
class ManageSurveysView(View):
    async def post(self, request):
        if request.method == 'POST':
            request_from_user = json.loads(request.body)
            question_count = request_from_user['questions']
            text_from_user = request_from_user['text']

            tracer_l.debug(f"{request.user.username} --- question_count: {question_count} text_from_user: {text_from_user}")

            if question_count.isdigit():
                if int(question_count) > 15 or int(question_count) < 0:
                    return JsonResponse({'error': 'Недоступное кол-во вопросов :('}, status=400)
            else:
                return JsonResponse({'error': 'Кол-во вопросов должно быть число'}, status=400)

            staff_id = get_staff_id(request)
            subscription_object = Subscription.objects.get(staff_id=staff_id)
            plan_name = subscription_object.plan_name

            tests_count_limit = get_daily_test_limit(plan_name)

            # Получение кол-ва использованных токенов
            manage_tokens_limits = ManageTokensLimits(staff_id)
            total_used_per_period = manage_tokens_limits.get_tests_used_today()
            tracer_l.debug(f"{request.user.username} --- total_used_per_period: {total_used_per_period}")

            if plan_name.lower() == 'стартовый':
                if total_used_per_period >= tests_count_limit:
                    return JsonResponse({
                        'error': 'Ваш лимит тестов на тарифе "Стартовый" исчерпан.'},
                        status=429
                    )
            else:
                if total_used_per_period >= tests_count_limit:
                    return JsonResponse({
                        'error': 'Лимит по созданию тестов исчерпан :(\n\nОзнакомьтесь с тарифами на странице профиля.'
                    }, status=429)

            if subscription_object.check_sub_status() != 'active':
                return JsonResponse({
                    'error': 'Ваша подписка закончилась :(\n\nОзнакомьтесь с тарифами на странице профиля.'
                }, status=429)

            try:
                tracer_l.debug(f"{request.user.username} --- GEN STAAAART")
                start_time = time.perf_counter()

                manage_generate_surveys_text = ManageGenerationSurveys(request, text_from_user, question_count)
                generated_text = await manage_generate_surveys_text.github_gpt(await get_active_api_key('SURVEY'))

                if generated_text.get('success'):
                    tokens_used = generated_text.get('tokens_used')
                    cleaned_generated_text = generated_text.get('generated_text')
                    tracer_l.debug(f"{request.user.username} --- generated_text: {generated_text}")
                    end_time = time.perf_counter()
                    response_time_ms = int((end_time - start_time) * 1000)
                else:
                    return JsonResponse({'error': f'Произошла ошибка :( {generated_text}'}, status=429)

            except Exception as fail:
                tracer_l.error(f"{request.user.username} --- {fail}")
                return JsonResponse({'error': 'Опаньки :(\n\nК сожалению, не удалось составить тест'}, status=400)

            # try:
            new_survey_id = uuid.uuid4()

            survey = Survey(
                survey_id=new_survey_id,
                title=cleaned_generated_text['title'],
                id_staff=get_staff_id(request),
                model_name=generated_text.get('model_used', '')
            )
            survey.save_questions(cleaned_generated_text['questions'])
            survey.save()

            # _tokens_used = TokensUsed(
            #     id_staff=get_staff_id(request),
            #     tokens_survey_used=tokens_used,
            # )
            # _tokens_used.save()

            api_key_manage = await get_active_api_key('SURVEY')
            APIKeyUsage.objects.create(
                api_key=api_key_manage,
                success=True,
                response_time_ms=response_time_ms
            )

            tracer_l.info(f'{request.user.username} --- success save to DB')

            return JsonResponse({'survey': cleaned_generated_text, 'survey_id': f"{new_survey_id}"}, status=200)
            # except Exception as fail:
            #     user = await sync_to_async(str)(request.user.username)
            #     tracer_l.tracer_charge(
            #         'INFO', user, ManageSurveysView.post.__name__,
            #         "error in save to DB", f"{fail}")
            #     return JsonResponse(
            #         {'error': 'Ошибочка :(\n\nПожалуйста, попробуйте позже'}, status=400)

        tracer_l.warning(f'{request.user.username} --- Invalid request method: code 400')
        return JsonResponse({'error': 'Invalid request method'}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class GenerationSurveysView(View):
    async def post(self, request):
        try:
            body = await sync_to_async(request.body.decode)('utf-8')
            request_from_user = json.loads(body)
            question_count = str(request_from_user['questions'])
            text_from_user = request_from_user['text']

            if not (0 < int(question_count) <= 5):
                return JsonResponse({'error': 'Допустимо от 1 до 5 вопросов'}, status=400)

            client_ip = get_client_ip(request)
            hashed_ip = hash_data(client_ip)

            # !!! ИСПРАВЛЕНИЕ: Обертываем синхронную ORM-операцию
            existing_survey = await sync_to_async(Survey.objects.filter(title=text_from_user).first)()
            if existing_survey:
                tracer_l.info(
                    f'{request.user.username or hashed_ip} --- Survey already exists: {existing_survey.survey_id}')
                return JsonResponse({
                    'survey_id': str(existing_survey.survey_id),
                    'redirect_url': f'/c/{existing_survey.survey_id}/'
                }, status=200)

            try:
                auth_user = await sync_to_async(AuthUser.objects.get)(hash_user_id=client_ip)
            except Exception as fail:
                auth_user = await sync_to_async(AuthUser.objects.create)(
                    username=f"{hashed_ip}_{uuid.uuid4().hex[:6]}",
                    hash_user_id=client_ip
                )

            staff_id = auth_user.id_staff

            try:
                subscription_object = await sync_to_async(Subscription.objects.filter(staff_id=staff_id).first)()
                if subscription_object:
                    plan_name = subscription_object.plan_name
                    token_limit = get_token_limit(plan_name)
            except Exception as sub_e:
                tracer_l.warning(f'{staff_id} --- Could not retrieve subscription details: {sub_e}')

            surveys_count = await sync_to_async(Survey.objects.filter(id_staff=staff_id).count)()
            tracer_l.debug(f'{staff_id} --- surveys_count: {surveys_count}')

            if surveys_count > 1:
                return JsonResponse(
                    {'error': 'Лимит исчерпан :(\n\nХочешь ещё? Зарегистрируйся, и дадим 10 тестов в подарок.'})

            manage_generate_surveys_text = ManageGenerationSurveys(request, text_from_user, question_count)
            start_time = time.perf_counter()

            # if DEBUG:
            #     generated_text_data = {
            #         'success': True, 'generated_text': {
            #             "title": "Тест по процессорам Intel",
            #             "questions": [
            #                 {
            #                     "question": "Как называется технология Intel, которая позволяет процессору автоматически увеличивать тактовую частоту при необходимости?",
            #                     "options": ["Hyper-Threading", "Turbo Boost", "Intel Optane", "Quick Sync",
            #                                 "Turbo Boost"],
            #                     "correct_answer": "Turbo Boost"
            #                 },
            #                 {
            #                     "question": "Какая архитектура процессоров Intel была представлена в 2021 году и сочетает производительные и энергоэффективные ядра?",
            #                     "options": ["Rocket Lake", "Alder Lake", "Ice Lake", "Tiger Lake", "Alder Lake"],
            #                     "correct_answer": "Alder Lake"
            #                 }
            #             ]
            #         }, 'tokens_used': 200,
            #     }
            # else:
            generated_text_data = await manage_generate_surveys_text.github_gpt(await get_active_api_key('SURVEY'))

            end_time = time.perf_counter()

            if not generated_text_data.get('success'):
                tracer_l.error(f'{staff_id} --- Generation error: {generated_text_data.get("message")}')
                return JsonResponse({
                    'error': f'Произошла ошибка генерации: {generated_text_data.get("message", "Неизвестная ошибка")}'
                }, status=500)

            response_time_ms = int((end_time - start_time) * 1000)

            new_survey_id = uuid.uuid4()
            survey = Survey(
                survey_id=new_survey_id,
                title=generated_text_data['generated_text']['title'],
                id_staff=staff_id,
                model_name=generated_text_data.get('model_used', '')
            )

            await sync_to_async(survey.save_questions)(generated_text_data['generated_text']['questions'])
            await sync_to_async(survey.save)()

            _tokens_used = TokensUsed(
                id_staff=staff_id,
                tokens_survey_used=generated_text_data['tokens_used']
            )
            await sync_to_async(_tokens_used.save)()

            # !!! ИСПРАВЛЕНИЕ: Обертываем синхронную ORM-операцию
            api_key_manage = await sync_to_async(APIKey.objects.filter(purpose='SURVEY', is_active=True).first)()

            # !!! ИСПРАВЛЕНИЕ: Обертываем синхронную ORM-операцию
            if api_key_manage:
                await sync_to_async(APIKeyUsage.objects.create)(
                    api_key=api_key_manage,
                    success=True,
                    response_time_ms=response_time_ms
                )
            else:
                tracer_l.warning(f'{staff_id} --- APIKey для SURVEY не найден для логирования использования.')

            tracer_l.info(f'{staff_id} --- Успешная генерация: {new_survey_id}')

            return JsonResponse({
                'survey': generated_text_data['generated_text'],
                'survey_id': str(new_survey_id),
                'redirect_url': f'/c/{new_survey_id}/'
            }, status=200)

        except json.JSONDecodeError:
            tracer_l.error(f'{request.user.username or get_client_ip(request)} --- Invalid JSON in request body.')
            return JsonResponse({'error': 'Невалидный JSON'}, status=400)
        except Exception as e:
            tracer_l.critical(f"FATAL ERROR in GenerationSurveysView: {e}", exc_info=True)
            return JsonResponse({'error': 'Внутренняя ошибка сервера'}, status=500)


def get_demo_tests(request):
    client_ip = get_client_ip(request)

    user = AuthUser.objects.filter(hash_user_id=client_ip).first()

    if user:
        surveys = Survey.objects.filter(id_staff=user.id_staff)

        tests = []
        for survey in surveys:
            tests.append({
                'title': survey.title,
                'url_link': f'/survey/{survey.survey_id}/download/',
                'survey_id': survey.survey_id
            })

        return JsonResponse({'tests': tests})

    return JsonResponse({'tests': {}})


def toggle_answers(request, survey_id):
    if request.method == 'POST':
        try:
            survey_data = Survey.objects.filter(survey_id=survey_id).first()
            client_ip = get_client_ip(request)
            staff_id = get_staff_id(request)

            if not staff_id:
                staff_id = AuthUser.objects.filter(hash_user_id=client_ip).first()

            if staff_id:

                survey_data.show_answers = not survey_data.show_answers
                survey_data.save()

                return JsonResponse({
                    'status': 'success',
                    'show_answers': survey_data.show_answers
                })

            return JsonResponse({'status': 'error', 'message': 'Not authorized'}, status=403)

        except Survey.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Survey not found'}, status=404)


@login_required
def get_all_surveys(request, page=1, per_page=5):
    staff_id = get_staff_id(request)
    if staff_id is None:
        return {}

    surveys_queryset = Survey.objects.filter(id_staff=staff_id).order_by('-created_at')

    paginator = Paginator(surveys_queryset, per_page)
    try:
        surveys_page = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        surveys_page = paginator.page(1)

    # Предзагружаем все токены, чтобы не лупить запросы по одному
    tokens_entries = TokensUsed.objects.filter(id_staff=staff_id)

    results = {}
    time_margin = timedelta(seconds=5)

    from django.db.models.functions import Abs, Extract

    for survey in surveys_page.object_list:
        if not DEBUG:
            nearby_tokens = (
                tokens_entries
                .filter(created_at__range=(survey.updated_at - time_margin, survey.updated_at + time_margin))
                .annotate(
                    time_diff=ExpressionWrapper(
                        Abs(Extract(F('created_at') - survey.updated_at, 'epoch')),
                        output_field=DurationField()
                    )
                )
                .order_by('time_diff')
                .first()
            )
        else:
            nearby_tokens = (
                tokens_entries
                .filter(created_at__range=(survey.updated_at - time_margin, survey.updated_at + time_margin))
                .annotate(
                    time_diff=ExpressionWrapper(
                        Abs(F('created_at') - survey.updated_at),
                        output_field=DurationField()
                    )
                )
                .order_by('time_diff')
                .first()
            )

        tokens_used = nearby_tokens.tokens_survey_used if nearby_tokens else None

        results[str(survey.survey_id)] = {
            'title': survey.title if len(survey.title) < 32 else survey.title[:32] + '...',
            'update': survey.updated_at.strftime('%d.%m.%Y'),
            'create': survey.created_at.strftime('%d.%m.%Y'),
            'tokens': tokens_used
        }

    return {
        'results': results,
        'paginator': paginator,
        'page_obj': surveys_page
    }


# @method_decorator(login_required, name='dispatch')
# @method_decorator(subscription_required, name='dispatch')
class FileUploadView(View):
    async def post(self, request):
        if not request.user.is_authenticated:
            return HttpResponseForbidden()

        staff_id = get_staff_id(request)

        form = FileUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            tracer_l.error('Загружен невалидный файл')
            return JsonResponse({'errors': form.errors}, status=400)

        available_file_types = [
            'application/pdf', 'text/plain', 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ]

        question_count = form.cleaned_data['question_count']
        uploaded_file = form.cleaned_data['file']

        tracer_l.debug(f'question_count {question_count} uploaded_file {uploaded_file}')

        if uploaded_file.content_type not in available_file_types:
            tracer_l.error('Недопустимый файл')
            return JsonResponse({'error': 'Недопустимый файл'}, status=400)

        if uploaded_file.size > 5 * 1024 * 1024:
            tracer_l.error('No file provided')
            return JsonResponse({'error': 'Файл слишком большой. Максимальный размер: 5 МБ'}, status=400)

        data = self.read_file_data(uploaded_file)
        if data == -1:
            tracer_l.error('Файл не является допустимым документом')
            return JsonResponse({'error': 'Файл не является допустимым документом'})

        subscription_object = await sync_to_async(Subscription.objects.filter(staff_id=staff_id).first)()
        if subscription_object.check_sub_status() != 'active':
            return JsonResponse({
                'error': 'Ваша подписка закончилась :(\n\nОзнакомьтесь с тарифами на странице профиля.'
            }, status=400)

        try:
            prompts_tokens = 479
            num_tokens = count_tokens(data) + prompts_tokens
            tracer_l.info(f"Кол-во токенов в файле: {num_tokens}")
            if num_tokens > 8000:
                tracer_l.error(f'Слишком большой объем текста в файле ({num_tokens} токенов). ')
                error_message = (
                    f'Слишком большой объем текста в файле ({num_tokens} токенов). '
                    f'Максимально допустимо {8000} токенов. '
                    'Пожалуйста, сократите документ.'
                )
                return JsonResponse({'error': error_message}, status=400)
        except Exception as e:
            tracer_l.error(f'Error counting tokens: {e}')
            # return JsonResponse({'error': 'Не удалось обработать текст файла.'}, status=500)

        tracer_l.debug("--- ТЕСТ ГЕНЕРИРУЕТСЯ ---")
        try:
            tracer_l.debug("Начало генерации")
            manage_generate_surveys_text = ManageGenerationSurveys(request, data, f'{question_count}')
            generated_text = await manage_generate_surveys_text.github_gpt(await get_active_api_key('SURVEY'))
            tracer_l.debug("Завершение генерации")

            if generated_text.get('success'):
                tokens_used = generated_text.get('tokens_used')
                cleaned_generated_text = generated_text.get('generated_text')
            else:
                tracer_l.critical(f'Произошла ошибка: {generated_text.get("message")}')
                return JsonResponse({'error': f'Произошла ошибка: {generated_text.get("message")}'}, status=429)
        except Exception as fatal:
            return JsonResponse({'error': f'Не удалось выполнить запрос: {fatal}'}, status=400)

        try:
            with transaction.atomic():
                staff_id = get_staff_id(request)
                new_survey_id = uuid.uuid4()

                survey = Survey(
                    survey_id=new_survey_id,
                    title=cleaned_generated_text['title'],
                    id_staff=staff_id
                )
                await sync_to_async(survey.save_questions)(cleaned_generated_text['questions'])
                await sync_to_async(survey.save)()

                _tokens_used = TokensUsed(
                    id_staff=staff_id,
                    tokens_survey_used=tokens_used
                )
                await sync_to_async(_tokens_used.save)()

                api_key_manage = await sync_to_async(APIKey.objects.filter(purpose='SURVEY', is_active=True).first)()
                if api_key_manage:
                    await sync_to_async(APIKeyUsage.objects.create)(
                        api_key=api_key_manage,
                        success=True,
                    )

        except Exception as fatal:
            tracer_l.error(f"Failed to create survey: {fatal}")
            return JsonResponse({'error': 'Произошла ошибка при сохранении теста'}, status=500)

        tracer_l.info(f'Успешно создан тест: {new_survey_id}')
        return JsonResponse({'success': True, 'message': 'Success create survey', 'survey_id': f"{new_survey_id}"})

    async def get(self, request):
        if not request.user.is_authenticated:
            return HttpResponseForbidden()
        return JsonResponse({'error': True, 'message': 'Invalid method'})

    def read_file_data(self, uploaded_file):
        full_text = ""
        ext = os.path.splitext(str(uploaded_file.name))[1].lower()

        read_symbols_count = 2 ** 13

        if ext == '.pdf':
            try:
                reader = PyPDF2.PdfReader(uploaded_file)
                for page in reader.pages:
                    if text := page.extract_text():
                        full_text += text.strip() + "\n"
                return full_text[:read_symbols_count]
            except Exception as e:
                print(f"Error reading PDF: {e}")
                return -1

        elif ext == '.txt':
            try:
                uploaded_file.seek(0)
                encoding = chardet.detect_encoding(uploaded_file)
                return uploaded_file.read().decode(encoding)[:read_symbols_count]
            except Exception as e:
                print(f"Error reading TXT: {e}")
                return -1

        elif ext in ['.doc', '.docx']:
            try:
                with NamedTemporaryFile(delete=True, suffix=ext) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp.seek(0)
                    return self.extract_text_from_word(tmp.name)[:read_symbols_count]
            except Exception as e:
                print(f"Error reading Word document: {e}")
                return -1

        return -1

    def detect_encoding(file_obj):
        """ Определение кодировки текстовых файлов """
        sample = file_obj.read(1024)
        file_obj.seek(0)
        result = chardet.detect(sample)
        return result['encoding'] or 'utf-8'

    def extract_text_from_word(self, file_path):
        """ Извлечение текста из Word документов """
        try:
            if file_path.endswith('.docx'):
                doc = docx.Document(file_path)
                return "\n".join([para.text for para in doc.paragraphs])

            elif file_path.endswith('.doc'):
                return textract.process(file_path).decode('utf-8', 'ignore')
        except Exception as e:
            print(f"Word extraction error: {e}")
            return ""


@method_decorator(login_required, name='dispatch')
@method_decorator(subscription_required, name='dispatch')
# @method_decorator(sync_to_async, name='dispatch')
class TakeSurvey(View):
    def post(self, request, survey_id):
        survey_id = uuid.UUID(survey_id)
        survey = get_object_or_404(Survey, survey_id=survey_id)
        questions = json.loads(survey.questions)

        user_answers = [request.POST.get(f'answers_{i + 1}') for i in range(len(questions))]

        if None in user_answers:
            context = {
                'survey': survey,
                'questions': questions,
                'error': 'Пожалуйста, ответьте на все вопросы.',
                'username': get_username(request)
            }
            return render(request, 'survey.html', context)

        survey_obj_user_answer = UserAnswers.objects.filter(survey_id=survey_id)

        if survey_obj_user_answer.exists():
            survey_obj_user_answer.delete()

        user_answers_dict = {f'question_{i + 1}': user_answers[i] for i in range(len(user_answers))}
        user_answers_list = []
        correct_count = 0

        for index_q, question in enumerate(questions):
            selected_answer = user_answers[index_q]
            is_correct = selected_answer == question['correct_answer']
            correct_count += 1 if is_correct else 0

            user_answers_json = json.dumps(user_answers_dict)

            UserAnswers.objects.update_or_create(
                survey_id=survey_id,
                selected_answer=selected_answer,
                defaults={
                    'scored_points': 1 if is_correct else 0,
                    'total_points': len(questions),
                    'user_answers': user_answers_json,
                    'id_staff': get_staff_id(request)
                }
            )

            user_answers_list.append(
                f"\n\nВопрос: {question['question']}\n"
                f"Правильный ответ: {question['correct_answer']}\n"
                f"Ответ пользователя: {selected_answer}"
            )

        subscription = Subscription.objects.get(staff_id=get_staff_id(request))

        subs_level = get_subscription_level(request)

        status = subscription.check_sub_status()
        tests_count_limit = get_daily_test_limit(subscription.plan_name) if status == 'active' else 0

        if (status == 'active') and (tests_count_limit > 0) and (subs_level > 1):
            generation_models_control = GenerationModelsControl()
            ai_feedback = generation_models_control.get_feedback_001(
                f"Список вопросов и моих ответов: {user_answers_list}.\n"
                f"Набрано балов: {correct_count} из {len(user_answers)}"
            )

            if ai_feedback.get('success'):
                feedback_obj = FeedbackFromAI.objects.filter(survey_id=survey_id)
                if feedback_obj.exists():
                    feedback_obj.delete()

                FeedbackFromAI.objects.create(
                    survey_id=survey_id,
                    id_staff=get_staff_id(request),
                    feedback_data=ai_feedback.get('generated_text'),
                    model_name=ai_feedback.get('model_used', '')
                )

                TokensUsed.objects.create(
                    id_staff=get_staff_id(request),
                    tokens_feedback_used=ai_feedback.get('tokens_used', '')
                )

                api_key_manage = APIKey.objects.filter(purpose='FEEDBACK', is_active=True).first()
                APIKeyUsage.objects.create(
                    api_key=api_key_manage,
                    success=True
                )

        context = {
            'score': correct_count, 'total': user_answers, 'survey_id': survey_id,
            'subscription_level': get_subscription_level(request),
            'username': get_username(request),
        }

        return render(request, 'result.html', context)

    def get(self, request, survey_id):
        survey_id = uuid.UUID(survey_id)
        survey = get_object_or_404(Survey, survey_id=survey_id)
        questions = json.loads(survey.questions)

        subscription = Subscription.objects.get(staff_id=get_staff_id(request))

        context = {
            'page_title': f'Прохождение теста – {survey.title}',
            'survey': survey,
            'questions': questions,
            'survey_title': survey.title,
            'username': request.user.username if request.user.is_authenticated else None,
        }
        return render(request, 'survey.html', context)


# @subscription_required
@login_required
def result_view(request, survey_id):
    survey = get_object_or_404(Survey, survey_id=survey_id)
    questions_data = survey.get_questions()

    last_attempt = UserAnswers.objects.filter(
        survey_id=survey_id,
        id_staff=get_staff_id(request)
    ).order_by('-created_at').first()

    if not last_attempt:
        selected_answers_dict = {}
    else:
        selected_answers_dict = last_attempt.get_user_answers()

    processed_questions = []
    correct_answers_count = 0

    for index, question in enumerate(questions_data):
        answer_key = f"question_{index + 1}"
        user_answer = selected_answers_dict.get(answer_key)
        question['user_answer'] = user_answer

        if user_answer and user_answer == question.get('correct_answer'):
            correct_answers_count += 1

        processed_questions.append(question)

    score = correct_answers_count
    total = len(questions_data)

    feedback_text = ''
    model_name = ''
    try:
        feedback_obj = FeedbackFromAI.objects.filter(survey_id=survey_id).first()
        if feedback_obj:
            feedback_text = markdown.markdown(feedback_obj.feedback_data)  # Упростил
            model_name = feedback_obj.model_name
    except Exception as fail:
        feedback_text = 'Не удалось получить обратную связь от ИИ :('
        tracer_l.warning(f'Нет фидбэка: {request.user.username} --- {fail}')

    subscription_db = Subscription.objects.get(staff_id=get_staff_id(request))
    subscription_check = SubscriptionCheck()
    subscription_level = subscription_check.get_subscription_level(subscription_db.plan_name)
    status = subscription_db.check_sub_status()

    context = {
        'page_title': f'Результаты прохождения теста – {survey.title}',
        'title': survey.title,
        'score': score,
        'total': total,
        'survey_id': survey_id,
        'questions': processed_questions,
        'username': request.user.username if request.user.is_authenticated else None,
        'feedback_text': feedback_text,
        'subscription_level': subscription_level,
        'model_name': f"Сгенерировано {format_model_name(model_name)}" if model_name else "",
        'subs_active': status == 'active'
    }

    return render(request, 'result.html', context)


def download_results_pdf(request, survey_id):
    try:
        from django.contrib.staticfiles import finders

        font_path_medium = finders.find('fonts/Merriweather-Medium.ttf')
        font_path_bold = finders.find('fonts/OpenSans-Bold.ttf')
        font_signature = finders.find('fonts/Unbounded-Medium.ttf')

        pdfmetrics.registerFont(TTFont('Manrope Medium', font_path_medium))
        pdfmetrics.registerFont(TTFont('Manrope Bold', font_path_bold))
        pdfmetrics.registerFont(TTFont('Unbounded Medium', font_signature))
        logging.info("Шрифты ReportLab успешно зарегистрированы.")
    except Exception as e:
        logging.error(
            f"Ошибка при регистрации шрифтов ReportLab: {e}. Убедитесь, что файлы шрифтов находятся по указанным путям ('fonts/'). PDF может быть нечитаемым.")

    try:
        survey = Survey.objects.get(survey_id=survey_id)
        staff_id = get_staff_id(request)

        user_answers_instances = UserAnswers.objects.filter(
            survey_id=survey_id,
            id_staff=staff_id
        ).order_by('created_at')

        if not user_answers_instances.exists():
            return HttpResponse("Вы не проходили этот тест или ответы не найдены.", status=404)

        last_user_answer_instance = user_answers_instances.last()

        score = sum(answer.scored_points for answer in user_answers_instances)

        original_questions_from_survey = survey.get_questions()
        total_questions = len(original_questions_from_survey)

        questions_for_pdf = []

        user_answer_data_map = {}
        for ua_instance in user_answers_instances:
            try:
                user_answer_json_data = ua_instance.user_answers
                if isinstance(user_answer_json_data, str):
                    user_answer_json_data = json.loads(user_answer_json_data)

                if isinstance(user_answer_json_data, dict):
                    if 'question' in user_answer_json_data and 'selected_answer' in user_answer_json_data:
                        user_answer_data_map[user_answer_json_data['question']] = {
                            'selected_answer': user_answer_json_data.get('selected_answer'),
                            'is_correct': user_answer_json_data.get('is_correct', False),
                            'scored_points': ua_instance.scored_points
                        }

            except (json.JSONDecodeError, TypeError) as e:
                tracer_l.error(
                    f"Ошибка парсинга JSON из user_answers для UserAnswers ID {ua_instance.id}: {ua_instance.user_answers} - {e}")

        for i, original_q in enumerate(original_questions_from_survey):
            q_text = original_q.get('question', f'Вопрос {i + 1} без текста')
            q_options = original_q.get('options', [])
            q_correct_answer = original_q.get('correct_answer', 'Нет правильного ответа')

            selected_answer_text = "Нет ответа"
            is_correct_user_answer = False

            matched_answer_info = user_answer_data_map.get(q_text)

            if matched_answer_info:
                selected_answer_text = matched_answer_info['selected_answer']
                is_correct_user_answer = matched_answer_info['is_correct']
            else:
                if last_user_answer_instance and isinstance(last_user_answer_instance.user_answers, dict):
                    question_key_by_index = f'question_{i + 1}'
                    if question_key_by_index in last_user_answer_instance.user_answers:
                        selected_answer_text = last_user_answer_instance.user_answers[question_key_by_index]
                        is_correct_user_answer = (selected_answer_text == q_correct_answer)
                elif last_user_answer_instance and isinstance(last_user_answer_instance.user_answers, str):
                    try:
                        parsed_answers = json.loads(last_user_answer_instance.user_answers)
                        if isinstance(parsed_answers, dict):
                            question_key_by_index = f'question_{i + 1}'
                            if question_key_by_index in parsed_answers:
                                selected_answer_text = parsed_answers[question_key_by_index]
                                is_correct_user_answer = (selected_answer_text == q_correct_answer)
                    except (json.JSONDecodeError, TypeError):
                        pass

            questions_for_pdf.append({
                'question_text': q_text,
                'options': q_options,
                'correct_answer_text': q_correct_answer,
                'selected_answer': selected_answer_text,
                'is_correct_user_answer': is_correct_user_answer,
            })

        feedback_obj = FeedbackFromAI.objects.filter(survey_id=survey_id).first()
        story = []
        model_name_ai = ''

        # --- ИНИЦИАЛИЗАЦИЯ СТИЛЕЙ REPORTLAB ---
        styles = getSampleStyleSheet()

        styles['Normal'].fontName = 'Manrope Medium'
        styles['Normal'].fontSize = 10
        styles['Normal'].leading = 14
        styles['Normal'].alignment = TA_LEFT
        styles['Normal'].textColor = colors.black

        styles.add(ParagraphStyle(name='h1_feedback',
                                  parent=styles['Normal'],
                                  fontName='Manrope Bold',
                                  fontSize=16,
                                  leading=18,
                                  alignment=TA_LEFT,
                                  spaceBefore=15,
                                  spaceAfter=8,
                                  textColor=colors.black))
        styles.add(ParagraphStyle(name='h2_feedback',
                                  parent=styles['Normal'],
                                  fontName='Manrope Bold',
                                  fontSize=14,
                                  leading=16,
                                  alignment=TA_LEFT,
                                  spaceBefore=12,
                                  spaceAfter=6,
                                  textColor=colors.black))
        styles.add(ParagraphStyle(name='h3_feedback',
                                  parent=styles['Normal'],
                                  fontName='Manrope Bold',
                                  fontSize=12,
                                  leading=14,
                                  alignment=TA_LEFT,
                                  spaceBefore=10,
                                  spaceAfter=5,
                                  textColor=colors.black))

        feedback_text_style = ParagraphStyle('FeedbackTextStyle',
                                             parent=styles['Normal'],
                                             fontName='Manrope Medium',
                                             fontSize=10,
                                             leading=14,
                                             spaceAfter=5,
                                             allowWidows=1,
                                             allowOrphans=1
                                             )

        title_style = ParagraphStyle('TitleStyle',
                                     parent=styles['Normal'],
                                     fontName='Manrope Bold',
                                     fontSize=22,
                                     leading=26,
                                     alignment=TA_LEFT,
                                     spaceAfter=15
                                     )
        subtitle_style = ParagraphStyle('SubtitleStyle',
                                        parent=styles['Normal'],
                                        fontName='Manrope Medium',
                                        fontSize=10,
                                        leading=12,
                                        alignment=TA_LEFT,
                                        spaceAfter=5
                                        )
        score_style = ParagraphStyle('ScoreStyle',
                                     parent=styles['Normal'],
                                     fontName='Manrope Bold',
                                     fontSize=16,
                                     leading=18,
                                     alignment=TA_LEFT,
                                     spaceAfter=25
                                     )

        question_style = ParagraphStyle('QuestionStyle',
                                        parent=styles['Normal'],
                                        fontName='Manrope Bold',
                                        fontSize=12,
                                        leading=14,
                                        spaceBefore=20,
                                        spaceAfter=8
                                        )
        option_header_style = ParagraphStyle('OptionHeaderStyle',
                                             parent=styles['Normal'],
                                             fontName='Manrope Medium',
                                             fontSize=10,
                                             leading=12,
                                             spaceAfter=5,
                                             leftIndent=10
                                             )
        option_style_base = ParagraphStyle('OptionStyleBase',
                                           parent=styles['Normal'],
                                           fontName='Manrope Medium',
                                           fontSize=11,
                                           leading=13,
                                           leftIndent=20,
                                           spaceAfter=3,
                                           textColor=colors.black
                                           )

        option_style_correct_user = option_style_base
        option_style_incorrect_user = option_style_base
        option_style_correct_answer = option_style_base
        option_style_default = option_style_base

        feedback_header_style = ParagraphStyle('FeedbackHeaderStyle',
                                               parent=styles['Normal'],
                                               fontName='Manrope Bold',
                                               fontSize=14,
                                               leading=16,
                                               spaceBefore=30,
                                               spaceAfter=10
                                               )

        model_name_style = ParagraphStyle('ModelNameStyle',
                                          parent=styles['Normal'],
                                          fontName='Manrope Medium',
                                          fontSize=8,
                                          leading=10,
                                          alignment=TA_RIGHT,
                                          spaceAfter=20
                                          )

        footer_style = ParagraphStyle('FooterStyle',
                                      parent=styles['Normal'],
                                      fontName='Unbounded Medium',
                                      fontSize=9,
                                      alignment=TA_LEFT
                                      )

        # --- СОЗДАНИЕ ЭЛЕМЕНТОВ PDF В STORY ---
        story.append(Paragraph(f"Результаты теста: «{survey.title}»", title_style))
        story.append(Paragraph(f"Пользователь: {get_username(request)}", subtitle_style))
        story.append(Paragraph(f"Тест пройден: {last_user_answer_instance.created_at.strftime('%d.%m.%Y %H:%M')}",
                               subtitle_style))
        story.append(Spacer(1, 10))
        percent = round((score / total_questions) * 100, 2)
        story.append(Paragraph(f"Результат: {score} из {total_questions} ({percent}%)", score_style))
        story.append(Spacer(1, 20))

        # --- Вопросы и ответы ---
        for i, q_data in enumerate(questions_for_pdf):
            story.append(Paragraph(f"Вопрос {i + 1}: {q_data['question_text']}", question_style))
            story.append(Spacer(1, 5))
            story.append(Paragraph("Варианты ответов:", option_header_style))
            story.append(Spacer(1, 5))

            for option in q_data['options']:
                display_option = option
                if option == q_data['selected_answer']:
                    if q_data['is_correct_user_answer']:
                        display_option = f"<b>[+] {display_option}</b> (Ваш верный ответ)"
                    else:
                        display_option = f"<b>[x] {display_option}</b> (Ваш неверный ответ)"
                elif option == q_data['correct_answer_text']:
                    if option != q_data['selected_answer']:
                        display_option = f"[*] {display_option} (Правильный ответ)"
                else:
                    display_option = f"[ ] {display_option}"

                story.append(Paragraph(display_option, option_style_base))
                story.append(Spacer(1, 3))
            story.append(Spacer(1, 15))

        # --- Фидбэк от ИИ ---
        if feedback_obj:
            feedback_text_raw = feedback_obj.feedback_data
            cleaned_feedback_raw = re.sub(r'think\s*', '', feedback_text_raw, flags=re.IGNORECASE).strip()
            feedback_html = markdown.markdown(cleaned_feedback_raw)
            soup = BeautifulSoup(feedback_html, 'html.parser')

            story.append(Paragraph("Обратная связь от ИИ:",
                                   feedback_header_style))  # Исправлено: добавляем Paragraph, а не стиль
            story.append(Spacer(1, 10))

            for tag in soup.children:
                if tag.name == 'p':
                    story.append(Paragraph(str(tag), feedback_text_style))
                    story.append(Spacer(1, 6))
                elif tag.name == 'ul' or tag.name == 'ol':
                    for li in tag.find_all('li'):
                        story.append(Paragraph(f"• {li.get_text()}", feedback_text_style))
                        story.append(Spacer(1, 3))
                    story.append(Spacer(1, 6))
                elif tag.name == 'h1':
                    story.append(Paragraph(tag.get_text(), styles['h1_feedback']))
                    story.append(Spacer(1, 8))
                elif tag.name == 'h2':
                    story.append(Paragraph(tag.get_text(), styles['h2_feedback']))
                    story.append(Spacer(1, 8))
                elif tag.name == 'h3':
                    story.append(Paragraph(tag.get_text(), styles['h3_feedback']))
                    story.append(Spacer(1, 6))

            model_name_ai = f"{'Сгенерировано ' + survey.model_name.upper().replace('O', 'o') if survey.model_name else ''}"
            story.append(Paragraph(model_name_ai, model_name_style))
            story.append(Spacer(1, 20))

        # --- Футер ---
        story.append(Paragraph(f"Сгенерировано в Летучке • {get_year_now()}", footer_style))

        # --- Генерация PDF ---
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                leftMargin=50, rightMargin=50,
                                topMargin=50, bottomMargin=50)

        doc.build(story)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        safe_title = re.sub(r'[^\w\s-]', '', survey.title).strip().replace(' ', '_')
        response['Content-Disposition'] = f'attachment; filename="letychka_result_{safe_title}.pdf"'
        return response

    except Survey.DoesNotExist:
        return HttpResponse("Тест не найден.", status=404)
    except Exception as e:
        tracer_l.exception(
            f"Критическая ошибка при генерации PDF результатов для survey_id={survey_id}, staff_id={staff_id}: {e}")
        return HttpResponse("Произошла критическая ошибка при генерации PDF. Пожалуйста, попробуйте позже.", status=500)


def get_is_creator(request, survey):
    survey_creator_id_staff = survey.id_staff

    current_user_id_staff = None

    client_ip = get_client_ip(request)
    anonymous_user = AuthUser.objects.filter(hash_user_id=client_ip).first()
    if anonymous_user:
        current_user_id_staff = anonymous_user.id_staff
    if survey.id_staff == get_staff_id(request):
        survey_creator_id_staff = current_user_id_staff

    is_creator = False
    if current_user_id_staff == survey_creator_id_staff:
        is_creator = True

    return is_creator


@csrf_exempt
def take_test(request, survey_id):
    """
    Отображает страницу прохождения теста.
    """
    survey = get_object_or_404(Survey, survey_id=survey_id)

    questions_list = survey.get_questions()
    random.shuffle(questions_list)

    author_username = AuthUser.objects.get(id_staff=survey.id_staff).username

    context = {
        'survey': survey,
        'questions_json': json.dumps(questions_list, ensure_ascii=False),
        'author': author_username if len(author_username) < 16 else 'Аноним',
        'page_title': survey.title,
        'is_creator': get_is_creator(request, survey)
    }
    return render(request, 'askify_service/take_test.html', context)


@csrf_exempt
def submit_answers(request, survey_id):
    """
    API-ручка, которая принимает ответы.
    """
    if request.method == 'POST':
        survey = get_object_or_404(Survey, survey_id=survey_id)
        data = json.loads(request.body)

        student_name = data.get('student_name', 'Аноним').strip()
        answers = data.get('answers', {})

        questions_data = {q['question']: q for q in survey.get_questions()}
        score = 0
        total_questions = len(questions_data)

        for q_text, student_answer in answers.items():
            if q_text in questions_data and student_answer == questions_data[q_text]['correct_answer']:
                score += 1

        TestAttempt.objects.create(
            survey=survey,
            student_name=student_name if student_name else "Аноним",
            answers_json=json.dumps(answers, ensure_ascii=False),
            score=score,
            total_questions=total_questions
        )
        tracer_l.info(f'USER {student_name} take {survey.title}')

        return JsonResponse({'success': True, 'score': score, 'total': total_questions})

    return JsonResponse({'error': 'Invalid request'}, status=400)


def preview_test(request, survey_id):
    if not is_valid_uuid(survey_id):
        context = {
            'not_found': True,
            'survey_id': None,
            'page_title': 'Тест не найден | Летучка',
        }
        return render(request, 'demo-view.html', context, status=404)

    survey = Survey.objects.filter(survey_id=survey_id).first()
    if (not survey) or (not is_valid_uuid(survey_id)):
        context = {
            'not_found': True,
            'page_title': 'Тест не найден | Летучка',
        }
        return render(request, 'demo-view.html', context, status=404)

    survey_creator_id_staff = survey.id_staff

    current_user_id_staff = None
    is_authenticated = request.user.is_authenticated

    # if is_authenticated:
    #     current_user_id_staff = get_staff_id(request)
    # else:
    client_ip = get_client_ip(request)
    anonymous_user = AuthUser.objects.filter(hash_user_id=client_ip).first()
    if anonymous_user:
        current_user_id_staff = anonymous_user.id_staff
    if survey.id_staff == get_staff_id(request):
        survey_creator_id_staff = current_user_id_staff

    is_creator = False
    if current_user_id_staff == survey_creator_id_staff:
        is_creator = True

    can_generate = True
    if not is_authenticated and current_user_id_staff:
        total_demo_surveys_count = Survey.objects.filter(id_staff=current_user_id_staff).count()
        if total_demo_surveys_count >= 2:
            can_generate = False

    if survey:
        questions = survey.get_questions()
        view_count = survey.view_count

        author_username = AuthUser.objects.get(id_staff=survey.id_staff).username

        json_response = {
            'page_title': f'{survey.title} | Генератор тестов с ИИ | Создать тест в Летучке',
            'title': survey.title,
            'survey_id': survey_id,
            'questions': questions,
            'author': author_username if len(author_username) < 16 else 'Аноним',
            'username': request.user.username if request.user.is_authenticated else 0,
            'model_name': f"{'Сгенерировано ' + survey.model_name.upper().replace('O', 'o') if survey.model_name else 'Сгенерировано в Летучке'}",
            'view_count': view_count,
            'is_creator': is_creator,
            'show_answers': survey.show_answers,
            'can_generate': can_generate,
            'debug': DEBUG
        }

        return render(request, 'demo-view.html', json_response)

    context = {
        'page_title': f'Генератор тестов с ИИ | Создать тест в Летучке',
        'title': 'Создать тест при помощи нейросети | Создать тест в Летучке',
        'survey_id': survey_id,
        'username': request.user.username if request.user.is_authenticated else None,
        'debug': DEBUG
    }

    return render(request, 'demo-view.html', context)


@login_required
def view_results(request, survey_id):
    survey = get_object_or_404(Survey, survey_id=survey_id)

    attempts_qs = survey.attempts.all().order_by('-created_at')
    total_attempts = attempts_qs.count()

    try:
        survey_questions_list = json.loads(survey.questions)
        questions_map = {q['question']: q['correct_answer'] for q in survey_questions_list if isinstance(q, dict)}
    except (json.JSONDecodeError, TypeError):
        questions_map = {}

    average_score_percent = 0
    median_score = 0
    perfect_attempts_percent = 0
    hardest_question, easiest_question = "-", "-"
    success_rate = 0

    if total_attempts > 0:
        base_aggregation = {
            'avg_percent': Avg(100.0 * F('score') / F('total_questions')),
            'perfect_count': Count('id', filter=Q(score=F('total_questions'))),
            'success_count': Count('id', filter=Q(score__gte=F('total_questions') * 0.5))
        }

        if not settings.DEBUG and 'postgresql' in connection.vendor:
            try:
                from django.contrib.postgres.aggregates import PercentileCont

                base_aggregation['median_score_agg'] = PercentileCont(0.5).within_group('score')
                stats = attempts_qs.aggregate(**base_aggregation)
                median_score = stats.get('median_score_agg', 0)

            except ImportError:
                stats = attempts_qs.aggregate(**base_aggregation)
                scores = list(attempts_qs.values_list('score', flat=True).order_by('score'))
                count = len(scores)
                if count % 2 == 1:
                    median_score = scores[count // 2]
                else:
                    mid1 = scores[count // 2 - 1]
                    mid2 = scores[count // 2]
                    median_score = (mid1 + mid2) / 2
        else:
            stats = attempts_qs.aggregate(**base_aggregation)
            scores = list(attempts_qs.values_list('score', flat=True).order_by('score'))
            count = len(scores)
            if count > 0:
                if count % 2 == 1:
                    median_score = scores[count // 2]
                else:
                    mid1 = scores[count // 2 - 1]
                    mid2 = scores[count // 2]
                    median_score = (mid1 + mid2) / 2

        average_score_percent = stats.get('avg_percent', 0)
        perfect_attempts_percent = (stats.get('perfect_count', 0) / total_attempts) * 100
        success_rate = (stats.get('success_count', 0) / total_attempts) * 100

        all_answers_json = attempts_qs.values_list('answers_json', flat=True)

        questions_stats = {}
        for answers_str in all_answers_json:
            try:
                answers = json.loads(answers_str)
                if isinstance(answers, dict):
                    for q_text, result in answers.items():
                        if isinstance(result, dict) and 'is_correct' in result:
                            q_stats = questions_stats.setdefault(q_text, {'correct': 0, 'total': 0})
                            q_stats['total'] += 1
                            if result.get('is_correct'):
                                q_stats['correct'] += 1
            except (json.JSONDecodeError, AttributeError):
                continue

    attempts_for_template = []
    for attempt in attempts_qs:
        percent = (attempt.score * 100 / attempt.total_questions) if attempt.total_questions > 0 else 0
        answers_with_results = []
        try:
            user_answers = json.loads(attempt.answers_json)
            if isinstance(user_answers, dict):
                for question_text, selected_answer in user_answers.items():
                    correct_answer = questions_map.get(question_text)
                    is_correct = (selected_answer == correct_answer)

                    answers_with_results.append({
                        'question': question_text,
                        'selected_answer': selected_answer,
                        'correct_answer': correct_answer,
                        'is_correct': is_correct
                    })
        except (json.JSONDecodeError, TypeError):
            pass

        answers_json_str = json.dumps(answers_with_results, ensure_ascii=False)

        attempts_for_template.append({
            'id': attempt.id,
            'student_name': attempt.student_name,
            'created_at': attempt.created_at,
            'score': attempt.score,
            'total_questions': attempt.total_questions,
            'percent': round(percent),
            'answers_json': mark_safe(answers_json_str)
        })

    author_username = AuthUser.objects.get(id_staff=survey.id_staff).username

    context = {
        'survey': survey,
        'attempts': attempts_for_template,
        'total_attempts': total_attempts,
        'average_score_percent': average_score_percent,
        'median_score': median_score,
        'perfect_attempts_percent': perfect_attempts_percent,
        'success_rate': success_rate,
        'hardest_question': hardest_question,
        'easiest_question': easiest_question,
        'view_count': survey.view_count,
        'username': get_username(request),
        'page_title': survey.title,
        'author': author_username if len(author_username) < 16 else 'Аноним',
    }
    return render(request, 'askify_service/test_results.html', context)


@csrf_exempt
@transaction.atomic
def register_survey_view(request, survey_id):
    if request.method == 'POST':
        try:
            survey = Survey.objects.select_for_update().get(survey_id=survey_id)
            data = json.loads(request.body)
            view_hash = data.get('hash', '')

            if not view_hash:
                return JsonResponse({'success': False, 'error': 'Hash required'})

            _, created = SurveyUniqueView.objects.get_or_create(
                survey=survey,
                view_hash=view_hash
            )

            if created:
                survey.view_count = F('view_count') + 1
                survey.save(update_fields=['view_count'])
                survey.refresh_from_db()

            return JsonResponse({
                'success': True,
                'new_view': created,
                'view_count': survey.view_count
            })

        except Survey.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Survey not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


# @login_required
def download_survey_pdf(request, survey_id):
    try:
        survey = get_object_or_404(Survey, survey_id=uuid.UUID(survey_id))
        tracer_l.info(f'{request.user.username} --- View survey in PDF')

        try:
            subscription_db = Subscription.objects.get(staff_id=get_staff_id(request))
            subscription_check = SubscriptionCheck()
            subscription_level = subscription_check.get_subscription_level(subscription_db.plan_name)
        except Exception:
            subscription_level = 0

        tracer_l.info(f'{request.user.id} --- success view: subscription_level {subscription_level}')
        return survey.generate_pdf(subscription_level)
    except Exception as fatal:
        tracer_l.critical(f'{request.user.username} --- FATAL with View survey in PDF: {fatal}')


def generate_username(email):
    from django.utils.text import slugify
    import random

    base_username = email.split('@')[0]
    base_username = slugify(base_username).replace('-', '_')

    if not AuthUser.objects.filter(username=base_username).exists():
        return base_username

    return f"{base_username}_{random.randint(1000, 9999)}"


@check_legal_process
def register(request):
    if request.user.is_authenticated:
        return redirect('create')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)

        if form.is_valid():
            if not is_allowed_email(form.cleaned_data.get('email')):
                form.add_error('email', 'Регистрация с этого почтового домена не разрешена.')
            else:
                user = form.save()

                tracer_l.warning(f'ADMIN. NEW USER {user.username}')

                plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
                Subscription.objects.create(
                    staff_id=user.id_staff,
                    plan_name=plan_name,
                    end_date=end_date,
                    status=status,
                    billing_cycle=billing_cycle
                )

                login(request, user)
                return redirect('create')

    else:
        form = CustomUserCreationForm()

    context = {'form': form, 'debug': DEBUG}
    return render(request, 'register.html', context)


@check_legal_process
def quick_register_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не разрешен'}, status=405)

    form = CustomUserCreationForm(request.POST)

    if form.is_valid():
        user = form.save()

        tracer_l.warning(f'API REGISTRATION. NEW USER {user.username}')

        plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
        subscription = Subscription.objects.create(
            staff_id=user.id_staff,
            plan_name=plan_name,
            end_date=end_date,
            status=status,
            billing_cycle=billing_cycle,
            discount=0.00
        )
        subscription.save()

        login(request, user)
        return JsonResponse({'redirect': '/payment'})
    else:
        print(form.errors.as_json())
        print("=" * 50)
        error_message = next(iter(form.errors.values()))[0]
        return JsonResponse({'error': error_message}, status=400)


@check_legal_process
def login_view(request):
    if request.user.is_authenticated:
        return redirect('/create')

    context = {}

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        if not email or not password:
            context['error'] = 'Введите email и пароль.'
            return render(request, 'login.html', context, status=400)

        if '@' not in email:
            context['error'] = 'Неверный email.'
            return render(request, 'login.html', context, status=400)

        try:
            username = email.split('@')[0]
        except IndexError:
            username = ''

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            request.session['user_id'] = user.id

            tracer_l.warning(f'ADMIN. LOGGED IN {user.username}')

            next_url = request.POST.get('next', '/create')
            safe_next = next_url if is_safe_url(next_url) else '/create'
            return redirect(safe_next)
        else:
            context['error'] = 'Неверный email или пароль. Попробуйте снова.'
            return render(request, 'login.html', context, status=400)

    context['next_url'] = request.GET.get('next', '/create')
    context['debug'] =  DEBUG
    return render(request, 'login.html', context)


def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('login')


def blocked_view(request):
    return render(request, 'askify_service/blocked.html')


VK_CLIENT_ID = env('VK_CLIENT_ID')
VK_CLIENT_SECRET = env('VK_CLIENT_SECRET')
VK_REDIRECT_URI = env('VK_REDIRECT_URI')
VK_API_VERSION = env('VK_API_VERSION')


def vk_auth(request):
    if not request.session.session_key:
        request.session.create()

    tracer_l.warning(f'ADMIN. VK_AUTH START. Session: {request.session.session_key}')

    auth_url = (
        f"https://oauth.vk.com/authorize?"
        f"client_id={VK_CLIENT_ID}&"
        f"display=page&"
        f"redirect_uri={VK_REDIRECT_URI}&"
        f"response_type=code&"
        f"v={VK_API_VERSION}&"
        f"state={request.session.session_key}&"
        f"scope=email"
    )
    tracer_l.warning(f'ADMIN. VK AUTH URL: {auth_url}')
    return redirect(auth_url)


@csrf_exempt
def vk_auth_callback(request):
    # Получаем код из GET или POST запроса
    code = request.GET.get('code') or request.POST.get('code')
    if not code:
        return JsonResponse({'success': False, 'error': 'Authorization code missing'}, status=400)

    # Для VK ID SDK (code_v2)
    if code.startswith('vk2.a.'):
        try:
            # Получаем данные пользователя напрямую через service token
            response = requests.get(
                "https://api.vk.com/method/users.get",
                params={
                    'v': VK_API_VERSION,
                    'access_token': "cf8db51fcf8db51fcf8db51f86ccaed8d3ccf8dcf8db51fa7f5bfa0b76655e0b9e7acae",
                    'fields': 'first_name,last_name,photo_200',
                    'code': code
                }
            )
            data = response.json()

            if 'error' in data:
                return JsonResponse({
                    'success': False,
                    'error': data['error']['error_msg']
                }, status=400)

            # Проверяем что есть данные пользователя
            if not data.get('response'):
                return JsonResponse({
                    'success': False,
                    'error': 'No user data received'
                }, status=400)

            user_data = data['response'][0]
            return JsonResponse({
                'success': True,
                'user_id': user_data['id'],
                'first_name': user_data['first_name'],
                'last_name': user_data['last_name'],
                'photo': user_data.get('photo_200', '')
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    # Для обычного OAuth
    else:
        try:
            # Получаем access token
            response = requests.post(
                "https://oauth.vk.com/access_token",
                data={
                    'client_id': VK_CLIENT_ID,
                    'client_secret': VK_CLIENT_SECRET,
                    'redirect_uri': VK_REDIRECT_URI,
                    'code': code
                }
            )
            data = response.json()

            if 'error' in data:
                return JsonResponse({
                    'success': False,
                    'error': data.get('error_description', 'VK auth error')
                }, status=400)

            return JsonResponse({
                'success': True,
                'access_token': data['access_token'],
                'user_id': data['user_id'],
                'email': data.get('email', '')
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)


@login_required
def redirect_to_profile(request):
    """
    Эта view просто берет залогиненного пользователя
    и перенаправляет его на его личную страницу профиля.
    """
    user = request.user
    if user.is_authenticated:
        return redirect('profile', username=user.username)
    else:
        return redirect('login')


@login_required
def profile_view(request, username):
    staff_id = get_staff_id(request)
    user = get_object_or_404(AuthUser, id_staff=staff_id)

    statistics = UserAnswers.calculate_user_statistics(staff_id)

    date_join = get_formate_date(user.date_joined)
    date_last_login = get_formate_date(user.last_login)

    subscription = get_object_or_404(Subscription, staff_id=staff_id)
    subscription_end_date_formatted = subscription.end_date.strftime('%d.%m.%Y')

    human_readable_plan = subscription.get_human_plan()

    subscription_end_date_as_date = subscription.end_date.date()

    # Расчет дней до конца подписки
    days_until_end = (subscription_end_date_as_date - timezone.now().date()).days

    user_django = request.user
    token_email_verification = signing.dumps(user_django.pk, salt='email-verification')

    subscription.status = subscription.check_sub_status()
    tests_count_limit = get_daily_test_limit(subscription.plan_name) if subscription.status == 'active' else 0

    manage_tokens_limits = ManageTokensLimits(staff_id)
    tests_used_today = manage_tokens_limits.get_tests_used_today()

    diff_tests_count_limit = tests_count_limit - tests_used_today

    tests_remaining_percentage = 0
    if tests_count_limit > 0:
        tests_remaining_percentage = (diff_tests_count_limit / tests_count_limit) * 100.0

    progress_bar_class = ''
    if tests_remaining_percentage > 50:
        progress_bar_class = 'progress-bar--high'
    elif tests_remaining_percentage > 20:
        progress_bar_class = 'progress-bar--medium'
    else:
        progress_bar_class = 'progress-bar--low'

    payments_qs = Payment.objects.filter(staff_id=staff_id).order_by('-created_at')

    payments_formatted = []
    for payment in payments_qs:
        amount_rubles = Decimal(payment.amount) / 100 / 100
        payments_formatted.append({
            'subscription': payment.subscription,
            'order_id': payment.order_id,
            'created_at': payment.created_at,
            'status': payment.status,
            'amount_display': "{:,.2f}".format(amount_rubles).replace('.', ',').replace(',', '')
        })

    manage_tokens_limits = ManageTokensLimits(staff_id)
    tests_used_today = manage_tokens_limits.get_tests_used_today()
    diff_tests_count_limit = tests_count_limit - tests_used_today

    user_data = {
        'page_title': f'Профиль {username}',
        'username': username,
        'tests_today_limit': max(diff_tests_count_limit, 0),
        'email': ('E-mail: ' + user.email) if user.email else '',
        'password': f'Пароль: *********' if user.password else '',
        'phone': 'Телефон: ' + (user.phone if user.phone else 'Не указан'),
        'date_join': date_join,
        'date_last_login': date_last_login,
        'statistics': statistics,
        'tokens': {
            'tests_remaining_count_limit': diff_tests_count_limit,
            'tests_total_limit': tests_count_limit,
            'tests_usage_percentage': tests_remaining_percentage,
            'progress_bar_class': progress_bar_class
        },
        'subscription': {
            'plan_name': human_readable_plan,
            'plan_end_date': f"{subscription_end_date_formatted}" if days_until_end > 0 else "Закончился",
            'days_until_end': days_until_end,
            'status': subscription.status
        },
        'subscription_level': get_subscription_level(request),
        'payments': payments_formatted,
        'token': token_email_verification
    }

    return render(request, 'profile.html', user_data)


@login_required
def user_profile_api(request):
    staff_id = get_staff_id(request)
    user = get_object_or_404(AuthUser, id_staff=staff_id)
    subscription = get_object_or_404(Subscription, staff_id=staff_id)

    statistics = UserAnswers.calculate_user_statistics(staff_id)
    subscription_status = subscription.check_sub_status()
    subscription_level = get_subscription_level(request)
    token_limit = get_token_limit(subscription.plan_name)

    # Подписка и лимиты
    tests_limit = get_daily_test_limit(subscription.plan_name) if subscription_status == 'active' else 0
    used_today = ManageTokensLimits(staff_id).get_tests_used_today()
    tests_remaining = max(0, tests_limit - used_today)

    end_date = subscription.end_date.date()
    days_until_end = (end_date - timezone.now().date()).days

    # Токены
    usage = TokensUsed.get_tokens_usage_today(staff_id)
    survey_tokens = usage['tokens_survey_used']
    feedback_tokens = usage['tokens_feedback_used']
    total_used = survey_tokens + feedback_tokens
    percent_used = (total_used / token_limit * 100) if token_limit > 0 else 0

    return JsonResponse({
        "username": user.username,
        "email": user.email,
        "phone": user.phone or None,
        "date_join": user.date_joined.strftime("%d.%m.%Y"),
        "date_last_login": user.last_login.strftime("%d.%m.%Y") if user.last_login else None,
        "statistics": statistics,
        "tokens": {
            "surveys": survey_tokens,
            "feedback": feedback_tokens,
            "total": total_used,
            "limit": token_limit,
            "token_limit": token_limit,
            "remaining": max(0, token_limit - total_used),
            "used_percent": round(percent_used),
            "tests_remaining_today": tests_remaining,
            "tests_daily_limit": tests_limit
        },
        "subscription": {
            "plan_name": subscription.get_human_plan(),
            "plan_end_date": subscription.end_date.strftime("%d.%m.%Y"),
            "days_until_end": days_until_end if days_until_end > 0 else 0,
            "is_active": days_until_end >= 0
        },
        "subscription_level": subscription_level,
        "email_verification_token": signing.dumps(user.pk, salt="email-verification")
    })


def get_subscription_level(request) -> int:
    subscription_db = Subscription.objects.get(staff_id=get_staff_id(request))
    subscription_check = SubscriptionCheck()
    return subscription_check.get_subscription_level(subscription_db.plan_name)

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Length, TruncDate
from django.utils import timezone
from datetime import timedelta, datetime

@login_required
def admin_stats(request):
    staff_id = get_staff_id(request)
    user = get_object_or_404(AuthUser, id_staff=staff_id)

    if request.method == 'POST':
        if 'ip_address' in request.POST:
            try:
                ip_to_block = request.POST.get('ip_address')
                if ip_to_block and (ip_to_block not in BlockedUsers.objects.all()):
                    new_block = BlockedUsers.objects.create(ip_address=ip_to_block)
                    new_block.save()
                    return JsonResponse({'status': True, 'message': f"[  BAN  ] --- [ OK ]"})
            except Exception as fail:
                return JsonResponse({'status': False, 'message': f"{fail}"})

        if 'username' in request.POST:
            username_to_promote = request.POST.get('username')
            try:
                user_to_promote = AuthUser.objects.get(username=username_to_promote)

                if user_to_promote.is_superuser:
                    return JsonResponse({'status': True, 'message': f"[  SUPERUSER  ] --- [ ALREADY ]"})

                user_to_promote.is_superuser = True
                user_to_promote.save()
                return JsonResponse({'status': True, 'message': f"[  SUPERUSER  ] --- [ OK ]"})
            except Exception as fail:
                return JsonResponse({'status': False, 'message': f"{fail}"})

        if 'new_api_key_value' in request.POST:
            APIKey.objects.create(
                name=request.POST.get('new_api_key_name'),
                key=request.POST.get('new_api_key_value'),
                provider=request.POST.get('new_api_key_provider'),
                purpose=request.POST.get('new_api_key_purpose'),
                expires_at=request.POST.get('new_api_key_expires') or None
            )
            return redirect('stats2975')

        if 'activate_api_key_id' in request.POST:
            key_id_to_activate = request.POST.get('activate_api_key_id')
            key_purpose = request.POST.get('key_purpose')

            if not key_id_to_activate or not key_purpose:
                return JsonResponse({'status': False, 'message': 'Недостаточно данных'}, status=400)

            try:
                APIKey.objects.filter(purpose=key_purpose).update(is_active=False)
                APIKey.objects.filter(id=key_id_to_activate, purpose=key_purpose).update(is_active=True)
                return JsonResponse({'status': True, 'message': f'Ключ для {key_purpose} активирован'})

            except Exception as e:
                return JsonResponse({'status': False, 'message': f'Ошибка: {str(e)}'}, status=500)
            
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    chart_data = None

    if start_date_str and end_date_str:
        start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()

        selected_users = AuthUser.objects.filter(date_joined__date__range=(start_date, end_date)).count()
        total_surveys = Survey.objects.filter(updated_at__date__range=(start_date, end_date)).count()
        total_answers = UserAnswers.objects.filter(created_at__date__range=(start_date, end_date)).count()
        subscriptions = Subscription.objects.filter(start_date__date__range=(start_date, end_date)).count()
        
        # 1. Собираем ежедневные регистрации
        user_counts_query = (
            AuthUser.objects.filter(date_joined__date__range=(start_date, end_date))
            .annotate(day=TruncDate('date_joined'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )

        # 2. Собираем ежедневное использование API
        api_usage_query = (
            APIKeyUsage.objects.filter(timestamp__date__range=(start_date, end_date))
            .annotate(day=TruncDate('timestamp'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )

        # 3. Форматируем данные для JS, заполняя пропущенные дни нулями
        labels = []
        user_counts = []
        api_counts = []
        
        user_data_map = {item['day'].isoformat(): item['count'] for item in user_counts_query}
        api_data_map = {item['day'].isoformat(): item['count'] for item in api_usage_query}

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            labels.append(current_date.strftime('%d.%m'))
            user_counts.append(user_data_map.get(date_str, 0))
            api_counts.append(api_data_map.get(date_str, 0))
            current_date += timedelta(days=1)

        chart_data = json.dumps({
            'labels': labels,
            'user_counts': user_counts,
            'api_counts': api_counts,
        })
    else:
        selected_users = total_surveys = subscriptions = total_answers = 0

    all_users = AuthUser.objects.all().count()

    if user.is_superuser:
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        selected_subscription = Subscription.objects.all()

        if start_date and end_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d')
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d') + timezone.timedelta(days=1)

            selected_users = (
                AuthUser.objects
                .filter(date_joined__range=(start_date, end_date))
                .annotate(username_len=Length('username'))
                .filter(username_len__lte=30)
                .count()
            )
            total_surveys = Survey.objects.filter(updated_at__range=(start_date, end_date)).count()
            total_answers = UserAnswers.objects.filter(created_at__range=(start_date, end_date)).count()
            subscriptions = Subscription.objects.filter(start_date__range=(start_date, end_date)).count()
        else:
            selected_users = total_surveys = subscriptions = total_answers = 0

        payment_data = []
        for subscription in selected_subscription:
            try:
                user = AuthUser.objects.get(id_staff=subscription.staff_id)
            except Exception:
                pass

            payments = Payment.objects.filter(subscription=subscription)

            for payment in payments:
                payment_data.append({
                    'name': user.username,
                    'plan_name': subscription.plan_name,
                    'status': subscription.status,
                    'payment_status': payment.status,
                    'amount': f'{get_format_number(payment.amount / 100)} руб.',
                    'date': get_formate_date(subscription.start_date),
                })

        completed_payments = Payment.objects.filter(status='completed')

        total_revenue = completed_payments.aggregate(total=Sum('amount'))['total'] / 100 or 0
        completed_count = completed_payments.count()

        average_check = total_revenue / completed_count if completed_count > 0 else 0

        total_attempts = Payment.objects.count()
        payment_conversion = (completed_count / total_attempts) * 100 if total_attempts > 0 else 0

        failed_count = Payment.objects.filter(status='failed').count()

        telegram_users_count = AuthUser.objects.filter(
            Q(hash_user_id__isnull=True) | Q(hash_user_id__exact=''),
            email__exact=''
        ).count()

        email_users_count = AuthUser.objects.exclude(email__exact='').count()

        thirty_days_ago = timezone.now() - timedelta(days=30)
        active_users_monthly = AuthUser.objects.filter(last_login__gte=thirty_days_ago).count()
        wau_weekly_active_users = AuthUser.objects.filter(last_login__gte=timezone.now() - timedelta(days=7)).count()

        total_users_count = AuthUser.objects.all().count()
        conversion_rate_to_paid = (Payment.objects.filter(status='completed').values(
            'staff_id').distinct().count() / total_users_count) * 100 if total_users_count > 0 else 0

        daily_active_users = AuthUser.objects.filter(last_login__gte=timezone.now() - timedelta(days=1)).count()
        stickiness_ratio = (daily_active_users / active_users_monthly) * 100 if active_users_monthly > 0 else 0

        total_api_calls_today = APIKeyUsage.objects.filter(timestamp__date=timezone.now().date()).count()

        context = {
            'username': request.user.username,
            'selected_users': selected_users,
            'total_users': all_users,
            'total_surveys': total_surveys,
            'total_answers': total_answers,
            'subscriptions': subscriptions,
            'selected_subscription': selected_subscription,
            'data': payment_data,
            'total_revenue': total_revenue,
            'average_check': average_check,
            'payment_conversion': payment_conversion,
            'failed_payments_count': failed_count,
            'telegram_users_count': telegram_users_count,
            'email_users_count': email_users_count,
            'active_users_monthly': active_users_monthly,
            'wau_weekly_active_users': wau_weekly_active_users,
            'conversion_rate_to_paid': conversion_rate_to_paid,
            'stickiness_ratio': stickiness_ratio,
            'total_api_calls_today': total_api_calls_today,
            'chart_data': chart_data
        }

        api_keys = APIKey.objects.all().order_by('-created_at')

        start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        def calculate_usage_percent(api_key):
            usage_count = APIKeyUsage.objects.filter(api_key=api_key, timestamp__gte=start_of_day).count()
            max_requests_per_day = 50
            _percent = int((usage_count / max_requests_per_day) * 100)
            return min(_percent, 100), usage_count

        active_keys = {
            'FEEDBACK': APIKey.objects.filter(purpose='FEEDBACK', is_active=True).first(),
            'SURVEY': APIKey.objects.filter(purpose='SURVEY', is_active=True).first()
        }

        from collections import defaultdict
        keys_by_purpose = defaultdict(list)

        for key in api_keys:
            percent, today_count = calculate_usage_percent(key)
            key.usage_percent = percent
            key.today_usage_count = today_count
            key.is_active = (active_keys.get(key.purpose) and active_keys[key.purpose].id == key.id)
            keys_by_purpose[key.purpose].append(key)

        context.update({
            "keys_by_purpose": dict(keys_by_purpose),
            "active_keys": active_keys,
        })

        return render(request, 'admin.html', context)
    else:
        return redirect(f'/profile/{request.user.username}')


@login_required
def activate_api_key(request):
    try:
        key_id = request.POST.get('activate_api_key_id')
        if not key_id:
            return JsonResponse({'status': False, 'message': 'Не указан ID ключа'})

        key = APIKey.objects.get(id=key_id)

        APIKey.objects.filter(purpose=key.purpose).update(is_active=False)

        key.is_active = True
        key.save()

        return JsonResponse({'status': True, 'message': f'Ключ {key.name} активирован для типа {key.purpose}'})

    except APIKey.DoesNotExist:
        return JsonResponse({'status': False, 'message': 'Ключ не найден'})
    except Exception as e:
        return JsonResponse({'status': False, 'message': str(e)})


MODEL_MAP = {
    'Survey': ('📝 Тесты', Survey),
    'SurveyView': ('📝 SurveyView', SurveyUniqueView),
    'UserAnswers': ('📤 Ответы', UserAnswers),
    'AuthUser': ('👥 Пользователи', AuthUser),
    'Subscription': ('💰 Подписки', Subscription),
    'Payment': ('💳 Платежи', Payment),
    'BlockedUsers': ('🚫 Блокировки', BlockedUsers),
    'BlogPost': ('📰 Статьи', BlogPost),
    'TokensUsed': ('🪙 Токены', TokensUsed),
}


@login_required
def db_viewer(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Ты не админ, дружок")

    model_key = request.GET.get('model', 'AuthUser')
    model_data = MODEL_MAP.get(model_key)

    if not model_data:
        return HttpResponse("Модель не найдена", status=404)

    model_class = model_data[1]
    items = model_class.objects.all().order_by('-pk')

    context = {
        'model_name': model_data[0],
        'model_key': model_key,
        'items': items,
        'fields': [f.name for f in model_class._meta.fields],
        'models': MODEL_MAP.items(),
    }
    return render(request, 'askify_service/db_viewer.html', context)


@login_required
def db_search(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 3:
        return JsonResponse([])

    models_to_search = [
        (Survey, ['survey_id', 'title', 'description', 'id_staff']),
        (AuthUser, ['username', 'email', 'first_name', 'last_name', 'id_staff']),
        (UserAnswers, ['survey_id', 'id_staff', 'user_agent', 'answer_text']),
        (Subscription, ['staff_id', 'plan_name', 'status', 'start_date', 'end_date']),
        (Payment, ['user__username', 'amount', 'currency', 'status', 'transaction_id']),
        (BlogPost, ['title', 'content', 'author__username']),
    ]

    results = []
    for model, fields in models_to_search:
        q_objects = Q()
        for field in fields:
            try:
                if '__' in field:
                    model._meta.get_field(field.split('__')[0])
                else:
                    model._meta.get_field(field)
                q_objects |= Q(**{f'{field}__icontains': query})
            except Exception:
                continue

        for item in model.objects.filter(q_objects)[:5]:
            results.append({
                'model': model.__name__,
                'field': ', '.join(fields),
                'value': str(item),
                'source': get_related_info(item)
            })

    results.sort(key=lambda x: x['model'])
    return JsonResponse(results, safe=False)


def get_related_info(item):
    """
    Получение расширенной связанной информации для элемента.
    Показывает не только id_staff, но и другие значимые связи.
    """
    info_parts = []

    if hasattr(item, 'id_staff') and item.id_staff:
        try:
            user = AuthUser.objects.get(id_staff=item.id_staff)
            info_parts.append(f"Пользователь: {user.username} ({user.email})")
            if user.first_name and user.last_name:
                info_parts.append(f"Имя: {user.first_name} {user.last_name}")
        except AuthUser.DoesNotExist:
            info_parts.append(f"ID юзера: {item.id_staff} (Не найден)")
        except Exception as e:
            pass
    elif hasattr(item, 'staff_id') and item.staff_id:
        try:
            user = AuthUser.objects.get(id=item.staff_id)
            info_parts.append(f"Пользователь: {user.username} ({user.email})")
            if user.first_name and user.last_name:
                info_parts.append(f"Имя: {user.first_name} {user.last_name}")
        except AuthUser.DoesNotExist:
            info_parts.append(f"ID юзера: {item.staff_id} (Не найден)")
        except Exception as e:
            pass

    if hasattr(item, 'user') and item.user:
        try:
            user = item.user
            info_parts.append(f"Пользователь: {user.username} ({user.email})")
            if user.first_name and user.last_name:
                info_parts.append(f"Имя: {user.first_name} {user.last_name}")
        except Exception as e:
            info_parts.append(f"Пользователь: Неизвестен")

    if hasattr(item, 'survey_id') and item.survey_id:
        try:
            survey = Survey.objects.get(survey_id=item.survey_id)
            info_parts.append(f"Тест: {survey.title} (ID: {survey.survey_id})")
        except Survey.DoesNotExist:
            info_parts.append(f"ID теста: {item.survey_id} (Не найден)")
        except Exception as e:
            pass

    if isinstance(item, AuthUser):
        try:
            subscriptions = Subscription.objects.filter(staff_id=item.id)
            if subscriptions.exists():
                for sub in subscriptions[:2]:
                    info_parts.append(f"Подписка: {sub.plan_name} (Статус: {sub.status})")

            payments = Payment.objects.filter(user=item)
            if payments.exists():
                for pay in payments[:2]:
                    info_parts.append(f"Платеж: {pay.amount} {pay.currency} (Статус: {pay.status})")
        except Exception as e:
            pass

    if hasattr(item, 'blog_post') and item.blog_post:
        try:
            info_parts.append(f"К посту: {item.blog_post.title}")
        except Exception as e:
            pass

    if not info_parts:
        return "Нет связанных данных"

    return ", ".join(info_parts)


@login_required
def block_by_staff_id(request, id_staff):
    maybe_admin = get_object_or_404(AuthUser, username=request.user.username)

    if maybe_admin.is_superuser:
        user = get_object_or_404(AuthUser, id_staff=id_staff)
        BlockedUsers.objects.get_or_create(ip_address=get_client_ip(request), reason=f'Blocked user {user.username}')
        return redirect('stats2975')

    return redirect('login')


@login_required
def block_by_ip(request, ip_address):
    maybe_admin = get_object_or_404(AuthUser, username=request.user.username)

    if maybe_admin.is_superuser:
        BlockedUsers.objects.get_or_create(ip_address=ip_address)
        return redirect(request.META.get('HTTP_REFERER', 'stats2975'))

    return redirect('login')


def unblock_by_ip(request, ip_address):
    maybe_admin = get_object_or_404(AuthUser, username=request.user.username)

    if maybe_admin.is_superuser:
        blocked_user = BlockedUsers.objects.filter(ip_address=ip_address)
        if blocked_user.exists():
            blocked_user.delete()
            return redirect(request.META.get('HTTP_REFERER', 'stats2975'))
        else:
            return JsonResponse({"success": False, "message": "IP не найден в заблокированных."})

    return redirect('login')


@login_required
def unblock_by_staff_id(request, id_staff):
    maybe_admin = get_object_or_404(AuthUser, username=request.user.username)

    if maybe_admin.is_superuser:
        try:
            blocked_user = BlockedUsers.objects.filter(id_staff=id_staff)
            blocked_user.delete()
            return JsonResponse({"success": True})
        except Exception as e:
            return HttpResponse(f"Fail - {e}")

    return redirect('login')


@login_required
def create_payment(request):
    user_data = get_object_or_404(AuthUser, id_staff=get_staff_id(request))
    order_id = generate_payment_id()

    tracer_l.warning(f'ADMIN. {request.user.username}: VIEW PAYMENT')

    context = {
        'page_title': 'Выбор тарифного плана',
        'username': get_username(request),
        'email': '' if user_data.email is None else user_data.email,
        'phone': '' if user_data.phone is None else user_data.phone,
        'order_id': order_id,
        'fullname': user_data.username,
    }

    return render(request, 'payments/payment.html', context)


class PaymentInitiateView(View):
    """
        Вьюшка инициализации платежа.
    """
    def post(self, request):
        data = json.loads(request.body)
        # Извлечение данных из запроса
        amount = data['amount']
        description = data['description']
        order_id = data['orderId']
        email = data['email']
        phone = data['phone']
        receipt = data['receipt']

        tracer_l.debug(
            f"RECIEVED DATA:\n\nphone: {phone}, email: {email}, order_id: {order_id}, receipt: {receipt}")
        tracer_l.debug(f"amount: {amount}")

        plan_prices = {
            'Начальный': 0,
            'Лайтовый': 99,
            'Стандартный': 420,
            'Премиум': 590,
            'Стандартный 3 мес': 840,
            'Премиум 3 мес': 1180,
            'Ультра': 990,
            'Стандартный Год': 2640,
            'Премиум Год': 4800
        }

        print(int(amount), description, plan_prices.get(description))

        if int(amount) != plan_prices.get(description):
            tracer_l.warning(f'ADMIN. {request.user.username}: Неверная сумма. code 400')
            return JsonResponse({'Success': False, 'Message': 'Неверная сумма.'}, status=400)

        order_id = generate_payment_id()
        tracer_l.debug(f'{request.user.username}: Приход: {order_id}. ')

        items = [
            {
                "Name": plan_prices.get(description),
                "Price": int(amount) * 100,
                "Quantity": 1,
                "Amount": int(amount) * 100,
                "Tax": "none"
            },
        ]

        total_amount = sum(item['Amount'] for item in items)

        data_token = [
            {"TerminalKey": TERMINAL_KEY},
            {"Amount": str(total_amount)},
            {"OrderId": order_id},
            {"Description": description},
            {"Password": TERMINAL_PASSWORD}
        ]

        tracer_l.warning(f'{request.user.username}\n\nWANT TO BUY!!!\n\nAmount: {amount}\n'
                         f'About: {description}')

        created_token = PaymentManager().generate_token_for_new_payment(data_token)

        request_body = {
            "TerminalKey": TERMINAL_KEY,
            "Amount": total_amount,
            "OrderId": order_id,
            "Description": description,
            "Token": created_token,
            "DATA": {
                "Phone": phone,
                "Email": email
            },
            "Receipt": {
                "Email": email,
                "Phone": phone,
                "Taxation": "osn",
                "Items": items
            }
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post("https://securepay.tinkoff.ru/v2/Init/", json=request_body, headers=headers)
        response_data = response.json()

        if response_data.get('Success'):
            
            if 'премиум' in description.lower():
                plan_name_for_db = 'Премиум'
            elif 'стандарт' in description.lower():
                plan_name_for_db = 'Стандартный'
            else:
                plan_name_for_db = 'Премиум'

            if 'год' in description.lower():
                billing_cycle = 'yearly'
            elif 'мес' in description.lower():
                billing_cycle = 'monthly3'
            else:
                billing_cycle = 'monthly'

            try:
                subscription, created = Subscription.objects.update_or_create(
                    staff_id=get_staff_id(request),
                    defaults={
                        'plan_name': plan_name_for_db,
                        'status': 'inactive',
                        'billing_cycle': billing_cycle,
                        'end_date': timezone.now()
                    }
                )

            except Exception as e:
                tracer_l.critical(f"НЕ СМОГ СОЗДАТЬ ПОДПИСКУ: {e}")
                return JsonResponse({'error': 'Ошибка при создании подписки'}, status=500)

            new_payment = Payment.objects.create(
                staff_id=get_staff_id(request),
                payment_id=response_data.get('PaymentId'),
                subscription=subscription,
                order_id=order_id,
                amount=int(amount) * 100,
                status='pending'
            )
            new_payment.save()

            # Запись в транзакции
            new_trans = TransactionTracker.objects.create(
                staff_id=get_staff_id(request),
                payment_id=response_data.get('PaymentId'),
                description=description,
                order_id=order_id,
                amount=int(amount) * 100,
            )
            new_trans.save()

            return JsonResponse({
                'Success': True,
                'PaymentURL': response_data['PaymentURL'],
                'Message': 'Платеж успешно инициирован.'
            })
        else:
            return JsonResponse({
                'Success': False,
                'ErrorCode': response_data.get('ErrorCode'),
                'Message': response_data.get('Message')
            }, status=400)


def get_payment_data(status, description, plan_name, end_date, payment_id, order_id, amount):
    _payment_data = {
        "payment_status": status, "text_status": description, "plan_name": plan_name,
        "plan_end_date": end_date, "payment_id": payment_id, 'order_id': order_id, 'amount': amount
    }
    return _payment_data


class PaymentSuccessView(View):
    def get(self, request):
        success = request.GET.get('Success')
        error_code = request.GET.get('ErrorCode')
        payment_id = request.GET.get('PaymentId')
        amount = request.GET.get('Amount')

        if success == 'true' and error_code == '0':
            try:
                payment = Payment.objects.get(payment_id=payment_id)
                # subscription = Subscription.objects.get(staff_id=get_staff_id(request))

                subscription, created = Subscription.objects.get_or_create(
                    staff_id=get_staff_id(request),
                    defaults={
                        'plan_name': 'Стартовый',
                        'status': 'inactive',
                        'billing_cycle': 'monthly',
                    }
                )

                payment_manager = PaymentManager()
                payment_parameters = [payment.order_id, TERMINAL_PASSWORD, TERMINAL_KEY]
                payment_status = payment_manager.check_order(payment_parameters)['response']['Payments'][0]['Status']

                if subscription.status == 'active' and payment.status == 'completed':
                    return redirect('create')

                description_payment = PAYMENT_STATUSES.get(payment_status, 'Статус не найден')

                error_payment_data = get_payment_data(
                    "Неудача", description_payment, subscription.plan_name, subscription.end_date,
                    payment.payment_id, payment.order_id, payment.amount
                )

                if int(payment.amount) != int(amount):
                    return render(request, 'payments/pay_status.html', error_payment_data)

                elif payment_status == 'DEADLINE_EXPIRED':
                    return render(request, 'payments/pay_status.html', error_payment_data)

                elif payment_status == 'CONFIRMED':
                    payment.status = 'completed'
                    payment.save()

                    tracer_l.critical(f'SUCCESS BUY - {request.user.username} - {description_payment}')

                    if subscription.billing_cycle == 'yearly':
                        subscription.end_date = datetime.now() + timedelta(days=365)
                    elif subscription.billing_cycle == 'monthly3':
                        subscription.end_date = datetime.now() + timedelta(days=92)
                    else:
                        subscription.end_date = datetime.now() + timedelta(days=30)

                    subscription.start_date = datetime.now()
                    subscription.status = 'active'
                    subscription.save()

                    formatted_amount = f"{payment.amount / 100:,.2f}".replace(',', ' ').replace('.', ',') + " RUB"

                    payment_details = [
                        {"label": "Сумма", "value": formatted_amount},
                        {"label": "ID платежа", "value": payment.payment_id},
                        {"label": "ID заказа", "value": payment.order_id},
                        {"label": "Дата покупки", "value": only_datetime.date.today().strftime("%d.%m.%Y")},
                        {"label": "Заканчивается", "value": get_formate_date(subscription.end_date)},
                    ]

                    payment_data = {
                        "page_title": "Успешный платеж",
                        "payment_status": "Успешно",
                        "text_status": "Спасибо за покупку!",
                        "plan_name": subscription.get_human_plan(),
                        "payment_details": payment_details,
                        "username": get_username(request)
                    }

                    # Запись в транзакции
                    new_transaction = TransactionTracker.objects.create(
                        staff_id=get_staff_id(request),
                        payment_id=payment.payment_id,
                        description=f'{formatted_amount}, {subscription.get_human_plan()}, completed: {payment_status}',
                        order_id=payment.order_id,
                        amount=int(amount),
                    )
                    new_transaction.save()

                    try:
                        message = render_to_string('payments/payment_success_email.html', {
                            'plan_name': subscription.get_human_plan(),
                            'amount': f"{payment.amount / 100:,.2f}".replace(',', ' ').replace('.', ','),
                            'payment_id': payment.payment_id,
                            'order_id': payment.order_id,
                            'end_date': get_formate_date(subscription.end_date),
                            'next_url': 'https://letychka.ru/create/'
                        })

                        user_data = AuthUser.objects.filter(id_staff=get_staff_id(request)).first()

                        if user_data.email:
                            send_mail(
                                '✅ Успешная оплата — тариф активирован',
                                message,
                                'support@letychka.ru',
                                [user_data.email],
                                fail_silently=False,
                                html_message=message
                            )
                        tracer_l.info(f'{request.user.username} Success send mail')

                    except Exception as fail:
                        tracer_l.warning(f'{request.user.username} Error to send check to email: {fail}')

                    try:
                        payment_details_text = "\n".join(
                            [f"<b>{detail['label']}:</b> {detail['value']}" for detail in payment_details])

                        message = (
                            f"{CONFIRM_SYMBOL} Успешный платеж\n\n"
                            f"<b>Статус платежа:</b> {payment_data['payment_status']}\n"
                            f"<b>План:</b> {payment_data['plan_name']}\n\n"
                            f"<b>Детали платежа:</b>\n"
                            f"{payment_details_text}\n\n"
                            f"<b>ID пользователя:</b> {get_staff_id(request)}"
                        )
                        telegram_message_manager = ManageTelegramMessages()
                        telegram_message_manager.send_message(TELEGRAM_CHAT_ID, message)

                        auth_user = AuthUser.objects.filter(id_staff=get_staff_id(request)).first()
                        if auth_user:
                            additional_auth_user = AuthAdditionalUser.objects.get(user=auth_user)
                            telegram_message_manager.send_message(additional_auth_user.id_telegram, message)

                            tracer_l.info(f'{request.user.username}\n\nSuccess send to Telegram')
                    except Exception as fail:
                        tracer_l.warning(f'{request.user.username}\n\nFail while send info about payment to Telegram: {fail}')

                    return render(request, 'payments/pay_status.html', payment_data)
                else:
                    tracer_l.debug(f'{request.user.username}\n\nСтатус платежа: {payment_status}')

                    return render(request, 'payments/pay_status.html', error_payment_data)
            except Payment.DoesNotExist as fatal:
                error_payment_data = {
                    "page_title": "Ошибка оплаты",
                    "payment_status": "Неудача",
                    "text_status": "Платеж не существует",
                }
                tracer_l.error(f'{request.user.username}\n\nОшибка оплаты. Платеж не существует: {fatal}')

                return render(request, 'payments/pay_status.html', error_payment_data)
        else:
            subscription = Subscription.objects.get(staff_id=get_staff_id(request))

            payment_data = {
                "payment_status": "Не удалось", "page_title": "Ошибка при оплате",
                "text_status": "Не удалось активировать план, попробуйте позже :(",
                "plan_name": subscription.get_human_plan(),
            }
            tracer_l.error(f'{request.user.username}\n\nОшибка при оплате. Не удалось активировать план')

            return render(request, 'payments/pay_status.html', payment_data)


@login_required
def get_ip(request):
    ip = get_client_ip(request)
    return JsonResponse({'ip': ip})


class ManageTelegramMessages:
    def __base_send_message(self, payload=None):
        bot_token = TELEGRAM_BOT_TOKEN
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        requests.post(url, json=payload)

    def send_message(self, user_id, message):
        payload = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'HTML'
        }

        self.__base_send_message(payload)

    def send_message_success_login(self, user_id, message):
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "Закрыть сессию",
                        "callback_data": "close_session"
                    }
                ]
            ]
        }

        payload = {
            'chat_id': user_id,
            'text': message,
            'reply_markup': json.dumps(keyboard)
        }

        self.__base_send_message(payload)

    def send_code_to_user(self, telegram_user_id, code):
        message = f"Код для авторизации: <pre><code>{code}</code></pre>\n\n<i>Нажмите, чтобы скопировать</i>"
        self.send_message(telegram_user_id, message)


class TelegramAuthManagement:
    @staticmethod
    def auth_user(telegram_auth_data: dict):
        telegram_user_id = telegram_auth_data.get('telegram_user_id')
        phone_number = telegram_auth_data.get('phone_number')
        first_name = telegram_auth_data.get('first_name')
        last_name = telegram_auth_data.get('last_name')
        username = telegram_auth_data.get('username')

        additional_auth = AuthAdditionalUser.objects.filter(id_telegram=int(telegram_user_id)).first()

        user, created = AuthUser.objects.update_or_create(
            phone=phone_number,
            defaults={
                'confirmed_user': True,
                'first_name': first_name,
                'last_name': last_name,
                'username': username if username is not None else telegram_user_id,
            }
        )

        if not additional_auth:
            new_auth_telegram = AuthAdditionalUser.objects.create(
                user=user,
                id_telegram=int(telegram_user_id),
            )
            new_auth_telegram.save()

            tracer_l.debug(f'confirm_user: Created additional auth for user: {telegram_user_id}')

            plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
            subscription = Subscription.objects.create(
                staff_id=user.id_staff,
                plan_name=plan_name,
                end_date=end_date,
                status=status,
                billing_cycle=billing_cycle,
                discount=0.00
            )
            subscription.save()

        return user

    @staticmethod
    def one_click_auth(telegram_user_id: int, first_name: str, last_name: str, username: str):
        """
            Авторизация пользователя по telegram_user_id.
            Если пользователь уже есть в системе, привязывает telegram_user_id к его аккаунту.
            Если пользователя нет, создаёт новую запись.
        """
        additional_auth = AuthAdditionalUser.objects.filter(id_telegram=int(telegram_user_id)).first()

        if additional_auth:
            user = additional_auth.user
            return user

        user = AuthUser.objects.filter(username=username).first()

        if user:
            new_auth_telegram, created = AuthAdditionalUser.objects.get_or_create(
                user=user,
                defaults={
                    'id_telegram': int(telegram_user_id),
                }
            )
        else:
            user, created = AuthUser.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                }
            )

            new_auth_telegram, created = AuthAdditionalUser.objects.get_or_create(
                user=user,
                defaults={
                    'id_telegram': int(telegram_user_id),
                }
            )

            plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
            subscription, created = Subscription.objects.get_or_create(
                staff_id=user.id_staff,
                defaults={
                    'plan_name': plan_name,
                    'end_date': end_date,
                    'status': status,
                    'billing_cycle': billing_cycle,
                    'discount': 0.00
                }
            )
            subscription.save()

        return user


@csrf_exempt
def one_click_auth_view(request, token: str, token_hash: str):
    """
        Обработка одноразовой ссылки для авторизации через Telegram.
    """
    if request.user.is_authenticated:
        return redirect('create')

    try:
        expected_hash = hashlib.sha256(token.encode()).hexdigest()
        if expected_hash != token_hash:
            return JsonResponse({"status": "error", "message": "Invalid token hash"}, status=400)

        parts = token.split(':')
        if len(parts) != 3:
            return JsonResponse({"status": "error", "message": "Invalid token format"}, status=400)

        telegram_user_id, timestamp, _ = parts
        telegram_user_id = int(telegram_user_id)
        timestamp = int(timestamp)

        current_time = int(time.time())
        if current_time - timestamp > 300:
            return JsonResponse({"status": "error", "message": "Link expired"}, status=400)

        user = TelegramAuthManagement.one_click_auth(
            telegram_user_id=telegram_user_id,
            first_name="",
            last_name="",
            username=f"{telegram_user_id}"
        )

        login(request, user)
        request.session['user_id'] = user.id

        tracer_l.warning(f'ADMIN. LOGGED IN {telegram_user_id}')

        return redirect('create')

    except Exception as fail:
        tracer_l.error(f'one_click_auth_view: {fail}')

        return JsonResponse({"status": "error", "message": f"Error: {fail}"}, status=500)


user_verify_code = {}


@csrf_exempt
def confirm_user(request):
    """ Прием данных с сервера V1, дешифровка и создание аккаунта для нового пользователя """
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

        data = body.get('data')
        data_hash = body.get('data_hash')

        if hash_data(data) != data_hash:
            return JsonResponse({'status': 'error', 'message': 'Data integrity check failed'}, status=402)

        telegram_user_id = data.get('telegram_user_id')
        phone_number = str(data.get('phone_number'))
        username = data.get('username') or ''
        first_name = data.get('first_name')
        last_name = data.get('last_name') or ''

        tracer_l.info(f'Success auth: hash is OK --- ')

        telegram_auth_data = {
            'telegram_user_id': telegram_user_id,
            'phone_number': phone_number,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
        }
        user = TelegramAuthManagement.auth_user(telegram_auth_data)

        login(request, user)
        request.session['user_id'] = user.id

        return JsonResponse({'status': 'success', 'user_id': user.id})

    return JsonResponse({'status': 'error', 'message': 'Invalid response'}, status=400)


client_public_keys = {}


@csrf_exempt
def confirm_user_v2(request):
    """ Прием данных с сервера V2, дешифровка и создание аккаунта для нового пользователя """
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError as fatal:
            return JsonResponse({'status': 'error', 'message': f'Invalid JSON: {fatal}'}, status=400)

        required_fields = ['nonce', 'ciphertext', 'tag', 'data_hash', 'telegram_user_id']
        for field in required_fields:
            if field not in body:
                return JsonResponse({'status': 'error', 'message': f'Missing field: {field}'}, status=400)

        try:
            nonce = bytes.fromhex(body.get("nonce"))
            ciphertext = bytes.fromhex(body.get("ciphertext"))
            tag = bytes.fromhex(body.get("tag"))
            data_hash = body.get("data_hash")
            telegram_user_id = body.get("telegram_user_id")
        except ValueError as e:
            return JsonResponse({'status': 'error', 'message': 'Invalid hex format'}, status=400)

        client_key_data = client_public_keys.get(telegram_user_id)
        if not client_key_data:
            return JsonResponse({'status': 'error', 'message': 'Client public key not found'}, status=400)

        client_public_key_pem = client_key_data['public_key']

        try:
            client_public_key = ECC.import_key(client_public_key_pem)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': 'Invalid client public key'}, status=400)

        crypto_b.derive_shared_key(client_public_key)

        try:
            decrypted_data = crypto_b.decrypt_data(nonce, ciphertext, tag)
        except ValueError as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

        if hash_data(decrypted_data) != data_hash:
            return JsonResponse({'status': 'error', 'message': 'Data integrity check failed'}, status=402)

        telegram_user_id = decrypted_data.get('telegram_user_id')
        phone_number = str(decrypted_data.get('phone_number'))
        username = decrypted_data.get('username') or ''
        first_name = decrypted_data.get('first_name')
        last_name = decrypted_data.get('last_name') or ''

        telegram_auth_data = {
            'telegram_user_id': telegram_user_id,
            'phone_number': phone_number,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
        }
        user = TelegramAuthManagement.auth_user(telegram_auth_data)

        login(request, user)
        request.session['user_id'] = user.id

        return JsonResponse({'status': 'success', 'user_id': user.id})

    return JsonResponse({'status': 'error'}, status=400)


def cleanup_old_keys():
    """ Удаляет нелегитимные ключи (TTL ключей в системе). """
    current_time = time.time()
    for telegram_user_id in list(client_public_keys.keys()):
        if current_time - client_public_keys[telegram_user_id]['timestamp'] > 300:
            del client_public_keys[telegram_user_id]


@csrf_exempt
def exchange_keys(request):
    """ Обмен ключами с сервером """
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError as e:
        tracer_l.error(f'exchange_keys --- Invalid JSON: {e}')
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        public_key_a_pem = body["public_key"]
        telegram_user_id = body["telegram_user_id"]
    except KeyError as e:
        tracer_l.error(f'exchange_keys --- Missing field: {e}')

        return JsonResponse({"error": f"Missing field: {e}"}, status=400)

    try:
        public_key_a = ECC.import_key(public_key_a_pem)
    except Exception as e:
        tracer_l.error(f'exchange_keys --- Invalid public key: {e}')
        return JsonResponse({"error": f"Invalid public key"}, status=400)

    client_public_keys[telegram_user_id] = {
        'public_key': public_key_a_pem,
        'timestamp': time.time()
    }

    cleanup_old_keys()
    crypto_b.generate_keys_with_secret()

    return JsonResponse({
        "public_key": crypto_b.public_key.export_key(format='PEM'),
        "status": "Keys generated successfully"
    })


@csrf_exempt
def phone_number_view(request):
    if request.method == 'POST':
        form = PhoneNumberForm(request.POST)

        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']

            user = AuthUser.objects.filter(phone=phone_number).first()
            new_auth_telegram = AuthAdditionalUser.objects.filter(user=user).first()

            if new_auth_telegram and (user.confirmed_user is True):
                code = random.randint(10000, 99999)
                user_verify_code[user.phone] = code

                telegram_message_manager = ManageTelegramMessages()
                telegram_message_manager.send_code_to_user(new_auth_telegram.id_telegram, code)

                tracer_l.debug(f'phone_number_view. Код отправлен: {user.id}')

                request.session['phone_number'] = phone_number
                return JsonResponse({'status': 'success', 'message': 'Код отправлен'})
            else:
                referral_link = f"https://t.me/LetychkaRobot?start=login"

                return JsonResponse({
                    'status': 'success',
                    'message': 'phone init',
                    'referral_link': referral_link,
                })

    else:
        form = PhoneNumberForm()

    return render(request, 'phone_number_form.html', {'form': form, 'code_form': False})


@csrf_exempt
def verify_code_view(request):
    if request.method == 'POST':
        verification_code = request.POST.get('verification_code')
        phone_number = request.session.get('phone_number')

        user = AuthUser.objects.filter(phone=phone_number).first()

        if user:
            if user_verify_code.get(user.phone) == int(verification_code):
                login(request, user)
                request.session['user_id'] = user.id

                return redirect('create')

            else:
                return JsonResponse({'status': 'error', 'message': 'Неверный код'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Пользователь не найден'})

    tracer_l.debug(f'2 verify_code_view. Неверный запрос')
    return JsonResponse({'status': 'error', 'message': 'Неверный запрос'})


def check_telegram_hash(auth_data):
    string_to_check = '\n'.join([
        f"{key}={value}" for key, value in sorted(auth_data.items()) if key != 'hash'
    ])

    secret = TELEGRAM_BOT_TOKEN.encode('UTF-8')
    hash_check = hmac.new(secret, string_to_check.encode('UTF-8'), hashlib.sha256).hexdigest()

    return hash_check


@method_decorator(csrf_exempt, name='dispatch')
class TelegramAuthView(View):
    def dispatch(self, request, *args, **kwargs):
        tracer_l.warning(f"TelegramAuthView dispatch method={request.method} GET={request.GET} POST={request.POST}")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        auth_data = request.POST

        tracer_l.warning("TelegramAuthView called")
        tracer_l.warning(f"{auth_data}")

        try:
            auth_date = auth_data.get('auth_date', 999)
            first_name = auth_data.get('first_name', '')
            last_name = auth_data.get('last_name', '')
            telegram_id = auth_data.get('id', 0)
            username = auth_data.get('username', None)

            if not check_telegram_hash(auth_data):
                tracer_l.warning("Invalid hash")
                return JsonResponse({'status': 'Error', 'message': 'Invalid auth'}, status=400)

            if (int(time.time()) - int(auth_date) > 600) or (int(telegram_id) == 0):
                tracer_l.warning("Invalid timestamp or ID")
                return JsonResponse({'status': 'error', 'message': 'Invalid data'}, status=400)

            existing_user = AuthAdditionalUser.objects.filter(id_telegram=telegram_id).first()
            tracer_l.debug(f'TelegramAuthView: existing_user: {existing_user}')

            if existing_user:
                auth_user = existing_user.user
            else:
                auth_user = AuthUser.objects.create(
                    username=str(telegram_id) if username is None else username,
                    first_name=first_name,
                    last_name=last_name
                )
                auth_user.save()

                telegram_auth = AuthAdditionalUser.objects.create(
                    user=auth_user,
                    id_telegram=telegram_id
                )
                telegram_auth.save()

                plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
                subscription = Subscription.objects.create(
                    staff_id=auth_user.id_staff,
                    plan_name=plan_name,
                    end_date=end_date,
                    status=status,
                    billing_cycle=billing_cycle,
                    discount=0.00
                )
                subscription.save()

            login(request, auth_user)
            request.session['user_id'] = auth_user.id

            tracer_l.debug(f'TelegramAuthView: user has been login in')

            auth_data = {
                'id': telegram_id,
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'auth_date': auth_date,
                'hash': request.GET.get('hash') or request.POST.get('hash')
            }
            return render(request, "telegram.html", {
                "target_url": reverse('create'),
                "auth_data": auth_data  # Добавляем данные для шаблона
            })

        except Exception as fail:
            import traceback
            tracer_l.error(f'Error: {fail}\n{traceback.format_exc()}')
            tracer_l.error(f'TelegramAuthView: error in tg auth: {fail}')
            return JsonResponse({'status': 'error', 'message': 'Internal server error'}, status=500)

    def get(self, request):
        auth_data = request.GET

        tracer_l.warning("TelegramAuthView called")
        tracer_l.warning(f"{auth_data}")

        try:
            auth_date = auth_data.get('auth_date', 999)
            first_name = auth_data.get('first_name', '')
            last_name = auth_data.get('last_name', '')
            telegram_id = auth_data.get('id', 0)
            username = auth_data.get('username', None)

            if not check_telegram_hash(auth_data):
                print("Invalid hash")
                return JsonResponse({'status': 'Error', 'message': 'Invalid auth'}, status=400)

            if (int(time.time()) - int(auth_date) > 600) or (telegram_id == 0):
                return JsonResponse({'status': 'error', 'message': 'Invalid data'}, status=400)

            existing_user = AuthAdditionalUser.objects.filter(id_telegram=telegram_id).first()

            if existing_user:
                auth_user = existing_user.user
            else:
                auth_user = AuthUser.objects.create(
                    username=str(telegram_id) if username is None else username,
                    first_name=first_name,
                    last_name=last_name
                )
                auth_user.save()

                telegram_auth = AuthAdditionalUser.objects.create(
                    user=auth_user,
                    id_telegram=telegram_id
                )
                telegram_auth.save()

                plan_name, end_date, status, billing_cycle, discount = init_free_subscription()
                subscription = Subscription.objects.create(
                    staff_id=auth_user.id_staff,
                    plan_name=plan_name,
                    end_date=end_date,
                    status=status,
                    billing_cycle=billing_cycle,
                    discount=0.00
                )
                subscription.save()

            login(request, auth_user)
            request.session['user_id'] = auth_user.id

            tracer_l.debug(f'TelegramAuthView: success')

            # return redirect('create')
            auth_data = {
                'id': telegram_id,
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'auth_date': auth_date,
                'hash': request.GET.get('hash') or request.POST.get('hash')
            }
            return render(request, "telegram.html", {
                "target_url": reverse('create'),
                "auth_data": auth_data  # Добавляем данные для шаблона
            })

        except Exception as fail:
            import traceback
            tracer_l.error(f'Error: {fail}\n{traceback.format_exc()}')
            tracer_l.error(f'TelegramAuthView: error in tg auth: {fail}')
            return JsonResponse({'status': 'error', 'message': 'Internal server error'}, status=500)


@check_legal_process
def available_plans(request):
    context = {
        'page_title': 'Выберите оптимальный план подписки | Летучка — создать тест онлайн бесплатно'
    }
    return render(request, 'askify_service/avaible-plans.html', context)


@check_legal_process
def document_view(request, slug):
    file_path = os.path.join(BASE_DIR, 'docs', f'{slug}.md')
    tracer_l.debug(f'file_path: file_path')

    if not os.path.exists(file_path):
        return render(request, '404.html', status=404)

    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    content_html = markdown.markdown(content)

    content = {
        'title': slug.replace('-', ' ').title(), 'content': content_html,
        'year': get_year_now()
    }

    return render(request, 'document.html', content)


@check_legal_process
def blog_view(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)

    ip = request.META.get('REMOTE_ADDR')

    post.add_unique_view(ip)

    file_path = os.path.join(BASE_DIR, 'blog', f'{slug}.md')

    if not os.path.exists(file_path):
        return render(request, '404.html', status=404)

    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    title = content.splitlines()[0].lstrip('# ').strip()
    content_html = markdown.markdown(content)

    view_count_text = get_view_count_text(post.view_count)

    context = {
        'title': title,
        'content': content_html,
        'year': get_year_now(),
        'view_count': f"{view_count_text} • {post.created_at.strftime('%d.%m')}",
        'article_url': f"media/{slug}"
    }

    return render(request, 'blog.html', context)


@csrf_exempt
def terminate_session(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user_id = int(data.get('user_id'))
        received_hash = data.get('hash')

        message = json.dumps({'user_id': user_id, 'hash': received_hash}).encode()

        manage_confident_fields = ManageConfidentFields("config.json")
        ghost_connection = manage_confident_fields.get_confident_key("ghost_connection")
        expected_hash = hmac.new(ghost_connection.encode(), message, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(received_hash, expected_hash):
            return JsonResponse({'status': 'error', 'message': 'Invalid hash.'}, status=403)

        selected_user = AuthUser.objects.filter(id=user_id).first()

        if selected_user:
            logout(request)
            return JsonResponse({'success': True, 'message': 'Session closed successfully.'})

        return JsonResponse({'success': False, 'message': 'Fail in  close session.'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)


def send_verification_email(user):
    token = signing.dumps(user.pk, salt='email-verification')
    verification_link = reverse('verify_email', kwargs={'token': token})
    full_link = f'http://letychka.ru{verification_link}'

    html_message = f"""
    <html>
        <body>
            <h2>Подтверждение почты</h2>
            <p>Привет! Пожалуйста, подтверди свою почту, перейдя по ссылке ниже:</p>
            <a href="{full_link}" style="display: inline-block; padding: 10px 20px; background-color: #007AFF; color: white; text-decoration: none; border-radius: 5px;">
                Подтвердить почту
            </a>
            <p>Если вы не создавали аккаунт, просто проигнорируйте это письмо.</p>
        </body>
    </html>
    """

    send_mail(
        'Подтверждение почты',
        'Это письмо в формате HTML. Пожалуйста, включите поддержку HTML.',
        'support@letychka.ru',
        [user.email],
        html_message=html_message,
        fail_silently=False,
    )


def verify_email(request, token):
    User = get_user_model()

    try:
        user_id = signing.loads(token, salt='email-verification', max_age=3600)
        user = get_object_or_404(User, pk=user_id)
    except signing.BadSignature:
        return redirect('error_page')

    user.confirmed_user = True
    user.save()

    return redirect('create')


class PasswordResetView(View):
    def post(self, request):
        staff_id = get_staff_id(request)
        user = AuthUser.objects.get(id_staff=staff_id)
        email = user.email

        if user:
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            link = request.build_absolute_uri(f'/password_reset_confirm/{uid}/{token}/')

            message = render_to_string('confirmed_data/password_reset_email.html', {'link': link})
            send_mail(
                'Сброс пароля',
                message,
                'support@letychka.ru',
                [email],
                fail_silently=False,
                html_message=message
            )

        return redirect('password_reset_done')


class PasswordResetConfirmView(View):
    def get(self, request, uidb64, token):
        return render(request, 'confirmed_data/password_reset_confirm.html', {'uidb64': uidb64, 'token': token})

    def post(self, request, uidb64, token):
        new_password = request.POST.get('new_password')
        user_id = urlsafe_base64_decode(uidb64).decode()
        user = AuthUser.objects.get(pk=user_id)
        print(new_password)
        if default_token_generator.check_token(user, token):
            user.set_password(new_password)
            user.save()
            return redirect('password_reset_complete')


def password_reset_complete(request):
    return render(request, 'confirmed_data/password_reset_complete.html')


def password_reset_email(request):
    context = {
        'page_title': 'Сброс пароля'
    }
    return render(request, 'confirmed_data/password_message_reset_email.html', context)


def black_ops_launch(request, secret):
    if secret != settings.DEPLOY_WEBHOOK_SECRET:
        return HttpResponse("Forbidden", status=403)

    command = f"nohup {DEPLOY_SCRIPT_PATH} > /dev/null 2>&1 &"

    subprocess.Popen(command, shell=True)
    print('Deployment process started')

    return JsonResponse({"status": "ok", "message": "Deployment process started."})


def health_check_view(request):
    version_file_path = os.path.join(settings.BASE_DIR, 'VERSION.txt')
    try:
        with open(version_file_path, 'r') as f:
            version = f.read().strip()
    except FileNotFoundError:
        version = 'unknown'

    return JsonResponse({'status': 'ok', 'version': version})


def handler403(request, exception=None):
    return render(request, 'askify_service/errors/403.html', status=403)


def handler404(request, exception=None):
    return render(request, 'askify_service/errors/404.html', status=404)


def handler500(request):
    return render(request, 'askify_service/errors/500.html', status=500)
