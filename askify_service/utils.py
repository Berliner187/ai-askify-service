import json
import datetime
import random
import string
from datetime import timedelta
import locale
import os
import re
import time
import hashlib

from django.http import JsonResponse

import openai
import requests


from .tracer import *


tracer_l = TracerManager(TRACER_FILE)


TERMINAL_KEY = '1731153311116DEMO'
TERMINAL_PASSWORD = '4Z6GdFlLmPZwRbT4'


class ManageConfidentFields:
    def __init__(self, filename):
        self.filename = filename

    def __read_confident_file(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))

        config_path = os.path.join(base_dir, '../askify_app', self.filename)

        with open(config_path) as config_file:
            return json.load(config_file)

    def get_confident_key(self, keyname):
        _config = self.__read_confident_file()
        return _config[keyname]


class ManageGenerationSurveys:
    def __init__(self, request, data):
        self.request = request
        self.data = data
        self.text_from_user = self.get_text_from_request()
        self.forbidden_words = self.load_forbidden_words()
        self.generation_models_control = GenerationModelsControl()
        self.max_retries = 3

    def get_text_from_request(self):
        print(self.data)
        return self.data

    def load_forbidden_words(self):
        print('ошибка')
        base_dir = os.path.dirname(os.path.abspath(__file__))
        forbidden_words_file_path = os.path.join(base_dir, '../askify_app', "forbidden_words.txt")
        with open(forbidden_words_file_path) as forbidden_words_file:
            return [word.strip().lower() for word in forbidden_words_file.read().splitlines()]

    def check_forbidden_words(self):
        if any(word in self.text_from_user for word in self.forbidden_words):
            self.log_warning("Detected forbidden words")
            print("Detected forbidden words")
            return True
        return False

    def log_warning(self, message):
        print(message)
        tracer_l.tracer_charge(
            'WARNING', self.request.user.username, self.generate_survey_for_user.__name__,
            message, "status: 400", self.text_from_user
        )

    def generate_survey_for_user(self):
        print('на месте')
        if self.check_forbidden_words():
            return 420

        self.log_info("start the generated: {}".format(self.text_from_user[:16]))
        print("start the generated: {}".format(self.text_from_user[:16]))

        for attempt in range(self.max_retries):
            try:
                generated_text, tokens_used = self.generation_models_control.get_generated_survey_0003(self.text_from_user)
                return self.process_generated_text(generated_text), tokens_used

            except Exception as fail:
                print(fail, attempt)
                response = self._handle_exception(fail, attempt)
                if response:
                    return response

    def log_info(self, message):
        tracer_l.tracer_charge(
            'INFO', self.request.user.username, self.generate_survey_for_user.__name__,
            message
        )

    def process_generated_text(self, generated_text):
        json_match = re.search(r'(\{.*\})', generated_text, re.DOTALL)

        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError as fail:
                self.log_error("json.JSONDecodeError", str(fail))
                return JsonResponse({'error': 'Ошибка декодирования JSON'}, status=479)
        else:
            self.log_warning("JSON not found")
            return JsonResponse({'error': f"{generated_text}"}, status=429)

    def log_error(self, error_type, message):
        print(error_type, message)
        tracer_l.tracer_charge(
            'ERROR', self.request.user.username, self.generate_survey_for_user.__name__,
            error_type, message
        )

    def _handle_exception(self, fail, attempt):
        if fail.response.status_code == 429:
            self.log_error("Code 429", str(fail))
            if attempt < self.max_retries - 1:
                wait_time = 60
                time.sleep(wait_time)
                return JsonResponse(
                    {'error': f"Сервер перегружен. Пожалуйста, повторите попытку через {wait_time} секунд."},
                    status=429
                )
            else:
                self.log_error(429, "AI: Server Overloaded")
                return JsonResponse({'error': 'Сервер перегружен, попробуйте позже.'}, status=429)
        else:
            self.log_error("Code XXX", f"unknown critical error: {fail}")
            raise


class AccessControlUser:
    @staticmethod
    def validate_text(text):
        """ Проверка допуска к генерации текста от пользователя """
        # if len(text) <
        pass

    # def check_subscription(self, id_staff):
    #     get_sub = Subscription.objects.filter(id_staff=id_staff)
    #     if get_sub:
    #         return get_sub


def get_format_number(number) -> str:
    return f"{number:,}".replace(',', ' ')


def get_datetime_now():
    return datetime.now()


def get_staff_id(request):
    user = request.user
    if user.is_authenticated:
        return user.id_staff
    return None


def get_username(request):
    return request.user.username if request.user.is_authenticated else None


def init_subscription():
    plan_name = 'free'
    end_date = datetime.now() + timedelta(days=7)
    status = 'active'
    billing_cycle = 'weakly'
    discount = 0.00
    return plan_name, end_date, status, billing_cycle, discount


def generate_payment_id(length=16):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def get_formate_date(date):
    locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')

    date_str = str(date)
    date_obj = datetime.fromisoformat(date_str[:-6])

    return date_obj.strftime("%-d %B, в %H:%M")


class GenerationModelsControl:
    def __init__(self):
        pass

    @staticmethod
    def __get_confidential_key(key_name):
        manage_confident_fields = ManageConfidentFields("config.json")
        return manage_confident_fields.get_confident_key(key_name)

    def get_generated_survey_0002(self, text_from_user):
        messages = [
            {
                "role": "system",
                "content": f"{self.__get_confidential_key('system_prompt')}"
            },
            {
                "role": "user",
                "content": f"{text_from_user}{self.__get_confidential_key('user_prompt')}"
            }
        ]

        url = "https://api.arliai.com/v1/chat/completions"
        payload = json.dumps({
            "model": "Meta-Llama-3.1-8B-Instruct",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2048,
            "stream": False
        })
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.__get_confidential_key("api_arliai")}'
        }
        response = requests.post(url, headers=headers, data=payload)
        return response.json()

    def get_generated_feedback_0003(self, text_from_user):
        client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.__get_confidential_key('openrouter')
        )

        completion = client.chat.completions.create(
            model="meta-llama/llama-3.2-90b-vision-instruct:free",
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{self.__get_confidential_key('pre_feedback_prompt')}"
                        },
                        {
                            "type": "text",
                            "text": f"{text_from_user}{self.__get_confidential_key('post_feedback_prompt')}"
                        }
                    ]
                }
            ]
        )

        return self.__generate_completion(completion)

    @staticmethod
    def __generate_completion(completion):
        generated_text = completion.choices[0].message.content
        cleaned_generated_text = generated_text.replace("json", "").replace("`", "")
        tokens_used = completion.usage.total_tokens
        print(cleaned_generated_text, tokens_used)
        return cleaned_generated_text, tokens_used

    def get_generated_survey_0001(self, text_from_user):
        client = openai.OpenAI(
            api_key=self.__get_confidential_key("api_openai"),
            base_url="https://glhf.chat/api/openai/v1",
        )

        messages = [
            {
                "role": "system",
                "content": f"{self.__get_confidential_key('system_prompt')}"
            },
            {
                "role": "user",
                "content": f"{text_from_user}{self.__get_confidential_key('user_prompt')}"
            }
        ]

        # return self.__generate_completion(client, messages)

    def get_generated_survey_0003(self, text_from_user):
        client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.__get_confidential_key('openrouter')
        )

        completion = client.chat.completions.create(
            model="meta-llama/llama-3.2-90b-vision-instruct:free",
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{self.__get_confidential_key('system_prompt')}"
                        },
                        {
                            "type": "text",
                            "text": f"{text_from_user} {self.__get_confidential_key('user_prompt')}"
                        }
                    ]
                }
            ]
        )

        return self.__generate_completion(completion)

    def get_feedback_001(self, text_from_user):
        feedback_text, tokens_used = self.get_generated_feedback_0003(text_from_user)
        print("Feedback's response:", feedback_text)
        return feedback_text, tokens_used


class PaymentManager:
    def __init__(self):
        pass

    def _post_requests_to_bank(self, request_url, data_json: dict):
        """
            Базовый метод запроса к банку
        """
        headers = {"Content-Type": "application/json"}
        start_time = time.time()
        response_api = requests.post(request_url, json=data_json, headers=headers)
        elapsed_time = time.time() - start_time
        try:
            response = response_api.json()
            if response['Success']:
                return {'success': True, 'response': response, 'elapsed_time': elapsed_time}
            return {
                'success': False, 'response': response, 'code': response_api.status_code,
                'text': response_api.text, 'elapsed_time': elapsed_time
            }
        except Exception as fail:
            return {'success': False, 'response': response_api, 'error': fail}

    def generate_token_for_new_payment(self):
        """ Генерация токена для инициализации заказа """
        pass

    def _generate_token_for_check_order(self, parameters: list):
        """
            Генерация токена для проверки заказа.
            Передается в таком порядке: {OrderId}{Password}{TerminalKey}.
            Прим.: osidvoidsvnb = ["OrderId", "Password", "TerminalKey"]
        """
        concatenated = ''.join([item for item in parameters])
        return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()

    def check_order(self, parameters: list):
        """ Проверка платежа """
        request_url = "https://securepay.tinkoff.ru/v2/CheckOrder"

        post_request = {
            "TerminalKey": TERMINAL_KEY,
            "OrderId": "SZS9M83W5R435DCV",
            "Token": self._generate_token_for_check_order(parameters)
        }

        return self._post_requests_to_bank(request_url, post_request)


def get_year_now():
    return datetime.now().strftime("%Y")


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
