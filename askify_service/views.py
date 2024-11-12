from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.views import View
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.decorators import method_decorator

from .utils import *
from .models import *
from .forms import *
from askify_app.settings import DEBUG, BASE_DIR
from askify_app.middleware import check_blocked
from .tracer import *

import openai
import markdown
import requests
import aiofiles
import PyPDF2

from datetime import datetime
import time
import hashlib
import uuid
import random
import os
import re


tracer_l = TracerManager(TRACER_FILE)


def index(request):
    context = {
        'username': request.user.username if request.user.is_authenticated else 0
    }
    return render(request, 'askify_service/index.html', context)


@csrf_exempt
@login_required
def page_create_survey(request):
    tracer_l.tracer_charge(
        'INFO', request.user.username, page_history_surveys.__name__, "load page")
    context = {
        'username': request.user.username if request.user.is_authenticated else None
    }
    return render(request, 'askify_service/text_input.html', context)


@login_required
def page_history_surveys(request):
    surveys_data = get_all_surveys(request)
    context = {
        'surveys_data': surveys_data,
        'username': request.user.username if request.user.is_authenticated else None
    }
    tracer_l.tracer_charge(
        'INFO', request.user.username, page_history_surveys.__name__, "load page")
    return render(request, 'askify_service/history.html', context)


@login_required
def drop_survey(request, survey_id):
    survey_obj = Survey.objects.get(survey_id=uuid.UUID(survey_id))
    survey_obj.delete()
    tracer_l.tracer_charge(
        'INFO', request.user.username, drop_survey.__name__, "Delete Survey")
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


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
@method_decorator(check_blocked, name='dispatch')
class ManageSurveysView(View):
    def post(self, request):
        if request.method == 'POST':
            try:
                text_from_user = json.loads(request.body)
                text_from_user = text_from_user
                print(text_from_user)

                time.sleep(900)

                try:
                    print(f"\n\nGEN STAAAART")
                    manage_generate_surveys_text = ManageGenerationSurveys(request, text_from_user)
                    generated_text, tokens_used = manage_generate_surveys_text.generate_survey_for_user()
                    print(generated_text, tokens_used)

                    print(f"\n\nGEN TEST: {generated_text}")

                    cleaned_generated_text = generated_text
                    tracer_l.tracer_charge(
                        'INFO', request.user.username, ManageSurveysView.post.__name__, f"success json.loads: {cleaned_generated_text.get('title')}")
                except TypeError as error:
                    tracer_l.tracer_charge(
                        'ERROR', request.user.username, ManageSurveysView.post.__name__,
                        "text is not valid JSON", str(error), "status: 400")
                    return JsonResponse({'error': 'К сожалению, не удалось выполнить запрос'}, status=400)
                except json.JSONDecodeError as json_error:
                    tracer_l.tracer_charge(
                        'ERROR', request.user.username, ManageSurveysView.post.__name__, "text is not valid JSON", str(json_error), "status: 400")
                    return JsonResponse({'error': generated_text}, status=400)
                except Exception as fail:
                    tracer_l.tracer_charge(
                        'CRITICAL', request.user.username, ManageSurveysView.post.__name__, f"{fail}", "status: 400")
                    return JsonResponse({'error': 'Generated text is not valid JSON'}, status=400)

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
                        'ERROR', request.user.username, ManageSurveysView.post.__name__, "error in save to DB", f"{fail}")

                if DEBUG:
                    print(cleaned_generated_text)

            except json.JSONDecodeError as json_decode:
                tracer_l.tracer_charge(
                    'ERROR', request.user.username, ManageSurveysView.generate_survey.__name__,
                    "Invalid JSON in request body", f"{json_decode}",
                    f"status: 400")
                return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
            except Exception as e:
                tracer_l.tracer_charge(
                    'CRITICAL', request.user.username, ManageSurveysView.generate_survey.__name__,
                    "FATAL Exception", f"{e}",
                    f"status: 500")
                return JsonResponse({'error': str(e)}, status=500)

        tracer_l.tracer_charge(
            'CRITICAL', request.user.username, ManageSurveysView.generate_survey.__name__,
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
        response_data_all[str(survey.survey_id)] = survey.title

    print(response_data_all)
    return response_data_all


class FileUploadView(View):
    def post(self, request):
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)

        uploaded_file = request.FILES['file']
        if uploaded_file.size > 5 * 1024 * 1024:
            return JsonResponse({'error': 'File too large. Max size is 5 MB.'}, status=400)

        data = self.read_file_data(uploaded_file)

        # Если текст предоставлен, передаем его в метод генерации
        # manage_generate_surveys_text = ManageGenerationSurveys(request, data)
        # generated_text, tokens_used = manage_generate_surveys_text.generate_survey_for_user()
        print("ТЕСТ ГЕНЕРИРУЕТСЯ")
        try:
            manage_generate_surveys_text = ManageGenerationSurveys(request, data)
            generated_text, tokens_used = manage_generate_surveys_text.generate_survey_for_user()
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
        data = []

        if uploaded_file.content_type == 'application/pdf':
            reader = PyPDF2.PdfReader(uploaded_file)

            for page in reader.pages:
                text = page.extract_text()
                if text:
                    data.append(text.strip())
        else:
            data.append("Файл не является PDF")

        print(data)
        return data


@login_required
def take_survey(request, survey_id):
    if DEBUG:
        print("take_survey: work")

    request.user.log_activity(request)

    survey_id = uuid.UUID(survey_id)
    survey = get_object_or_404(Survey, survey_id=survey_id)
    questions = json.loads(survey.questions)

    # random.shuffle(questions)

    if request.method == 'POST':
        if DEBUG:
            print("Метод POST")
            print("Данные POST:", request.POST)

        user_answers = [request.POST.get(f'answers_{i + 1}') for i in range(len(questions))]

        question_ids = [f'question_{i + 1}' for i in range(len(user_answers))]
        user_answers_dict = {question_ids[i]: user_answers[i] for i in range(len(user_answers))}

        if DEBUG:
            print("Ответы пользователя:", user_answers)
        if None in user_answers:
            context = {
                'survey': survey, 'questions': questions, 'error': 'Пожалуйста, ответьте на все вопросы.',
                'username': get_username(request)
            }
            return render(
                request, 'survey.html', context)

        survey_obj = UserAnswers.objects.filter(survey_id=survey_id)

        if survey_obj.exists():
            survey_obj.delete()

        user_answers_list = []

        correct_count = 0
        total_count = 0
        for index_q, question in enumerate(questions):
            selected_answer = user_answers[index_q]
            is_correct = selected_answer == question['correct_answer']
            if is_correct:
                correct_count = 1
                total_count += 1

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

            if DEBUG:
                print(f"\n\nВопрос: {question['question']}\nПравильный ответ: {question['correct_answer']}\nОтвет пользователя: {selected_answer}")

        try:
            feedback_obj = FeedbackFromAI.objects.filter(survey_id=survey_id)
            if feedback_obj.exists():
                feedback_obj.delete()

            print(">>>>> ЗАГРУЗКА FEEDBACK <<<<<")
            generation_models_control = GenerationModelsControl()
            ai_feedback, tokens_used = generation_models_control.get_feedback_001(
                f"Список вопросов и моих ответов: {user_answers_list}.\n"
                f"Набрано балов: {total_count} из {len(user_answers)}"
            )

            FeedbackFromAI.objects.create(
                survey_id=survey_id,
                id_staff=get_staff_id(request),
                feedback_data=ai_feedback
            )

            _tokens_used = TokensUsed(
                id_staff=get_staff_id(request),
                tokens_feedback_used=tokens_used
            )
            _tokens_used.save()
        except Exception as fail:
            tracer_l.tracer_charge(
                'CRITICAL', request.user.username, take_survey.__name__,
                "Invalid FEEDBACK", f"{fail}")

        json_response = {'score': correct_count, 'total': user_answers, 'survey_id': survey_id}
        return render(request, 'result.html', json_response)

    context = {
        'survey': survey, 'questions': questions, 'survey_title': survey.title,
        'username': request.user.username if request.user.is_authenticated else None
    }
    return render(request, 'survey.html', context)


@login_required
def result_view(request, survey_id):
    print("result_view", survey_id)

    survey = Survey.objects.get(survey_id=survey_id)
    user_answers = UserAnswers.objects.filter(survey_id=survey_id)
    score = sum(answer.scored_points for answer in user_answers)

    questions = survey.get_questions()
    selected_answers = {answer.selected_answer for answer in user_answers}
    selected_answers_list = list(user_answers.values_list('selected_answer', flat=True))

    try:
        feedback_obj = FeedbackFromAI.objects.get(survey_id=survey_id)
        feedback_text = markdown.markdown(feedback_obj.feedback_data)
    except Exception as fail:
        feedback_text = None

    json_response = {
        'title': survey.title,
        'score': score,
        'total': len(user_answers),
        'survey_id': survey_id,
        'questions': questions,
        'selected_answers': selected_answers,
        'selected_answers_list': selected_answers_list,
        'username': request.user.username if request.user.is_authenticated else None,
        'feedback_text': feedback_text
    }
    print("result_view", score, len(user_answers))

    return render(request, 'result.html', json_response)


def download_survey_pdf(request, survey_id):
    request.user.log_activity(request)
    survey = get_object_or_404(Survey, survey_id=uuid.UUID(survey_id))
    return survey.generate_pdf()


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()

            tracer_l.tracer_charge(
                'ADMIN', user.username, register.__name__, f"NEW USER")

            plan_name, end_date, status, billing_cycle, discount = init_subscription()
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
            request.user.log_activity(request)

            tracer_l.tracer_charge(
                'ADMIN', request.user.username, register.__name__, f"user has been login in")

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
                request.user.log_activity(request)

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
            'client_id': '7b09de637b09de637b09de6325782ab3af77b097b09de631c385ca246d43f689073405f',  # Замените на ваш client_id
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


def profile_view(request, username):
    staff_id = get_staff_id(request)
    user = get_object_or_404(AuthUser, id_staff=staff_id)

    statistics = UserAnswers.calculate_user_statistics(staff_id)

    date_join = get_formate_date(user.date_joined)
    date_last_login = get_formate_date(user.last_login)

    tokens_usage = TokensUsed.get_tokens_usage(staff_id)

    total_tokens_for_surveys = f"{tokens_usage['tokens_survey_used']:,}"
    total_tokens_for_feedback = f"{tokens_usage['tokens_feedback_used']:,}"

    try:
        subscription = get_object_or_404(Subscription, staff_id=staff_id)
        subscription.end_date = get_formate_date(subscription.end_date)
    except Subscription.DoesNotExist:
        subscription = 'Free 0₽'

    user_data = {
        'username': username,
        'email': user.email,
        'date_join': date_join,
        'date_last_login': date_last_login,
        'statistics': statistics,
        'tokens': {'surveys': total_tokens_for_surveys, 'feedback': total_tokens_for_feedback},
        'subscription': subscription
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

        if start_date and end_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d')
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d') + timezone.timedelta(days=1)

            selected_users = AuthUser.objects.filter(date_joined__range=(start_date, end_date)).count()
            total_surveys = Survey.objects.filter(updated_at__range=(start_date, end_date)).count()
            total_answers = UserAnswers.objects.filter(created_at__range=(start_date, end_date)).count()
            subscriptions = Subscription.objects.filter(start_date__range=(start_date, end_date)).count()

            user_activities = UserActivity.objects.filter(created_at__range=(start_date, end_date)).values('id_staff', 'ip_address', 'created_at')
            user_activities_count = UserActivity.objects.filter(created_at__range=(start_date, end_date)).count()

            blocked_users = BlockedUsers.objects.values_list('id_staff', 'ip_address')

            blocked_users_set = set(blocked_users)

            for user_record in user_activities:
                if user_record['id_staff'] is not None:
                    user_record['id_staff'] = AuthUser.objects.get(id_staff=user_record['id_staff']).id_staff

                    user_record['is_blocked'] = (
                        (user_record['id_staff'], None) in blocked_users_set or
                        (None, user_record['ip_address']) in blocked_users_set
                    )

                    print(f"Checking: {(user_record['id_staff'], user_record['ip_address'])} in {blocked_users_set}")
                    print(f"Is blocked: {user_record['is_blocked']}")

                    user_record['username'] = AuthUser.objects.get(id_staff=staff_id)
                else:
                    user_record['is_blocked'] = False

            print(user_activities)
        else:
            selected_users = total_surveys = subscriptions = total_answers = 0
            user_activities = UserActivity.objects.none()
            user_activities_count = 0

        usernames = AuthUser.objects.values_list('username', flat=True)

        context = {
            'selected_users': selected_users,
            'total_users': all_users,
            'total_surveys': total_surveys,
            'total_answers': total_answers,
            'usernames': usernames,
            'username': request.user.username,
            'subscriptions': subscriptions,
            'user_activities': user_activities,
            'count_activities': user_activities_count
        }

        return render(request, 'admin.html', context)
    else:
        return redirect(f'profile/{request.user.username}')


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


def create_subscription(request):
    if request.method == 'POST':
        staff_id = get_staff_id(request)
        plan_name = request.POST.get('plan_name')
        end_date = datetime.now() + timedelta(days=30)
        status = 'active'
        billing_cycle = request.POST.get('billing_cycle')
        discount = request.POST.get('discount', 0.00)

        # free_subscription = AvailableSubscription.objects.create(
        #     plan_name='Free Plan', amount=0.0, plan_type='free')
        # standard_subscription = AvailableSubscription.objects.create(
        #     plan_name='Standard Plan', amount=190, plan_type='standard')
        # plus_subscription = AvailableSubscription.objects.create(
        #     plan_name='Plus Plan', amount=590, plan_type='plus')
        #
        # print(f'Free Subscription Expires on: {free_subscription.expiration_date}')
        # print(f'Standard Subscription Expires on: {standard_subscription.expiration_date}')
        # print(f'Plus Subscription Expires on: {plus_subscription.expiration_date}')

        subscription = Subscription(
            staff_id=staff_id,
            plan_name=plan_name,
            end_date=end_date,
            status=status,
            billing_cycle=billing_cycle,
            discount=discount
        )
        subscription.save()
        return redirect('success_page')

    return render(request, 'subscription.html')


@login_required
def subscription_list(request):
    subscriptions = AvailableSubscription.objects.all()
    staff_id = get_staff_id(request)

    if request.method == 'POST':
        plan_name = request.POST.get('plan_name')
        print(plan_name)
        selected_subscription = get_object_or_404(AvailableSubscription, plan_name=plan_name)
        end_date = datetime.now() + timedelta(days=30)
        status = 'active'
        billing_cycle = 'monthly'
        discount = 0.00
        amount = selected_subscription.amount

        # free_subscription = AvailableSubscription.objects.create(
        #     plan_name='free', amount=0.00, plan_type='free')
        # standard_subscription = AvailableSubscription.objects.create(
        #     plan_name='standard', amount=190.00, plan_type='standard')
        # plus_subscription = AvailableSubscription.objects.create(
        #     plan_name='plus', amount=590.00, plan_type='plus')
        #
        # print(f'Free Subscription Expires on: {free_subscription.expiration_date}')
        # print(f'Standard Subscription Expires on: {standard_subscription.expiration_date}')
        # print(f'Plus Subscription Expires on: {plus_subscription.expiration_date}')

        try:
            subscription = get_object_or_404(Subscription, staff_id=staff_id)
            subscription.plan_name = plan_name
            subscription.end_date = end_date
            subscription.status = status
            subscription.billing_cycle = billing_cycle
            subscription.discount = discount
            subscription.save()
            print("Обновлена")
        except Subscription.DoesNotExist:
            subscription = Subscription.objects.create(
                staff_id=staff_id,
                plan_name=plan_name,
                end_date=end_date,
                status=status,
                billing_cycle=billing_cycle,
                discount=discount
            )
            print("Новая подписка")

        payment = Payment.objects.create(
            subscription=subscription,
            payment_id=generate_payment_id(),
            amount=amount,
            status='completed' if amount > 0 else 'free'
        )

        return redirect('success_payment', payment_id=payment.payment_id)

    return render(request, 'subscription.html', {'subscriptions': subscriptions})


def success_payment(request, payment_id):
    print("GET запрос на success_payment с payment_id:", payment_id)
    payment = get_object_or_404(Payment, payment_id=payment_id)
    return render(request, 'payment.html', {'payment': payment})


def payment_success(request):
    if request.method == 'POST':
        print('прилет payment_success')
        data = json.loads(request.body)
        payment_id = data.get('payment_id')
        amount = data.get('amount')
        status = data.get('status')

        if not payment_id or not amount or not status:
            return HttpResponseBadRequest("Missing required fields")

        staff_id = get_staff_id(request)
        subscription = get_object_or_404(Subscription, staff_id=staff_id)

        payment = Payment.objects.create(
            subscription=subscription,
            payment_id=payment_id,
            amount=amount,
            status=status
        )

        return JsonResponse({'status': 'success', 'payment_id': payment.payment_id})

    return render(request, 'payments/payment.html')


def get_ip(request):
    ip = get_client_ip(request)
    print(os.path.join(BASE_DIR, 'documents'))
    return JsonResponse({'ip': ip})


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


def confirm_payment(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        order_id = data.get('orderId')
        amount = data.get('amount')
        email = data.get('email')

        # Здесь добавь логику для обработки платежа
        # Например, сохранить информацию в базе данных

        return JsonResponse({'status': 'success', 'message': 'Payment confirmed'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
