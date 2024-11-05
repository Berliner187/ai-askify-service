from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver

from .utils import *
from .models import *
from .forms import *
from askify_app.settings import DEBUG
from .tracer import *

import openai

from datetime import datetime
import time

import uuid
import random
import os


tracer_l = TracerManager(TRACER_FILE)


def index(request):
    return render(request, 'askify_service/index.html')


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
    survey_user_answers = UserAnswers.objects.get(survey_id=uuid.UUID(survey_id))
    survey_user_answers.delete()
    return redirect('history')


@csrf_exempt
@login_required
def generate_survey(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text_from_user = data.get('text')

            base_dir = os.path.dirname(os.path.abspath(__file__))
            forbidden_words_file_path = os.path.join(base_dir, '../askify_app', "forbidden_words.txt")

            forbidden_words_file = open(forbidden_words_file_path)
            forbidden_words = [word.strip().lower() for word in forbidden_words_file.read().splitlines()]
            text_from_user = text_from_user.lower()

            if any(word in text_from_user for word in forbidden_words):
                return JsonResponse({'error': 'К сожалению, не удалось выполнить запрос'}, status=400)

            if DEBUG:
                print("\nstart the generated...")
            tracer_l.tracer_charge(
                'INFO', request.user.username, generate_survey.__name__, f"start the generated: {text_from_user}")

            generation_models_control = GenerationModelsControl()
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if DEBUG is False:
                        generated_text = generation_models_control.get_service_0001(text_from_user)
                    else:
                        generated_text = """
                        {
                            "title": "Тест по архитектуре основной памяти",
                            "questions": [
                                {
                                    "question": "Какой тип памяти используется для временного хранения данных, которые обрабатываются процессором?",
                                    "options": ["ОЗУ", "ПЗУ", "Кэш-память", "Жесткий диск"],
                                    "correct_answer": "ОЗУ"
                                },
                                {
                                    "question": "Что такое кэш-память и для чего она используется?",
                                    "options": ["Для хранения программ", "Для хранения данных",
                                                "Для ускорения доступа к часто используемым данным",
                                                "Для хранения настроек системы"],
                                    "correct_answer": "Для ускорения доступа к часто используемым данным"
                                },
                                {
                                    "question": "Какой принцип используется при организации памяти для обеспечения быстрого доступа к данным?",
                                    "options": ["Последовательный доступ", "Прямой доступ", "Ассоциативный доступ",
                                                "Адресный доступ"],
                                    "correct_answer": "Ассоциативный доступ"
                                },
                                {
                                    "question": "Что такое страница памяти и для чего она используется?",
                                    "options": ["Для хранения программ", "Для хранения данных",
                                                "Для организации виртуальной памяти",
                                                "Для управления доступом к памяти"],
                                    "correct_answer": "Для организации виртуальной памяти"
                                },
                                {
                                    "question": "Какой алгоритм используется для замены страниц памяти при нехватке свободной памяти?",
                                    "options": ["LRU (Least Recently Used)", "FIFO (First-In-First-Out)",
                                                "OPT (Оптимальный)", "RANDOM"],
                                    "correct_answer": "LRU (Least Recently Used)"
                                }
                            ]
                        }
                        """
                    break
                except Exception as e:
                    if e.response.status_code == 429:
                        if attempt < max_retries - 1:
                            wait_time = 60
                            print(f"Слишком много запросов. Повтор через {wait_time} секунд.")
                            time.sleep(wait_time)
                            return JsonResponse({'error': f"Сервер перегружен. Пожалуйста, повторите попытку через {wait_time} секунд."}, status=429)
                        else:
                            return JsonResponse({'error': 'Сервер перегружен, попробуйте позже.'}, status=429)
                    else:
                        raise

            if DEBUG:
                print("\n"*3)
                print("generated_text", generated_text)

            try:
                cleaned_generated_text = json.loads(generated_text)
                tracer_l.tracer_charge(
                    'INFO', request.user.username, generate_survey.__name__, f"success json.loads: {cleaned_generated_text.get('title')}")
            except json.JSONDecodeError:
                tracer_l.tracer_charge(
                    'ERROR', request.user.username, generate_survey.__name__, "text is not valid JSON", "status: 400")
                return JsonResponse({'error': generated_text}, status=400)
            except Exception as fail:
                tracer_l.tracer_charge(
                    'CRITICAL', request.user.username, generate_survey.__name__, f"{fail}", "status: 400")
                return JsonResponse({'error': 'Generated text is not valid JSON'}, status=400)

            try:
                new_survey_id = uuid.uuid4()
                survey = Survey(
                    survey_id=new_survey_id,
                    title=cleaned_generated_text['title'],
                    id_staff=get_staff_id(request)
                )
                survey.save_questions(cleaned_generated_text['questions'])
                survey.save()

                # survey = Survey(
                #     survey_id=new_survey_id,
                #     title=cleaned_generated_text['title'],
                #     questions=json.dumps(cleaned_generated_text['questions']),
                #     id_staff=get_staff_id(request)
                # )
                # survey.save()
                tracer_l.tracer_charge(
                    'INFO', request.user.username, generate_survey.__name__, "success save to DB")

                return JsonResponse({'survey': cleaned_generated_text, 'survey_id': new_survey_id}, status=200)
            except Exception as fail:
                tracer_l.tracer_charge(
                    'ERROR', request.user.username, generate_survey.__name__, "error in save to DB", f"{fail}")

            print(cleaned_generated_text)

        except json.JSONDecodeError as json_decode:
            tracer_l.tracer_charge(
                'ERROR', request.user.username, generate_survey.__name__,
                "Invalid JSON in request body", f"{json_decode}",
                f"status: 400")
            return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
        except Exception as e:
            tracer_l.tracer_charge(
                'CRITICAL', request.user.username, generate_survey.__name__,
                "FATAL Exception", f"{e}",
                f"status: 400")
            return JsonResponse({'error': str(e)}, status=500)

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
    # return render(request, 'askify_service/text_input.html', {'surveys_data': response_data_all})
    # return JsonResponse(response_data_all, status=200)


@login_required
def take_survey(request, survey_id):
    if DEBUG:
        print("take_survey: work")

    survey_id = uuid.UUID(survey_id)
    survey = get_object_or_404(Survey, survey_id=survey_id)
    questions = json.loads(survey.questions)
    print(questions, survey)

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
                'username': request.user.username if request.user.is_authenticated else None
            }
            return render(
                request, 'survey.html', context)

        survey_obj = UserAnswers.objects.filter(survey_id=survey_id)

        if survey_obj.exists():
            survey_obj.delete()

        correct_count = 0
        for index_q, question in enumerate(questions):
            selected_answer = user_answers[index_q]
            is_correct = selected_answer == question['correct_answer']
            if is_correct:
                correct_count = 1

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

            # UserAnswers.objects.get_or_create(
            #     survey_id=survey_id,
            #     selected_answer=selected_answer,
            #     defaults={
            #         'scored_points': correct_count if is_correct else 0,
            #         'total_points': len(questions),
            #         'user_answers': user_answers_dict
            #     },
            #     id_staff=get_staff_id(request)
            # )

            if DEBUG:
                print(f"\n\nВопрос: {question['question']}\nПравильный ответ: {question['correct_answer']}\nОтвет пользователя: {selected_answer}")

        json_response = {'score': correct_count, 'total': len(user_answers), 'survey_id': survey_id}

        return render(request, 'result.html', json_response)

    return render(request, 'survey.html', {'survey': survey, 'questions': questions, 'username': request.user.username if request.user.is_authenticated else None})


@login_required
def result_view(request, survey_id):
    print("result_view", survey_id)

    survey = Survey.objects.get(survey_id=survey_id)
    user_answers = UserAnswers.objects.filter(survey_id=survey_id)
    score = sum(answer.scored_points for answer in user_answers)

    questions = survey.get_questions()
    selected_answers = {answer.selected_answer for answer in user_answers}
    selected_answers_list = list(user_answers.values_list('selected_answer', flat=True))

    json_response = {
        'title': survey.title,
        'score': score,
        'total': len(user_answers),
        'survey_id': survey_id,
        'questions': questions,
        'selected_answers': selected_answers,
        'selected_answers_list': selected_answers_list,
        'username': request.user.username if request.user.is_authenticated else None
    }
    print("result_view", score, len(user_answers))

    return render(request, 'result.html', json_response)


def download_survey_pdf(request, survey_id):
    survey = get_object_or_404(Survey, survey_id=uuid.UUID(survey_id))
    return survey.generate_pdf()


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('/create')
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})


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
            return redirect('/create')
        else:
            print('Неверное имя пользователя или пароль')
            messages.error(request, 'Неверное имя пользователя или пароль')

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('login')


def profile_view(request, username):
    staff_id = get_staff_id(request)
    user = AuthUser.objects.get(id_staff=staff_id)

    statistics = UserAnswers.calculate_user_statistics(staff_id)

    date_join = get_formate_date(user.date_joined)
    date_last_login = get_formate_date(user.last_login)

    try:
        subscription = Subscription.objects.get(staff_id=staff_id)
        subscription.end_date = get_formate_date(subscription.end_date)
    except Subscription.DoesNotExist:
        subscription = 'Free 0₽'

    user_data = {
        'username': username,
        'email': user.email,
        'date_join': date_join,
        'date_last_login': date_last_login,
        'statistics': statistics,
        'subscription': subscription
    }

    return render(request, 'profile.html', user_data)


@login_required
def admin_stats(request):
    staff_id = get_staff_id(request)
    user = AuthUser.objects.get(id_staff=staff_id)

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
        else:
            selected_users = total_surveys = subscriptions = total_answers = 0

        context = {
            'selected_users': selected_users,
            'total_users': all_users,
            'total_surveys': total_surveys,
            'total_answers': total_answers,
            'username': request.user.username,
            'subscriptions': subscriptions
        }

        return render(request, 'admin.html', context)
    else:
        redirect(f'profile/{request.user.username}')


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


def subscription_list(request):
    subscriptions = AvailableSubscription.objects.all()
    staff_id = get_staff_id(request)

    if request.method == 'POST':
        plan_name = request.POST.get('plan_name')
        print(plan_name)
        selected_subscription = AvailableSubscription.objects.get(plan_name=plan_name)
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
            subscription = Subscription.objects.get(staff_id=staff_id)
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
    payment = Payment.objects.get(payment_id=payment_id)
    return render(request, 'payment.html', {'payment': payment})
