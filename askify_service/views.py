from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
import openai
import json

from .utils import *
from askify_app.settings import DEBUG


manage_confident_fields = ManageConfidentFields("config.json")


client = openai.OpenAI(
    api_key=manage_confident_fields.get_confident_key("api_openai"),
    base_url="https://glhf.chat/api/openai/v1",
)


def index(request):
    return render(request, 'askify_service/index.html')


@csrf_exempt
def page_create_test(request):
    return render(request, 'askify_service/text_input.html')


@csrf_exempt
def generate_survey(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text_from_user = data.get('text')

            if DEBUG:
                print("\nstart the generated...")

            completion = client.chat.completions.create(
                model=f"hf:{manage_confident_fields.get_confident_key('llm_model_name')}",
                messages=[
                    {
                        "role": "system",
                        "content": f"{manage_confident_fields.get_confident_key('system_prompt')}"
                    },
                    {
                        "role": "user",
                        "content": f"На основе следующего текста: {text_from_user}{manage_confident_fields.get_confident_key('user_prompt')}"
                    }
                ]
            )

            generated_text = completion.choices[0].message.content

            if DEBUG:
                print("\n"*3)
                print("generated_text", generated_text)

            return JsonResponse({'survey': generated_text}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            print(e)
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=400)
