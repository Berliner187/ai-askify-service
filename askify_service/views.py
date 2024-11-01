from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404

from .utils import *
from .models import *
from askify_app.settings import DEBUG

import openai

import uuid
import random


def index(request):
    return render(request, 'askify_service/index.html')


@csrf_exempt
def page_create_survey(request):
    surveys_data = get_all_surveys()
    return render(request, 'askify_service/text_input.html')


def page_history_surveys(request):
    surveys_data = get_all_surveys()
    return render(request, 'askify_service/history.html', {'surveys_data': surveys_data})


def drop_survey(request, survey_id):
    survey_obj = Survey.objects.get(survey_id=uuid.UUID(survey_id))
    survey_obj.delete()
    return redirect('history')


@csrf_exempt
def generate_survey(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text_from_user = data.get('text')

            forbidden_words_file = open('./askify_app/forbidden_words.txt')
            forbidden_words = forbidden_words_file.read()
            if any(word in text_from_user for word in forbidden_words):
                return JsonResponse({'error': 'К сожалению, не удалось выполнить запрос'}, status=400)

            if DEBUG:
                print("\nstart the generated...")

            generation_models_control = GenerationModelsControl()
            generated_text = generation_models_control.get_service_0001(text_from_user)

            if DEBUG:
                print("\n"*3)
                print("generated_text", generated_text)

            try:
                cleaned_generated_text = json.loads(generated_text)
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Generated text is not valid JSON'}, status=400)

            new_survey_id = uuid.uuid4()
            survey = Survey(
                survey_id=new_survey_id,
                title=cleaned_generated_text['title'],
                questions=json.dumps(cleaned_generated_text['questions'])
            )
            survey.save()
            print(cleaned_generated_text)

            return JsonResponse({'survey': cleaned_generated_text, 'new_survey_id': new_survey_id}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
        except Exception as e:
            print(e)
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=400)


def get_all_surveys():
    surveys = Survey.objects.all()

    response_data_all = {}

    for survey in surveys:
        # response_data_all[f'survey_data_{count}'] = {'survey_id': f"{survey.survey_id}", 'title': survey.title}
        response_data_all[str(survey.survey_id)] = survey.title

    print(response_data_all)
    return response_data_all
    # return render(request, 'askify_service/text_input.html', {'surveys_data': response_data_all})
    # return JsonResponse(response_data_all, status=200)


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
            return render(request, 'survey.html',
                          {'survey': survey, 'questions': questions, 'error': 'Пожалуйста, ответьте на все вопросы.'})

        survey_obj = UserAnswers.objects.filter(survey_id=survey_id)

        if survey_obj.exists():
            survey_obj.delete()

        correct_count = 0
        for index_q, question in enumerate(questions):
            selected_answer = user_answers[index_q]
            is_correct = selected_answer == question['correct_answer']
            if is_correct:
                correct_count = 1

            UserAnswers.objects.get_or_create(
                survey_id=survey_id,
                selected_answer=selected_answer,
                defaults={
                    'scored_points': correct_count if is_correct else 0,
                    'total_points': len(questions),
                    'user_answers': user_answers_dict
                }
            )

            if DEBUG:
                print(f"\n\nВопрос: {question['question']}\nПравильный ответ: {question['correct_answer']}\nОтвет пользователя: {selected_answer}")

        json_response = {'score': correct_count, 'total': len(user_answers), 'survey_id': survey_id}

        return render(request, 'result.html', json_response)

    return render(request, 'survey.html', {'survey': survey, 'questions': questions})


def result_view(request, survey_id):
    print("result_view", survey_id)

    survey = Survey.objects.get(survey_id=survey_id)
    user_answers = UserAnswers.objects.filter(survey_id=survey_id)
    score = sum(answer.scored_points for answer in user_answers)

    json_response = {'title': survey.title, 'score': score, 'total': len(user_answers), 'survey_id': survey_id}
    print("result_view", score, len(user_answers))

    return render(request, 'result.html', json_response)
