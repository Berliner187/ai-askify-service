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
import httpx
import asyncio

from .tracer import *
from .constants import *


tracer_l = TracerManager(TRACER_FILE)


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


manage_conf = ManageConfidentFields("config.json")
TERMINAL_KEY = manage_conf.get_confident_key("bank_terminal_key")
TERMINAL_PASSWORD = manage_conf.get_confident_key("bank_terminal_password")


class ManageGenerationSurveys:
    def __init__(self, request, data):
        self.request = request
        self.data = data
        self.text_from_user = self.get_text_from_request()
        self.forbidden_words = self.load_forbidden_words()
        self.generation_models_control = GenerationModelsControl()
        self.max_retries = 5

    def get_text_from_request(self):
        print(self.data)
        return self.data

    def load_forbidden_words(self):
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
        if self.check_forbidden_words():
            return 420

        self.log_info("start the generated: {}".format(self.text_from_user[:32]))
        print("start the generated: {}".format(self.text_from_user[:32]))

        # for attempt in range(self.max_retries):
            # try:
        ai_response = self.generation_models_control.get_generated_survey_0003(self.text_from_user)
        if ai_response.get('success'):
            generated_text, tokens_used = ai_response.get('generated_text'), ai_response.get('tokens_used')
            print("generate_survey_for_user", generated_text, tokens_used)
            return self.process_generated_text(generated_text), tokens_used
        else:
            self.log_error('error in ai_response at generate_survey', ai_response)
            # except Exception as fail:
            #     print(fail, attempt)
            #     self.log_error("Code 429", str(fail))
            #     if attempt < self.max_retries - 1:
            #         return JsonResponse(
            #             {'error': f"Сервер перегружен. Пожалуйста, повторите попытку позже."},
            #             status=429
            #         )
            #     else:
            #         self.log_error(429, "AI: Server Overloaded")
            #         return JsonResponse({'error': 'Сервер перегружен, попробуйте позже.'}, status=429)

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
            print(json_match)
            self.log_warning("JSON not found")
            return JsonResponse({'error': f"{generated_text}"}, status=429)

    def log_error(self, error_type, message):
        print(error_type, message)
        tracer_l.tracer_charge(
            'ERROR', self.request.user.username, self.generate_survey_for_user.__name__,
            error_type, message
        )


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


def init_free_subscription():
    plan_name = 'Стартовый план'
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

        for model in MODEL_NAMES:
            try:
                completion = client.chat.completions.create(
                    model=model,
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

                if hasattr(completion, 'error') and completion.error is not None:
                    error_message = completion.error.get('message', 'Unknown error')
                    raise Exception(f"Error from API: {error_message}")

                return self.__generate_completion(completion)

            except Exception as fail:
                tracer_l.tracer_charge('WARNING', '', 'get_generated_feedback_0003',
                                       f'FAILED to load model: {model}. Error: {str(fail)}', fail)

        return None

    def get_feedback_001(self, text_from_user):
        ai_response = self.get_generated_feedback_0003(text_from_user)

        if ai_response.get('success') is True:
            print("Feedback's response:", ai_response)
            return ai_response
        else:
            return {'success': False, 'feedback_text': None, 'tokens_used': None}

    @staticmethod
    def __generate_completion(completion) -> dict:
        print(completion)
        try:
            if completion.choices:
                generated_text = completion.choices[0].message.content
                print("\n\ngenerated_text", generated_text)
                cleaned_generated_text = generated_text.replace("json", "").replace("`", "")
                tokens_used = completion.usage.total_tokens
                print("\n\ncleaned_generated_text", cleaned_generated_text, tokens_used)
                return {
                    'success': True, 'generated_text': cleaned_generated_text, 'tokens_used': tokens_used
                }
            else:
                error_message = "No choices available in the completion response."
                tracer_l.tracer_charge(
                    "WARNING", '', "__generate_completion",
                    "error generate", error_message
                )
                raise ValueError(error_message)

        except Exception as fail:
            print(fail)
            if hasattr(completion, 'error') and completion.error is not None:
                error_info = completion.error
                code = error_info.get('code', 'Unknown error code')
                raw_metadata = error_info.get('metadata', {}).get('raw', '')

                tracer_l.tracer_charge(
                    "ERROR", '', "__generate_completion",
                    f"error generate: {completion}", f"{fail}"
                )

                if raw_metadata:
                    try:
                        metadata = json.loads(raw_metadata)
                        message = metadata.get('error', {}).get('message', 'No error message provided')
                    except json.JSONDecodeError:
                        message = 'Failed to decode error message from raw metadata'
                else:
                    message = 'No raw metadata available'

                print(f"Code: {code}, Message: {message}")
                return {'success': False, 'code': code, 'message': message}
            else:
                print("Не удалось получить информацию об ошибке.")
                return {'success': False, 'code': 429, 'message': str(fail)}

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

        for model in MODEL_NAMES:
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
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
            except Exception as fail:
                tracer_l.tracer_charge('WARNING', '', 'get_generated_feedback_0003',
                                       f'FAILED to load model: {model}', fail)

        return None

    # async def get_generated_survey_0003(self, text_from_user):
    #     async with httpx.AsyncClient() as client:
    #         response = await client.post(
    #             "https://openrouter.ai/api/v1/chat/completions",
    #             json={
    #                 "model": "meta-llama/llama-3.2-90b-vision-instruct:free",
    #                 "messages": [
    #                     {
    #                         "role": "system",
    #                         "content": [
    #                             {
    #                                 "type": "text",
    #                                 "text": f"{self.__get_confidential_key('system_prompt')}"
    #                             },
    #                             {
    #                                 "type": "text",
    #                                 "text": f"{text_from_user} {self.__get_confidential_key('user_prompt')}"
    #                             }
    #                         ]
    #                     }
    #                 ]
    #             },
    #             headers={"Authorization": f"Bearer {self.__get_confidential_key('openrouter')}"}
    #         )
    #         completion = response.json()
    #         return self.__generate_completion(completion)


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

    @staticmethod
    def generate_token_for_new_payment(data_order):
        """ Генерация токена для инициализации заказа """
        sorted_data = sorted(data_order, key=lambda x: list(x.keys())[0])
        concatenated = ''.join([list(item.values())[0] for item in sorted_data])
        return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()

    def create_payment(self):
        return

    def _generate_token_for_check_order(self, parameters: list):
        """
            Генерация токена для проверки заказа.
            Передается в таком порядке: {OrderId}{Password}{TerminalKey}.
            Прим.: order_data = ["OrderId", "Password", "TerminalKey"]
        """
        concatenated = ''.join([item for item in parameters])
        return hashlib.sha256(concatenated.encode('utf-8')).hexdigest()

    def check_order(self, parameters: list):
        """ Проверка платежа """
        request_url = "https://securepay.tinkoff.ru/v2/CheckOrder"

        post_request = {
            "TerminalKey": TERMINAL_KEY,
            "OrderId": parameters[0],
            "Token": self._generate_token_for_check_order(parameters)
        }

        return self._post_requests_to_bank(request_url, post_request)


class SubscriptionCheck:
    """
        Проверка уровня доступа в подписке.
    """
    def __init__(self, level=0):
        self.level = level
        self.plans = SUBSCRIPTION_TIERS

    def get_subscription_name(self):
        return self.plans.get(self.level, "Стартовый план")

    def get_subscription_level(self, subscription_name):
        for number, name in self.plans.items():
            if name == subscription_name:
                return number
        return 0


def get_year_now():
    return datetime.now().strftime("%Y")


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
