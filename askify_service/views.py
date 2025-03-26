import json

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.views import View
from django.template.loader import render_to_string
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator
# from asgiref.sync import database_sync_to_async
from django.core import signing
from datetime import timedelta
from django.urls import reverse
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.http import HttpResponseForbidden
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q


from .utils import *
from .models import *
from .forms import *
from .constants import *
from .tracer import *
from .quant import Quant


from askify_app.settings import DEBUG, BASE_DIR
from askify_app.middleware import check_blocked, subscription_required, check_legal_process


import openai
import markdown
import requests
import aiofiles
import PyPDF2
from Crypto.PublicKey import ECC
import vk_api


from datetime import datetime, timedelta
import base64
import asyncio
import time
import hashlib
import uuid
import random
import os
import re
import hmac


os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"


tracer_l = TracerManager(TRACER_FILE)
crypto_b = Quant()


@check_legal_process
def index(request):
    start_date = "01.01.2025"

    context = {
        'username': request.user.username if request.user.is_authenticated else 0,
        'total_users': calculate_total_users(start_date, 1200),
    }

    tracer_l.tracer_charge(
        'INFO', f"{get_client_ip(request)}", "PROMO PAGE", "load page")

    return render(request, 'askify_service/index.html', context)


# @subscription_required
@login_required
def page_create_survey(request):
    current_id_staff = get_staff_id(request)

    subs = Subscription.objects.get(staff_id=current_id_staff)
    tokens_limit = get_token_limit(subs.plan_name)

    manage_tokens_limits = ManageTokensLimits(current_id_staff)
    tokens_used = manage_tokens_limits.get_usage_tokens()

    print('---')
    print(type(tokens_limit), tokens_limit, type(tokens_used), tokens_used)
    print('---')

    subscription_level = get_subscription_level(request)

    tracer_l.tracer_charge(
        'INFO', request.user.username, page_create_survey.__name__, "load page")

    diff_limit = tokens_limit - tokens_used

    faq_file_path = os.path.join(BASE_DIR, 'docs', f'faq-s.md')
    with open(faq_file_path, 'r', encoding='utf-8') as f:
        faq_content = f.read()
        faq_html = markdown.markdown(faq_content)

    context = {
        "page_title": "Создать тест",
        'tokens_f': get_format_number(diff_limit) if diff_limit > 0 else 0,
        'limit_tokens': tokens_limit,
        'username': get_username(request),
        'subscription_level': subscription_level,
        'faq_html': faq_html
    }

    return render(request, 'askify_service/text_input.html', context)


@login_required
def page_history_surveys(request):
    try:
        surveys_data = get_all_surveys(request)

        survey_paginator = PaginatorManager(surveys_data, per_page=5)
        surveys_page = survey_paginator.get_page(1)

        context = {
            'page_title': 'Предыдущие тесты',
            'surveys_data': dict(surveys_page.object_list),
            'username': get_username(request),
            'paginator': survey_paginator.get_paginator(),
        }
        print(surveys_page)

    except Exception as fatal:
        context = {
            'page_title': 'Предыдущие тесты',
            'username': get_username(request)
        }
        tracer_l.tracer_charge(
            'ERROR', request.user.username, page_history_surveys.__name__, f"{fatal}")
    return render(request, 'askify_service/history.html', context)


@login_required
def load_more_surveys(request):
    if request.method == "GET" and request.headers.get('x-requested-with') == 'XMLHttpRequest':

        page_number = request.GET.get('page', 2)
        surveys_data = get_all_surveys(request)

        survey_paginator = PaginatorManager(surveys_data, per_page=5)
        surveys_page = survey_paginator.get_page(page_number)

        surveys_list = [
            {
                'survey_id': survey_id,
                'title': survey_data['title'],
                'update': survey_data['update'],
            }
            for survey_id, survey_data in surveys_page
        ]

        return JsonResponse({
            'surveys': surveys_list,
            'has_next': surveys_page.has_next(),
            'next_page': surveys_page.next_page_number() if surveys_page.has_next() else None,
        })
    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def drop_survey(request, survey_id):
    survey_obj = Survey.objects.get(survey_id=uuid.UUID(survey_id))
    survey_obj.delete()
    try:
        survey_user_answers = get_object_or_404(UserAnswers, survey_id=uuid.UUID(survey_id))
        survey_user_answers.delete()
        tracer_l.tracer_charge(
            'INFO', request.user.username, drop_survey.__name__, "Delete Survey")
    except Exception as pass_fail:
        print("Не найдено записей", pass_fail)
        tracer_l.tracer_charge(
            'INFO', request.user.username, drop_survey.__name__, "Delete UserAnswers", pass_fail)
    return redirect('history')


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

    @staticmethod
    def check_token_limits(token_used, token_limit) -> bool:
        if token_used >= token_limit:
            return True
        return False


@method_decorator(login_required, name='dispatch')
@method_decorator(check_blocked, name='dispatch')
@method_decorator(subscription_required, name='dispatch')
class ManageSurveysView(View):
    async def post(self, request):
        if request.method == 'POST':
            try:
                request_from_user = json.loads(request.body)
                question_count = request_from_user['questions']
                text_from_user = request_from_user['text']

                print(question_count, text_from_user)
                tracer_l.tracer_charge(
                    'INFO', request.user.username, ManageSurveysView.post.__name__,
                    f"{question_count} {text_from_user}")

                if question_count.isdigit():
                    if int(question_count) > 20 or int(question_count) < 0:
                        return JsonResponse({'error': 'Недоступное кол-во вопросов :('}, status=400)
                else:
                    return JsonResponse({'error': 'Кол-во вопросов должно быть число'}, status=400)

                staff_id = get_staff_id(request)
                subscription_object = Subscription.objects.get(staff_id=staff_id)
                plan_name = subscription_object.plan_name

                token_limit = get_token_limit(plan_name)

                # Получение кол-ва использованных токенов
                manage_tokens_limits = ManageTokensLimits(staff_id)
                total_used_token_per_period = manage_tokens_limits.get_usage_tokens()
                # total_used_token_per_period = 1_490_000
                print("total_used_token_per_period", total_used_token_per_period)

                if plan_name.lower() == 'стартовый':
                    if total_used_token_per_period >= token_limit:
                        return JsonResponse({
                            'error': 'Токены закончились :(\n\nОзнакомьтесь с тарифами на странице профиля.'},
                            status=403
                        )
                else:
                    if total_used_token_per_period >= token_limit:
                        return JsonResponse({
                            'error': 'Токены закончились :(\n\nОзнакомьтесь с тарифами на странице профиля.'}, status=403)

                try:
                    # time.sleep(9999)
                    print(f"\n\nGEN STAAAART")

                    # tracer_l.tracer_charge(
                    #     'ADMIN', request.user.username, ManageSurveysView.post.__name__,
                    #     f"GEN STAAAART")

                    manage_generate_surveys_text = ManageGenerationSurveys(request, text_from_user, question_count)
                    generated_text = await manage_generate_surveys_text.github_gpt()

                    # tracer_l.tracer_charge(
                    #     'ADMIN', request.user.username, ManageSurveysView.post.__name__,
                    #     f"{generated_text}")

                    if generated_text.get('success'):
                        tokens_used = generated_text.get('tokens_used')
                        cleaned_generated_text = generated_text.get('generated_text')
                        print(f"\n\nGEN TEST: {generated_text}")
                        # tracer_l.tracer_charge(
                        #     'ADMIN', request.user.username, ManageSurveysView.post.__name__,
                        #     f"{cleaned_generated_text}")
                    else:
                        return JsonResponse({'error': 'Произошла ошибка :(\nПожалуйста, попробуйте позже'}, status=429)

                    # cleaned_generated_text = generated_text
                    # tracer_l.tracer_charge(
                    #     'INFO', request.user.username, ManageSurveysView.post.__name__,
                    #     f"success json.loads: {cleaned_generated_text.get('title')}")
                # except (json.JSONDecodeError, TypeError) as json_error:
                    # tracer_l.tracer_charge(
                    #     'ERROR', request.user.username, ManageSurveysView.post.__name__,
                    #     "text is not valid JSON", str(json_error), "status: 400")
                    # return JsonResponse({'error': str(json_error)}, status=400)
                except Exception as fail:
                    # tracer_l.tracer_charge(
                    #     'CRITICAL', request.user.username, ManageSurveysView.post.__name__,
                    #     f"{fail}", "status: 400")
                    return JsonResponse({'error': 'Опаньки :(\n\nК сожалению, не удалось составить тест'}, status=400)

                try:
                    print(f"\n\n---- ТОКЕНОВ ИСПОЛЬЗОВАНО: {tokens_used}\n\n")
                    new_survey_id = uuid.uuid4()

                    survey = Survey(
                        survey_id=new_survey_id,
                        title=cleaned_generated_text['title'],
                        id_staff=get_staff_id(request)
                    )
                    survey.save_questions(cleaned_generated_text['questions'])
                    survey.save()

                    _tokens_used = TokensUsed(
                        id_staff=get_staff_id(request),
                        tokens_survey_used=tokens_used
                    )
                    _tokens_used.save()

                    tracer_l.tracer_charge(
                        'DB', request.user.username, ManageSurveysView.post.__name__, "success save to DB")

                    return JsonResponse({'survey': cleaned_generated_text, 'survey_id': f"{new_survey_id}"}, status=200)
                except Exception as fail:
                    user = await sync_to_async(str)(request.user.username)
                    tracer_l.tracer_charge(
                        'INFO', user, ManageSurveysView.post.__name__,
                        "error in save to DB", f"{fail}")
                    return JsonResponse(
                        {'error': 'Ошибочка :(\n\nПожалуйста, попробуйте позже'}, status=400)

            # except json.JSONDecodeError as json_decode:
            #     # tracer_l.tracer_charge(
            #     #     'ERROR', request.user.username, ManageSurveysView.post.__name__,
            #     #     "Invalid JSON in request body", f"{json_decode}",
            #     #     f"status: 400")
            #     return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
            except Exception as e:
                # tracer_l.tracer_charge(
                #     'CRITICAL', request.user.username, ManageSurveysView.post.__name__,
                #     "FATAL Exception", f"{e}",
                #     f"status: 500")
                return JsonResponse({'error': str(e)}, status=500)

        # tracer_l.tracer_charge(
        #     'CRITICAL', request.user.username, ManageSurveysView.post.__name__,
        #     "Invalid request method", "status: 400")
        return JsonResponse({'error': 'Invalid request method'}, status=400)


@login_required
def get_all_surveys(request):
    staff_id = get_staff_id(request)
    if staff_id is None:
        return {}

    surveys = Survey.objects.filter(id_staff=staff_id).order_by('-updated_at')
    response_data_all = {}

    for survey in surveys:
        format_date_update = get_formate_date(survey.updated_at)
        response_data_all[str(survey.survey_id)] = {
            'title': survey.title, 'update': format_date_update
        }

    return response_data_all


class FileUploadView(View):
    # @login_required
    # @subscription_required
    async def post(self, request):
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)

        uploaded_file = request.FILES['file']
        if uploaded_file.size > 5 * 1024 * 1024:
            return JsonResponse({'error': 'File too large. Max size is 5 MB.'}, status=400)

        data = self.read_file_data(uploaded_file)
        if data == -1:
            return JsonResponse({'error': 'Файл не является PDF'})

        print("\n--- ТЕСТ ГЕНЕРИРУЕТСЯ ---")
        try:
            manage_generate_surveys_text = ManageGenerationSurveys(request, data, '5')
            generated_text = await manage_generate_surveys_text.github_gpt()

            if generated_text.get('success'):
                tokens_used = generated_text.get('tokens_used')
                cleaned_generated_text = generated_text.get('generated_text')
            else:
                return JsonResponse({'error': 'Произошла ошибка при создании теста'}, status=429)
        except TypeError:
            return JsonResponse({'error': 'К сожалению, не удалось выполнить запрос'}, status=400)

        new_survey_id = uuid.uuid4()
        survey = Survey(
            survey_id=new_survey_id,
            title=cleaned_generated_text['title'],
            id_staff=get_staff_id(request)
        )
        survey.save_questions(cleaned_generated_text['questions'])
        survey.save()

        _tokens_used = TokensUsed(
            id_staff=get_staff_id(request),
            tokens_survey_used=tokens_used
        )
        _tokens_used.save()

        return JsonResponse({'success': True, 'message': 'Success create survey', 'survey_id': f"{new_survey_id}"})

    def read_file_data(self, uploaded_file):
        full_text = ""
        print(uploaded_file, os.path.splitext(str(uploaded_file))[1])

        if os.path.splitext(str(uploaded_file))[1] != '.pdf':
            return -1

        if uploaded_file.content_type == 'application/pdf':
            reader = PyPDF2.PdfReader(uploaded_file)

            for page in reader.pages:
                text = page.extract_text()
                if text:
                    full_text += text.strip()
        else:
            return -1

        truncated_text = full_text[:2**14]
        return truncated_text


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

        survey_obj = UserAnswers.objects.filter(survey_id=survey_id)

        if survey_obj.exists():
            survey_obj.delete()

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

        subscription_check = SubscriptionCheck()
        subs_level = subscription_check.get_subscription_level(subscription.plan_name)

        if subscription.status == 'active' and (subs_level == 0 or subs_level > 1):
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
                    feedback_data=ai_feedback.get('generated_text')
                )

                TokensUsed.objects.create(
                    id_staff=get_staff_id(request),
                    tokens_feedback_used=ai_feedback.get('tokens_used')
                )

        context = {
            'score': correct_count, 'total': user_answers, 'survey_id': survey_id,
            'subscription_level': get_subscription_level(request)
        }
        return render(request, 'result.html', context)

    def get(self, request, survey_id):
        survey_id = uuid.UUID(survey_id)
        survey = get_object_or_404(Survey, survey_id=survey_id)
        questions = json.loads(survey.questions)

        context = {
            'page_title': f'Прохождение теста – {survey.title}',
            'survey': survey,
            'questions': questions,
            'survey_title': survey.title,
            'username': request.user.username if request.user.is_authenticated else None,
        }
        return render(request, 'survey.html', context)


@login_required
# @subscription_required
def result_view(request, survey_id):
    print("result_view", survey_id)

    survey = Survey.objects.get(survey_id=survey_id)
    user_answers = UserAnswers.objects.filter(survey_id=survey_id)
    score = sum(answer.scored_points for answer in user_answers)

    questions = survey.get_questions()
    selected_answers = {answer.selected_answer for answer in user_answers}
    selected_answers_list = list(user_answers.values_list('selected_answer', flat=True))

    try:
        feedback_obj = FeedbackFromAI.objects.filter(survey_id=survey_id).first()

        if feedback_obj is not None:
            feedback_text = re.sub(r'[^a-zA-Zа-яА-Я0-9.,!?;:\s]', '', feedback_obj.feedback_data)
            feedback_text = markdown.markdown(feedback_text)
        else:
            feedback_text = 'Не удалось получить обратную связь от ИИ :('

    except Exception as fail:
        feedback_text = 'Не удалось получить обратную связь от ИИ :('
        tracer_l.tracer_charge(
            "INFO", f"{get_username(request)}", result_view.__name__,
            "WARNING: Fail in get AI feedback", fail)

    subscription_db = Subscription.objects.get(staff_id=get_staff_id(request))
    subscription_check = SubscriptionCheck()
    subscription_level = subscription_check.get_subscription_level(subscription_db.plan_name)

    json_response = {
        'page_title': f'Результаты прохождения теста – {survey.title}',
        'title': survey.title,
        'score': score,
        'total': len(user_answers),
        'survey_id': survey_id,
        'questions': questions,
        'selected_answers': selected_answers,
        'selected_answers_list': selected_answers_list,
        'username': request.user.username if request.user.is_authenticated else None,
        'feedback_text': feedback_text,
        'subscription_level': subscription_level
    }
    # print("result_view", score, len(user_answers))

    return render(request, 'result.html', json_response)


@login_required
def download_survey_pdf(request, survey_id):
    # try:
    survey = get_object_or_404(Survey, survey_id=uuid.UUID(survey_id))
    tracer_l.tracer_charge(
        'INFO', request.user.username, download_survey_pdf.__name__, "View survey in PDF")
    return survey.generate_pdf()
    # except Exception as fatal:
    #     tracer_l.tracer_charge(
    #         'CRITICAL', request.user.username, download_survey_pdf.__name__, "FATAL with View survey in PDF", fatal)


from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.exceptions import ValidationError

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
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        print(form.is_valid(), form.cleaned_data.get('email'))

        if form.is_valid():
            user = form.save()

            tracer_l.tracer_charge(
                'ADMIN', user.username, register.__name__, f"NEW USER")

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
            return JsonResponse({'redirect': '/create'})
        else:
            errors = {field: errors for field, errors in form.errors.items()}
            print(errors)
            return JsonResponse({'errors': errors}, status=400)

    else:
        form = CustomUserCreationForm()

    return render(request, 'register.html', {'form': form})


@check_legal_process
def login_view(request):
    if request.user.is_authenticated:
        return redirect('/create')

    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        username = email.split('@')[0]

        user = authenticate(request, username=username, password=password)
        user_auth = AuthUser.objects.filter(email=email).first()

        if user is not None:
            login(request, user)
            request.session['user_id'] = user.id
            print(request.session.get('user_id'))

            if not DEBUG:
                tracer_l.tracer_charge(
                    'ADMIN', request.user.username, login_view.__name__, f"LOGGED IN")

            return redirect('/create')
        else:
            print('Неверный email или пароль')
            return JsonResponse({'errors': {'email': ['Неверный email или пароль']}}, status=400)

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('login')


def blocked_view(request):
    return render(request, 'askify_service/blocked.html')


VK_CLIENT_ID = 52653516
VK_CLIENT_SECRET = "Qh6Z7Nax0GeXpIzxOJ6S"
VK_REDIRECT_URI = "https://letychka.ru/create/"


def vk_auth(request):
    vk_session = vk_api.VkApi(app_id=VK_CLIENT_ID, client_secret=VK_CLIENT_SECRET)
    auth_url = vk_session.get_auth_url()
    return redirect(auth_url)


def vk_auth_callback(request):
    if request.method == 'GET':
        try:
            code = request.GET.get('code')
            device_id = request.GET.get('device_id')

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, vk_auth_callback.__name__, f"Code: {code}, Device ID: {device_id}")

            if not code or not device_id:
                return JsonResponse({'success': False, 'error': 'Invalid data'})

            url = 'https://api.vk.com/oauth/access_token'
            params = {
                'client_id': VK_CLIENT_ID,
                'client_secret': VK_CLIENT_SECRET,
                'redirect_uri': VK_REDIRECT_URI,
                'code': code,
            }

            response = requests.post(url, params=params)

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, vk_auth_callback.__name__, f"{response} {response.text }")

            response_data = response.json()

            if 'access_token' not in response_data:
                return JsonResponse({'success': False, 'error': 'Failed to get access token'})

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, vk_auth_callback.__name__, f"access_token in response_data: {response_data}")

            access_token = response_data['access_token']
            user_id = response_data['user_id']

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, vk_auth_callback.__name__, f"access_token: {access_token}")

            # Получаем данные пользователя
            vk_session = vk_api.VkApi(token=access_token)
            user_info = vk_session.method('users.get', {'user_ids': user_id, 'fields': 'photo_200'})

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, vk_auth_callback.__name__, f"User Info: {user_info}")

            if user_info:
                first_name = user_info[0]['first_name']
                last_name = user_info[0]['last_name']

                tracer_l.tracer_charge(
                    'ADMIN', request.user.username, vk_auth_callback.__name__,
                    f"Creating user: {first_name} {last_name}")

                # Создаем пользователя
                auth_user = AuthUser.objects.create(
                    username=str(uuid.uuid4()),
                    first_name=first_name,
                    last_name=last_name
                )
                auth_user.save()

                # Создаем дополнительную информацию о пользователе
                add_user = AuthAdditionalUser.objects.create(
                    user=auth_user,
                    id_vk=user_id
                )
                add_user.save()

                # Логиним пользователя
                login(request, auth_user)
                request.session['user_id'] = auth_user.id

                # Перенаправляем на страницу создания теста
                return redirect('create')
            else:
                tracer_l.tracer_charge(
                    'ADMIN', request.user.username, vk_auth_callback.__name__, "Failed to get user info")
                return JsonResponse({'success': False, 'error': 'Failed to get user info'})

        except Exception as e:
            tracer_l.tracer_charge(
                'ADMIN', request.user.username, vk_auth_callback.__name__, f"Error: {e}")
            return JsonResponse({'success': False, 'error': str(e)})

    tracer_l.tracer_charge(
        'ADMIN', request.user.username, vk_auth_callback.__name__, "Invalid request method")

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def profile_view(request, username):
    staff_id = get_staff_id(request)
    user = get_object_or_404(AuthUser, id_staff=staff_id)

    statistics = UserAnswers.calculate_user_statistics(staff_id)

    date_join = get_formate_date(user.date_joined)
    date_last_login = get_formate_date(user.last_login)

    tokens_usage = TokensUsed.get_tokens_usage(staff_id)

    total_tokens_for_surveys = get_format_number(tokens_usage['tokens_survey_used'])
    total_tokens_for_feedback = get_format_number(tokens_usage['tokens_feedback_used'])

    _total_tokens = tokens_usage['tokens_survey_used'] + tokens_usage['tokens_feedback_used']
    total_tokens = get_format_number(_total_tokens)
    print('total_tokens', total_tokens)

    subscription = get_object_or_404(Subscription, staff_id=staff_id)
    subscription_end_date = get_formate_date(subscription.end_date)
    human_readable_plan = subscription.get_human_plan()

    if isinstance(subscription.end_date, str):
        subscription.end_date = datetime.strptime(subscription.end_date, '%Y.%m.%d')

    days_until_end = (subscription.end_date - timezone.now()).days
    print('days_until_end', days_until_end)

    user = request.user
    token = signing.dumps(user.pk, salt='email-verification')

    manage_tokens_limits = ManageTokensLimits(staff_id)
    total_used_token_per_period = manage_tokens_limits.get_usage_tokens()
    # total_used_token_per_period = 1_490_000
    print("total_used_token_per_period", total_used_token_per_period)

    user_data = {
        'page_title': f'Профиль {username}',
        'username': username,
        'email': 'E-mail: ' + user.email if user.email is not None else '',
        'password': f'Пароль: *********' if user.password != '' else '',
        'phone': 'Телефон: ' + user.phone if user.phone is not None else '',
        'date_join': date_join,
        'date_last_login': date_last_login,
        'statistics': statistics,
        'tokens': {
            'surveys': total_tokens_for_surveys,
            'feedback': total_tokens_for_feedback,
            'total_tokens': total_tokens,
            'limit_tokens': get_format_number(get_token_limit(subscription.plan_name))
        },
        'subscription': {
            'plan_name': human_readable_plan,
            'plan_end_date': f"заканчивается {subscription_end_date}" if days_until_end > 0 else "истёк :(",
            'days_until_end': days_until_end
        },
        'subscription_level': get_subscription_level(request),
        'token': token
    }

    return render(request, 'profile.html', user_data)


def get_subscription_level(request):
    subscription_db = Subscription.objects.get(staff_id=get_staff_id(request))
    subscription_check = SubscriptionCheck()
    return subscription_check.get_subscription_level(subscription_db.plan_name)


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

    all_users = AuthUser.objects.all().count()

    if user.is_superuser:
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        selected_subscription = Subscription.objects.all()

        if start_date and end_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d')
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d') + timezone.timedelta(days=1)

            selected_users = AuthUser.objects.filter(date_joined__range=(start_date, end_date)).count()
            total_surveys = Survey.objects.filter(updated_at__range=(start_date, end_date)).count()
            total_answers = UserAnswers.objects.filter(created_at__range=(start_date, end_date)).count()
            subscriptions = Subscription.objects.filter(start_date__range=(start_date, end_date)).count()

            user_activities = UserActivity.objects.filter(created_at__range=(start_date, end_date)).values('id_staff', 'ip_address', 'created_at')
            user_activities_count = UserActivity.objects.filter(created_at__range=(start_date, end_date)).count()

        else:
            selected_users = total_surveys = subscriptions = total_answers = 0
            user_activities = UserActivity.objects.none()
            user_activities_count = 0

        try:
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
                        'amount': f'{get_format_number(payment.amount / 100)} руб',
                        'date': get_formate_date(subscription.start_date),
                    })

            context = {
                'username': request.user.username,
                'selected_users': selected_users,
                # 'usernames': usernames,
                'total_users': all_users,
                'total_surveys': total_surveys,
                'total_answers': total_answers,
                'subscriptions': subscriptions,
                'user_activities': user_activities,
                'count_activities': user_activities_count,
                'selected_subscription': selected_subscription,
                'data': payment_data
            }

            return render(request, 'admin.html', context)
        except Exception as fail:
            tracer_l.tracer_charge(
                'ERROR', get_username(request), 'error in admin_stats', fail)

            context = {
                'username': request.user.username,
                'selected_users': selected_users,
                'total_users': all_users,
                'total_surveys': total_surveys,
                'total_answers': total_answers,
                'subscriptions': subscriptions,
                'user_activities': user_activities,
                'count_activities': user_activities_count,
                'selected_subscription': selected_subscription,
            }

            return render(request, 'admin.html', context)

    else:
        return redirect(f'/profile/{request.user.username}')


MODEL_MAP = {
    'Survey': ('📝 Опросы', Survey),
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


def db_search(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 3:
        return JsonResponse([])

    models_to_search = [
        (Survey, ['survey_id', 'title', 'id_staff']),
        (AuthUser, ['username', 'email', 'id_staff']),
        (UserAnswers, ['survey_id', 'id_staff']),
        (Subscription, ['staff_id', 'plan_name']),
    ]

    results = []
    for model, fields in models_to_search:
        q_objects = Q()
        for field in fields:
            q_objects |= Q(**{f'{field}__icontains': query})

        for item in model.objects.filter(q_objects)[:10]:
            results.append({
                'model': model.__name__,
                'field': ', '.join(fields),
                'value': str(item),
                'source': get_related_info(item)
            })

    return JsonResponse(results, safe=False)


def get_related_info(item):
    """ Получение связанных данных """
    if hasattr(item, 'id_staff'):
        try:
            user = AuthUser.objects.get(id_staff=item.id_staff)
            return f"{user.first_name} {user.last_name} ({user.email})"
        except AuthUser.DoesNotExist:
            return "Неизвестный пользователь"
    return "Нет связанных данных"


def block_by_staff_id(request, id_staff):
    maybe_admin = get_object_or_404(AuthUser, username=request.user.username)

    if maybe_admin.is_superuser:
        user = get_object_or_404(AuthUser, id_staff=id_staff)
        BlockedUsers.objects.get_or_create(ip_address=get_client_ip(request), reason=f'Blocked user {user.username}')
        return redirect('stats2975')

    return redirect('login')


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

        print(phone, email)
        print("amount", amount)

        plan_prices = {
            'Начальный': 0,
            'Стандартный': 220,
            'Премиум': 590,
            'Ультра': 990
        }

        if int(amount) != plan_prices.get(description):
            return JsonResponse({'Success': False, 'Message': 'Неверная сумма.'}, status=400)

        order_id = generate_payment_id()
        print('приход', order_id)

        items = [
            {
                "Name": "Премиум план",
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

        tracer_l.tracer_charge(
            'ADMIN', f"{get_username(request)}",
            'PaymentInitiateView',
            f"WANT TO BUY!!!")

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

        print()
        for key, value in response_data.items():
            print(key, value)
        print()

        if response_data.get('Success'):
            subscription_obj = Subscription.objects.filter(staff_id=get_staff_id(request))
            if subscription_obj.exists():
                subscription_obj.delete()

            # TODO: Сделать как транзакцию
            # Инициализация тарифного плана
            subscription = Subscription.objects.create(
                staff_id=get_staff_id(request),
                plan_name=description,
                end_date=datetime.now() + timedelta(days=30),
                status='inactive',
                billing_cycle='monthly',
                discount=0.00
            )
            subscription.save()
            # Инициализация оплаты
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
                subscription = Subscription.objects.get(staff_id=get_staff_id(request))

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
                    print("Срок действия платежа истек.")
                    return render(request, 'payments/pay_status.html', error_payment_data)

                elif payment_status == 'CONFIRMED':
                    payment.status = 'completed'
                    payment.save()

                    subscription.start_date = datetime.now()
                    subscription.status = 'active'
                    subscription.save()

                    formatted_amount = f"{payment.amount / 100:,.2f}".replace(',', ' ').replace('.', ',') + " RUB"

                    payment_details = [
                        {"label": "Сумма", "value": formatted_amount},
                        {"label": "ID платежа", "value": payment.payment_id},
                        {"label": "ID заказа", "value": payment.order_id},
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

                        auth_user = AuthUser.objects.get(id_staff=get_staff_id(request))
                        additional_auth_user = AuthAdditionalUser.objects.get(user=auth_user)

                        telegram_message_manager = ManageTelegramMessages()
                        telegram_message_manager.send_message(TELEGRAM_CHAT_ID, message)
                        telegram_message_manager.send_message(additional_auth_user.id_telegram, message)

                    except Exception as fail:
                        tracer_l.tracer_charge(
                            'INFO', f"{get_username(request)}",
                            PaymentSuccessView.__name__,
                            f'Fail while send info about payment to Telegram', fail)

                    return render(request, 'payments/pay_status.html', payment_data)
                else:
                    print("Статус платежа: ", payment_status)
                    return render(request, 'payments/pay_status.html', error_payment_data)
            except Payment.DoesNotExist:
                error_payment_data = {
                    "page_title": "Ошибка оплаты",
                    "payment_status": "Неудача",
                    "text_status": "Платеж не существует",
                }
                return render(request, 'payments/pay_status.html', error_payment_data)
        else:
            subscription = Subscription.objects.get(staff_id=get_staff_id(request))

            payment_data = {
                "payment_status": "Не удалось", "page_title": "Ошибка при оплате",
                "text_status": "К сожалению, не удалось активировать план :(",
                "plan_name": subscription.get_human_plan(),
            }
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

            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'confirm_user',
                f"Created additional auth for user: {telegram_user_id}")

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
            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'one_click_auth',
                f"User already linked: {telegram_user_id}")
            return user

        user = AuthUser.objects.filter(username=username).first()

        if user:
            new_auth_telegram, created = AuthAdditionalUser.objects.get_or_create(
                user=user,
                defaults={
                    'id_telegram': int(telegram_user_id),
                }
            )
            if not created:
                tracer_l.tracer_charge(
                    'ADMIN', f"telegram_id {telegram_user_id}",
                    'one_click_auth',
                    f"AuthAdditionalUser already exists for user: {user.id}")

            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'one_click_auth',
                f"Linked existing user: {telegram_user_id} to phone: {user.phone}")
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
            if not created:
                tracer_l.tracer_charge(
                    'ADMIN', f"telegram_id {telegram_user_id}",
                    'one_click_auth',
                    f"AuthAdditionalUser already exists for new user: {user.id}")

            tracer_l.tracer_charge(
                'ADMIN', f"telegram_id {telegram_user_id}",
                'one_click_auth',
                f"Created new user: {telegram_user_id}")

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

        tracer_l.tracer_charge(
            'ADMIN', f"telegram_id {telegram_user_id}",
            'one_click_auth_view',
            f"User authorized via one-click link: {telegram_user_id}")

        login(request, user)
        request.session['user_id'] = user.id

        return redirect('create')

    except Exception as fail:
        tracer_l.tracer_charge(
            'ERROR', 'one_click_auth_view',
            'one_click_auth_view',
            f"Error: {fail}")
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

        tracer_l.tracer_charge(
            'ADMIN', get_client_ip(request),
            'confirm_user',
            f"Success auth: hash is OK for {first_name} {username}")

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

        tracer_l.tracer_charge(
            'ERROR', get_client_ip(request),
            'exchange_keys',
            f"Invalid JSON: {e}")

        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        public_key_a_pem = body["public_key"]
        telegram_user_id = body["telegram_user_id"]
    except KeyError as e:
        print(f"Missing field: {e}")

        tracer_l.tracer_charge(
            'ERROR', get_client_ip(request),
            'exchange_keys',
            f"Missing field: {e}")

        return JsonResponse({"error": f"Missing field: {e}"}, status=400)

    try:
        public_key_a = ECC.import_key(public_key_a_pem)
    except Exception as e:

        tracer_l.tracer_charge(
            'ERROR', get_client_ip(request),
            'exchange_keys',
            f"Invalid public key: {e}")

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

                tracer_l.tracer_charge(
                    'ADMIN', get_client_ip(request),
                    'phone_number_view',
                    f"phone_number_view: {user.id}, {code}")

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
                tracer_l.tracer_charge(
                    'ADMIN', get_client_ip(request),
                    'phone_number_view',
                    f"3 verify_code_view: {user.id} {user.username}")

                login(request, user)
                request.session['user_id'] = user.id

                return redirect('create')

            else:
                return JsonResponse({'status': 'error', 'message': 'Неверный код'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Пользователь не найден'})

    tracer_l.tracer_charge(
        'ADMIN', get_client_ip(request),
        'phone_number_view',
        f"2 verify_code_view: {get_username(request)} Неверный запрос")
    return JsonResponse({'status': 'error', 'message': 'Неверный запрос'})


def check_telegram_hash(auth_data):
    string_to_check = '\n'.join([
        f"{key}={value}" for key, value in sorted(auth_data.items()) if key != 'hash'
    ])

    secret = TELEGRAM_BOT_TOKEN.encode('UTF-8')
    hash_check = hmac.new(secret, string_to_check.encode('UTF-8'), hashlib.sha256).hexdigest()

    return hash_check


class TelegramAuthView(View):
    def post(self, request):
        print("TelegramAuthView called")
        auth_data = request.POST

        tracer_l.tracer_charge(
            'INFO', get_client_ip(request),
            'try tg auth',
            f"request.POST: пришел в ТГ")

        try:
            auth_date = auth_data.get('auth_date', 999)
            first_name = auth_data.get('first_name', '')
            last_name = auth_data.get('last_name', '')
            telegram_id = auth_data.get('id', 0)
            username = auth_data.get('username', None)

            tracer_l.tracer_charge(
                'INFO', get_username(request),
                'try tg auth',
                f"{type(telegram_id)} {telegram_id}, auth_data: {auth_data}")

            if not check_telegram_hash(auth_data):
                print("Invalid hash")
                return JsonResponse({'status': 'Error', 'message': 'Invalid auth'}, status=400)

            if (int(time.time()) - int(auth_date) > 600) or (telegram_id == 0):
                return JsonResponse({'status': 'error', 'message': 'Invalid data'}, status=400)

            existing_user = AuthAdditionalUser.objects.filter(id_telegram=telegram_id).first()

            tracer_l.tracer_charge(
                'INFO', get_username(request),
                'try tg auth',
                f"{existing_user}")

            if existing_user:
                auth_user = existing_user.user
                tracer_l.tracer_charge(
                    'INFO', get_username(request),
                    'try tg auth',
                    f"{auth_user}")
            else:
                tracer_l.tracer_charge(
                    'INFO', get_username(request),
                    'try tg auth',
                    f"not exist{existing_user}")

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

            tracer_l.tracer_charge(
                'INFO', get_username(request),
                'try tg auth',
                f"login(request, {auth_user}, {auth_user.id})")

            login(request, auth_user)
            request.session['user_id'] = auth_user.id

            tracer_l.tracer_charge(
                'ADMIN', username, 'TelegramAuthView', f"user has been login in")

            return redirect('create')
        except Exception as fail:
            tracer_l.tracer_charge('ERROR', f"{get_client_ip(request)}", 'error in tg auth', fail)
            return JsonResponse({'status': 'error', 'message': 'Internal server error'}, status=500)

    def get(self, request):
        print("TelegramAuthView called")
        auth_data = request.GET

        tracer_l.tracer_charge(
            'INFO', get_client_ip(request),
            'try tg auth',
            f"request.GET: пришел в ТГ")

        try:
            auth_date = auth_data.get('auth_date', 999)
            first_name = auth_data.get('first_name', '')
            last_name = auth_data.get('last_name', '')
            telegram_id = auth_data.get('id', 0)
            username = auth_data.get('username', None)

            tracer_l.tracer_charge(
                'INFO', get_username(request),
                'try tg auth',
                f"{type(telegram_id)} {telegram_id}, auth_data: {auth_data}")

            if not check_telegram_hash(auth_data):
                print("Invalid hash")
                return JsonResponse({'status': 'Error', 'message': 'Invalid auth'}, status=400)

            if (int(time.time()) - int(auth_date) > 600) or (telegram_id == 0):
                return JsonResponse({'status': 'error', 'message': 'Invalid data'}, status=400)

            existing_user = AuthAdditionalUser.objects.filter(id_telegram=telegram_id).first()

            tracer_l.tracer_charge(
                'INFO', get_username(request),
                'try tg auth',
                f"{existing_user}")

            if existing_user:
                auth_user = existing_user.user
                tracer_l.tracer_charge(
                    'INFO', get_username(request),
                    'try tg auth',
                    f"{auth_user}")
            else:
                tracer_l.tracer_charge(
                    'INFO', get_username(request),
                    'try tg auth',
                    f"not exist{existing_user}")

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

            tracer_l.tracer_charge(
                'INFO', get_username(request),
                'try tg auth',
                f"login(request, {auth_user}, {auth_user.id})")

            login(request, auth_user)
            request.session['user_id'] = auth_user.id

            tracer_l.tracer_charge(
                'ADMIN', username, login_view.__name__, f"user has been login in")

            return redirect('create')
        except Exception as fail:
            tracer_l.tracer_charge('ERROR', f"{get_client_ip(request)}", 'error in tg auth', fail)
            return JsonResponse({'status': 'error', 'message': 'Internal server error'}, status=500)


@check_legal_process
def document_view(request, slug):
    file_path = os.path.join(BASE_DIR, 'docs', f'{slug}.md')
    print(file_path)

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
        'view_count': f"{view_count_text} • {get_formate_date(post.created_at)}",
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
