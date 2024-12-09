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
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator

from .utils import *
from .models import *
from .forms import *
from .constants import *
from askify_app.settings import DEBUG, BASE_DIR
from askify_app.middleware import check_blocked, subscription_required
from .tracer import *

import openai
import markdown
import requests
import aiofiles
import PyPDF2

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import asyncio
import time
import hashlib
import uuid
import random
import os
import re
import hmac


tracer_l = TracerManager(TRACER_FILE)


def index(request):
    context = {
        'username': request.user.username if request.user.is_authenticated else 0
    }

    tracer_l.tracer_charge(
        'INFO', f"{get_client_ip(request)}", "PROMO PAGE", "load page")

    return render(request, 'askify_service/index.html', context)


@login_required
# @subscription_required
def page_create_survey(request):
    current_id_staff = get_staff_id(request)

    tokens = TokensUsed.objects.filter(id_staff=current_id_staff)

    used_tokens = sum(token.tokens_survey_used for token in tokens)
    limit_tokens = 50_000

    subscription_db = Subscription.objects.get(staff_id=current_id_staff)

    subscription_check = SubscriptionCheck()
    subscription_level = subscription_check.get_subscription_level(subscription_db.plan_name)

    tracer_l.tracer_charge(
        'INFO', request.user.username, page_create_survey.__name__, "load page")

    context = {
        "page_title": "Создать тест",
        'tokens': limit_tokens - used_tokens,
        'tokens_f': get_format_number(limit_tokens - used_tokens),
        'limit_tokens': limit_tokens,
        'username': get_username(request),
        'subscription_level': subscription_level
    }

    return render(request, 'askify_service/text_input.html', context)


@login_required
def page_history_surveys(request):
    try:
        surveys_data = get_all_surveys(request)
        context = {
            'page_title': 'Предыдущие тесты',
            'surveys_data': surveys_data,
            'username': get_username(request)
        }
    except Exception as fatal:
        context = {
            'page_title': 'Предыдущие тесты',
            'username': get_username(request)
        }
        tracer_l.tracer_charge(
            'ERROR', request.user.username, page_history_surveys.__name__, f"{fatal}")
    return render(request, 'askify_service/history.html', context)


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


@method_decorator(login_required, name='dispatch')
@method_decorator(check_blocked, name='dispatch')
@method_decorator(subscription_required, name='dispatch')
class ManageSurveysView(View):
    def post(self, request):
        if request.method == 'POST':
            try:
                text_from_user = json.loads(request.body)
                text_from_user = text_from_user['text']

                try:
                    print(f"\n\nGEN STAAAART")
                    manage_generate_surveys_text = ManageGenerationSurveys(request, text_from_user)
                    generated_text, tokens_used = manage_generate_surveys_text.generate_survey_for_user()
                    print(generated_text, tokens_used)
                    print(f"\n\nGEN TEST: {generated_text}")

                    if (generated_text is None) and (tokens_used is None):
                        return JsonResponse({'error': 'Произошла ошибка :(\nПожалуйста, попробуйте позже'}, status=429)

                    cleaned_generated_text = generated_text
                    tracer_l.tracer_charge(
                        'INFO', request.user.username, ManageSurveysView.post.__name__,
                        f"success json.loads: {cleaned_generated_text.get('title')}")
                except json.JSONDecodeError or TypeError as json_error:
                    tracer_l.tracer_charge(
                        'ERROR', request.user.username, ManageSurveysView.post.__name__,
                        "text is not valid JSON", str(json_error), "status: 400")
                    return JsonResponse({'error': generated_text}, status=400)
                except Exception as fail:
                    tracer_l.tracer_charge(
                        'CRITICAL', request.user.username, ManageSurveysView.post.__name__,
                        f"{fail}", "status: 400")
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

                    return JsonResponse({'survey': cleaned_generated_text, 'survey_id': new_survey_id}, status=200)
                except Exception as fail:
                    tracer_l.tracer_charge(
                        'ERROR', request.user.username, ManageSurveysView.post.__name__,
                        "error in save to DB", f"{fail}")

                if DEBUG:
                    print(cleaned_generated_text)

            except json.JSONDecodeError as json_decode:
                tracer_l.tracer_charge(
                    'ERROR', request.user.username, ManageSurveysView.post.__name__,
                    "Invalid JSON in request body", f"{json_decode}",
                    f"status: 400")
                return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
            except Exception as e:
                tracer_l.tracer_charge(
                    'CRITICAL', request.user.username, ManageSurveysView.post.__name__,
                    "FATAL Exception", f"{e}",
                    f"status: 500")
                return JsonResponse({'error': str(e)}, status=500)

        tracer_l.tracer_charge(
            'CRITICAL', request.user.username, ManageSurveysView.post.__name__,
            "Invalid request method", "status: 400")
        return JsonResponse({'error': 'Invalid request method'}, status=400)


@login_required
def get_all_surveys(request):
    staff_id = get_staff_id(request)
    if staff_id is None:
        return {}

    surveys = Survey.objects.filter(id_staff=staff_id)
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
    def post(self, request):
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)

        uploaded_file = request.FILES['file']
        if uploaded_file.size > 5 * 1024 * 1024:
            return JsonResponse({'error': 'File too large. Max size is 5 MB.'}, status=400)

        data = self.read_file_data(uploaded_file)
        if data == -1:
            return JsonResponse({'error': 'Файл не является PDF'})

        # manage_generate_surveys_text = ManageGenerationSurveys(request, data)
        # generated_text, tokens_used = manage_generate_surveys_text.generate_survey_for_user()
        print("\n--- ТЕСТ ГЕНЕРИРУЕТСЯ ---")
        try:
            manage_generate_surveys_text = ManageGenerationSurveys(request, data)
            generated_text, tokens_used = manage_generate_surveys_text.generate_survey_for_user()
            if (generated_text is None) and (tokens_used is None):
                return JsonResponse({'error': 'Произошла ошибка при создании теста'}, status=429)
        except TypeError:
            return JsonResponse({'error': 'К сожалению, не удалось выполнить запрос'}, status=400)

        new_survey_id = uuid.uuid4()
        survey = Survey(
            survey_id=new_survey_id,
            title=generated_text['title'],
            id_staff=get_staff_id(request)
        )
        survey.save_questions(generated_text['questions'])
        survey.save()

        _tokens_used = TokensUsed(
            id_staff=get_staff_id(request),
            tokens_survey_used=tokens_used
        )
        _tokens_used.save()

        return JsonResponse({"Success": True})

    def read_file_data(self, uploaded_file):
        full_text = ""

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
# @method_decorator(subscription_required, name='dispatch')
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
                'username': request.user.username if request.user.is_authenticated else None
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

            UserAnswers.objects.get_or_create(
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
            feedback_obj = FeedbackFromAI.objects.filter(survey_id=survey_id)
            if feedback_obj.exists():
                feedback_obj.delete()

            generation_models_control = GenerationModelsControl()
            ai_feedback = generation_models_control.get_feedback_001(
                f"Список вопросов и моих ответов: {user_answers_list}.\n"
                f"Набрано балов: {correct_count} из {len(user_answers)}"
            )

            if ai_feedback.get('success'):
                FeedbackFromAI.objects.create(
                    survey_id=survey_id,
                    id_staff=get_staff_id(request),
                    feedback_data=ai_feedback.get('generated_text')
                )

                _tokens_used = TokensUsed(
                    id_staff=get_staff_id(request),
                    tokens_feedback_used=ai_feedback.get('tokens_used')
                )

        subscription_db = Subscription.objects.get(staff_id=get_staff_id(request))
        subscription_check = SubscriptionCheck()
        subscription_level = subscription_check.get_subscription_level(subscription_db.plan_name)

        context = {
            'score': correct_count, 'total': user_answers, 'survey_id': survey_id,
            'subscription_level': subscription_level
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
@subscription_required
def download_survey_pdf(request, survey_id):
    # try:
    survey = get_object_or_404(Survey, survey_id=uuid.UUID(survey_id))
    tracer_l.tracer_charge(
        'INFO', request.user.username, download_survey_pdf.__name__, "View survey in PDF")
    return survey.generate_pdf()
    # except Exception as fatal:
    #     tracer_l.tracer_charge(
    #         'CRITICAL', request.user.username, download_survey_pdf.__name__, "FATAL with View survey in PDF", fatal)


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
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
            return redirect('/create')
        else:
            error_messages = form.errors
    else:
        form = CustomUserCreationForm()
        error_messages = None
    print(error_messages)
    return render(request, 'register.html', {'form': form, 'error_messages': error_messages})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('/create')

    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            request.session['user_id'] = user.id
            print(request.session.get('user_id'))

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, login_view.__name__, f"user has been login in")

            return redirect('/create')
        else:
            print('Неверное имя пользователя или пароль')
            messages.error(request, 'Неверное имя пользователя или пароль')

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('login')


def vk_auth(request):
    tracer_l.tracer_charge(
        'ERROR', request.user.username, vk_auth.__name__, "start")
    if request.method == 'POST':
        tracer_l.tracer_charge(
            'ERROR', request.user.username, vk_auth.__name__, "post")

        try:
            data = json.loads(request.body)
            vk_id = data.get('vk_id')
            name = data.get('name')
            phone = data.get('phone')
            email = data.get('email')

            user_profile, created = AuthUser.objects.update_or_create(
                vk_id=vk_id,
                defaults={
                    'name': name,
                    'phone': phone,
                    'email': email,
                }
            )
            user = authenticate(request, username=vk_id)
            if user is not None:
                login(request, user)
                request.session['user_id'] = user.id

            tracer_l.tracer_charge(
                'ERROR', request.user.username, vk_auth.__name__, f"success")
            return JsonResponse({'status': 'success', 'created': created})
        except Exception as fail:
            tracer_l.tracer_charge(
                'ERROR', request.user.username, vk_auth.__name__, f"ERROR {fail}")
    return JsonResponse({'status': 'error'}, status=400)


def vk_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state')
    device_id = request.GET.get('device_id')
    code_verifier = request.session.get('code_verifier')

    if code:
        token_url = 'https://id.vk.com/oauth2/access_token'
        params = {
            'client_id': '7b09de637b09de637b09de6325782ab3af77b097b09de631c385ca246d43f689073405f',
            'client_secret': 'our2AXXhor7xIUA82DpH',
            'code': code,
            'redirect_uri': '/create/',
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,
            'device_id': device_id,
        }

        response = requests.post(token_url, data=params)
        tokens = response.json()

        if 'access_token' in tokens:
            access_token = tokens['access_token']
            refresh_token = tokens.get('refresh_token')
            id_token = tokens.get('id_token')

            print()

            return JsonResponse({'status': 'success', 'access_token': access_token})

    return JsonResponse({'status': 'error', 'message': 'Authorization failed'}, status=400)


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

    subscription = get_object_or_404(Subscription, staff_id=staff_id)
    subscription.end_date = get_formate_date(subscription.end_date)
    human_readable_plan = subscription.get_human_plan()

    user_data = {
        'page_title': f'Профиль {username}',
        'username': username,
        'email': user.email,
        'date_join': date_join,
        'date_last_login': date_last_login,
        'statistics': statistics,
        'tokens': {
            'surveys': total_tokens_for_surveys,
            'feedback': total_tokens_for_feedback,
            'total_tokens': total_tokens,
            'limit_tokens': get_format_number(50_000)
        },
        'subscription': {
            'plan_name': human_readable_plan,
            'plan_end_date': subscription.end_date
        }
    }

    return render(request, 'profile.html', user_data)


@login_required
def admin_stats(request):
    staff_id = get_staff_id(request)
    user = get_object_or_404(AuthUser, id_staff=staff_id)

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

            # blocked_users = BlockedUsers.objects.values_list('id_staff', 'ip_address')

            # blocked_users_set = set(blocked_users)

            # for user_record in user_activities:
            #     if user_record['id_staff'] is not None:
            #         user_record['id_staff'] = AuthUser.objects.get(id_staff=user_record['id_staff']).id_staff
            #
            #         user_record['is_blocked'] = (
            #             (user_record['id_staff'], None) in blocked_users_set or
            #             (None, user_record['ip_address']) in blocked_users_set
            #         )
            #
            #         print(f"Checking: {(user_record['id_staff'], user_record['ip_address'])} in {blocked_users_set}")
            #         print(f"Is blocked: {user_record['is_blocked']}")
            #
            #         user_record['username'] = AuthUser.objects.get(id_staff=staff_id)
            #     else:
            #         user_record['is_blocked'] = False

            # print(user_activities)
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

            # usernames = AuthUser.objects.values_list('username', flat=True)

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
        terminal_key = data['terminalKey']
        amount = data['amount']
        description = data['description']
        # order_id = data['orderId']
        email = data['email']
        phone = data['phone']
        receipt = data['receipt']

        print(phone, email)
        print("amount", amount)

        plan_prices = {
            'Начальный': 0,
            'Стандартный': 220,
            'Премиум': 590,
            'Пакет': 480
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

        created_token = PaymentManager().generate_token_for_new_payment(data_token)

        request_body = {
            "TerminalKey": "1731153311116DEMO",
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
                billing_cycle='monthly' if plan_prices.get(description) else 'yearly',
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

                    formatted_amount = f"{payment.amount / 100:,.2f}".replace(',', ' ').replace('.', ',') + " руб"

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

                    payment_details_text = "\n".join(
                        [f"<b>{detail['label']}:</b> {detail['value']}" for detail in payment_details])

                    message = (
                        f"{CONFIRM_SYMBOL} Успешный платеж\n\n"
                        f"<b>Статус платежа:</b> {payment_data['payment_status']}\n"
                        f"<b>Дата:</b> {get_formate_date(datetime.now())}\n\n"
                        f"<b>План:</b> {payment_data['plan_name']}\n\n"
                        f"<b>Детали платежа:</b>\n"
                        f"{payment_details_text}\n"
                        f"<b>Пользователь:</b> {payment_data['username']}"
                    )

                    try:
                        auth_user = AuthUser.objects.get(id_staff=get_staff_id(request))
                        additional_auth_user = AuthAdditionalUser.objects.get(user=auth_user)

                        telegram_message_manager = ManageTelegramMessages()
                        telegram_message_manager.send_message(additional_auth_user.id_telegram, message)

                    except Exception as fail:
                        tracer_l.tracer_charge(
                            'WARNING', f"{get_username(request)}",
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
        message = f"Никому не говорите код: {code}"
        self.send_message(telegram_user_id, message)

    def send_message_about_start(self):
        bot_token = TELEGRAM_BOT_TOKEN
        message = f"SERVER APP will be RELOADED {CONFIRM_SYMBOL}"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message
        }

        requests.post(url, json=payload)


def hash_data(data):
    data_string = json.dumps(data, sort_keys=True).encode()
    return hashlib.sha256(data_string).hexdigest()


user_verify_code = {}


@csrf_exempt
def confirm_user(request):
    if request.method == 'POST':
        body = json.loads(request.body)
        data = body.get('data')
        data_hash = body.get('data_hash')

        if hash_data(data) != data_hash:
            return JsonResponse({'status': 'error', 'message': 'Data integrity check failed'}, status=402)

        telegram_user_id = data.get('telegram_user_id')
        phone_number = data.get('phone_number')
        username = data.get('username')
        first_name = data.get('first_name')
        last_name = data.get('last_name')

        additional_auth = AuthAdditionalUser.objects.filter(id_telegram=telegram_user_id).first()

        if additional_auth:
            pass
        else:
            new_auth_telegram = AuthAdditionalUser.objects.create(
                id_telegram=int(telegram_user_id)
            )
            new_auth_telegram.save()

        user, created = AuthUser.objects.update_or_create(
            username=username,
            defaults={
                'confirmed_user': True,
                'first_name': first_name,
                'last_name': last_name,
                'phone': phone_number
            }
        )

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
        request.session['user_id'] = user.id

        return JsonResponse({'status': 'success', 'user_id': user.id})

    return JsonResponse({'status': 'error'}, status=400)


@csrf_exempt
def phone_number_view(request):
    if request.method == 'POST':
        form = PhoneNumberForm(request.POST)
        print(form.is_valid())

        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            print(phone_number)

            user = AuthUser.objects.filter(phone=phone_number).first()

            if user and (user.confirmed_user is True):
                code = random.randint(1000, 9999)
                user_verify_code[user.phone] = code

                telegram_message_manager = ManageTelegramMessages()
                telegram_message_manager.send_code_to_user(user.id, code)

                request.session['phone_number'] = phone_number
                return JsonResponse({'status': 'success', 'message': 'Код отправлен'})
            else:
                if not user:
                    new_user = AuthUser.objects.create(
                        username=generate_payment_id(),
                        phone=phone_number
                    )
                    new_user.save()
                    referral_code = generate_referral_code(new_user.id)
                else:
                    referral_code = generate_referral_code(user.id)

                referral_link = f"https://t.me/LetychkaRobot?start={referral_code}"

                return JsonResponse({
                    'status': 'success',
                    'message': 'Пользователь создан',
                    'referral_link': referral_link,
                    'referral_code': referral_code
                })

    else:
        form = PhoneNumberForm()

    return render(request, 'phone_number_form.html', {'form': form, 'code_form': False})


def generate_referral_code(user_id):
    # Генерация уникального реферального кода
    return f"LE{user_id}{random.randint(100000, 999999)}"


@csrf_exempt
def verify_code_view(request):
    if request.method == 'POST':
        verification_code = request.POST.get('verification_code')
        phone_number = request.session.get('phone_number')

        user = get_object_or_404(AuthUser, phone=phone_number)

        print(request.user.is_authenticated)
        if request.user.is_authenticated:
            print(f"Пользователь {request.user.username} успешно залогинен.")

        if user:
            if user_verify_code.get(user.phone) == int(verification_code):
                login(request, user)
                request.session['user_id'] = user.id
                print(request.session.get('user_id'))

                return redirect('create')
                # return JsonResponse({'status': 'success', 'redirect_url': '/create'})

            else:
                return JsonResponse({'status': 'error', 'message': 'Неверный код'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Пользователь не найден'})

    return JsonResponse({'status': 'error', 'message': 'Неверный запрос'})


class TelegramAuthView(View):
    def get(self, request):
        auth_data = request.GET

        try:
            auth_date = auth_data.get('auth_date', '')
            first_name = auth_data['first_name']
            last_name = auth_data.get('last_name', '')
            telegram_id = int(auth_data['id'])
            username = auth_data.get('username', None)
            hash_received = auth_data['hash']

            tracer_l.tracer_charge(
                'ERROR', get_username(request),
                'error in tg auth',
                f"{type(telegram_id)} {telegram_id}")

            if int(time.time()) - int(auth_date) > 600:
                return JsonResponse({'status': 'error', 'message': 'Данные не актуальны'}, status=400)

            existing_user = AuthAdditionalUser.objects.filter(id_telegram=telegram_id).first()

            if existing_user:
                auth_user = existing_user.user
            else:
                auth_user = AuthUser.objects.create(
                    username=telegram_id if username is None else username,
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

            tracer_l.tracer_charge(
                'ADMIN', username, login_view.__name__, f"user has been login in")

            return redirect('create')
        except Exception as fail:
            tracer_l.tracer_charge('ERROR', f"{get_client_ip(request)}", 'error in tg auth', fail)
            return JsonResponse({'status': 'error', 'message': 'Internal server error'}, status=500)


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
