from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .utils import *
from .models import *
from .forms import *
from askify_app.settings import DEBUG
from .tracer import *

import openai

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
    return redirect('history')


@csrf_exempt
@login_required
def generate_survey(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text_from_user = data.get('text')

            base_dir = os.path.dirname(os.path.abspath(__file__))
            forbidden_words_file_path = os.path.join(base_dir, '../askify_app/forbidden_words.txt')

            forbidden_words_file = open(forbidden_words_file_path)
            forbidden_words = forbidden_words_file.readlines()

            if any(word in text_from_user for word in forbidden_words):
                return JsonResponse({'error': 'К сожалению, не удалось выполнить запрос'}, status=400)

            if DEBUG:
                print("\nstart the generated...")
            tracer_l.tracer_charge(
                'INFO', request.user.username, generate_survey.__name__, f"start the generated: {text_from_user}")

            generation_models_control = GenerationModelsControl()
            generated_text = generation_models_control.get_service_0001(text_from_user)

            tracer_l.tracer_charge(
                'INFO', request.user.username, generate_survey.__name__, f"user request: {generated_text}")

            if DEBUG:
                print("\n"*3)
                print("generated_text", generated_text)

            try:
                cleaned_generated_text = json.loads(generated_text)
                tracer_l.tracer_charge(
                    'INFO', request.user.username, generate_survey.__name__, f"success json.loads: {cleaned_generated_text}")
            except json.JSONDecodeError:
                tracer_l.tracer_charge(
                    'ERROR', request.user.username, generate_survey.__name__, "text is not valid JSON", "status: 400")
                return JsonResponse({'error': 'Generated text is not valid JSON'}, status=400)
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
