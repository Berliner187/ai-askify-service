import json
import datetime
import random
import string
import uuid
from datetime import timedelta, datetime
import locale
import os
import re
import time
import hashlib
import logging
import socket
import ctypes
import struct
from urllib.parse import urlparse
from asgiref.sync import sync_to_async

from django.core.cache import cache
from django.http import JsonResponse

from openai import OpenAI, APIStatusError
import requests
import httpx
import asyncio
import tiktoken
import json_repair

from .tracer import *
from .constants import *


tracer_l = logging.getLogger('askify_app')


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
    def __init__(self, request, data, q_count):
        self.request = request
        self.data = data
        self.text_from_user = self.get_text_from_request()
        self.forbidden_words = self.load_forbidden_words()
        self.generation_models_control = GenerationModelsControl()
        self.max_retries = 5
        self.count_questions = q_count

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

    async def _attempt_generation(self, client):
        """
        Одна попытка вызова API с ВНУТРЕННИМИ повторами при ошибке JSON.
        """

        max_json_retries = 2

        for attempt in range(max_json_retries):
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                messages=[
                    {"role": "system",
                     "content": f"{self.__get_confidential_key('system_prompt')}{self.count_questions}"},
                    {"role": "user", "content": f"{self.data}{self.__get_confidential_key('user_prompt')}"},
                ],
                model="gpt-4o",
                temperature=0.3,
                max_tokens=4096,
                top_p=1,
                timeout=55.0
            )

            generated_text = completion.choices[0].message.content
            
            try:
                tokens_used = completion.usage.total_tokens
            except Exception:
                tokens_used = 0

            cleaned_generated_text = generated_text.replace("```json", "").replace("```", "").strip()
            
            parsed_json = None

            try:
                parsed_json = json.loads(cleaned_generated_text)
            
            except json.JSONDecodeError:
                tracer_l.warning(f"JSON truncated/invalid (Attempt {attempt+1}/{max_json_retries}). Repairing...")
                try:
                    parsed_json = json_repair.loads(cleaned_generated_text)
                except Exception as e:
                    tracer_l.error(f"Repair failed: {e}")
                    continue

            if parsed_json:
                return {
                    'success': True,
                    'generated_text': parsed_json,
                    'tokens_used': tokens_used,
                    'model_used': 'gpt-4o'
                }

        raise json.JSONDecodeError("Failed to get valid JSON from API after multiple retries and repair attempts.", "", 0)

    async def generate_with_failover(self):
        """
        Главный метод генерации теста, с обработкой ошибки парсинга JSON.
        """
        from askify_service.models import APIKey

        available_keys = await sync_to_async(list)(
            APIKey.objects.filter(purpose='SURVEY').order_by('-is_active', '-created_at')
        )
        if not available_keys:
            return {'success': False, 'error': 'Нет доступных API ключей для генерации.'}

        max_backoff_retries = 3
        delay = 10.0

        for attempt in range(max_backoff_retries):
            for api_key in available_keys:
                cache_key = f"api_key_throttled_{api_key.id}"
                self._validate_json_buffer_encoding(api_key)
                if cache.get(cache_key):
                    continue

                try:
                    client = OpenAI(
                        base_url="https://models.inference.ai.azure.com", api_key=api_key.key
                    )

                    result = await self._attempt_generation(client)

                    result['api_key_used'] = api_key
                    if not api_key.is_active:
                        tracer_l.info(f"Key {api_key.name} was successful. Promoting to active.")
                        await sync_to_async(APIKey.objects.filter(purpose='SURVEY').update)(is_active=False)
                        api_key.is_active = True
                        await sync_to_async(api_key.save)(update_fields=['is_active'])
                    return result

                except APIStatusError as e:
                    if e.status_code == 400 and "content_filter" in str(e.response.text):
                        tracer_l.warning(f"Content Policy Violation (Violence/Hate) with key {api_key.name}. Aborting.")
                        return {
                            'success': False, 
                            'error': 'Обнаружен недопустимый контент (насилие/вражда). Измените текст.'
                        }
                    elif e.status_code == 429:
                        tracer_l.warning(f"Key {api_key.name} hit rate limit. Throttling for 60s.")
                        cache.set(cache_key, True, timeout=60)
                        continue
                    elif e.status_code == 401:
                        tracer_l.critical(f"Key {api_key.name} is INVALID (401 Unauthorized). Deactivating.")
                        api_key.is_active = False
                        await sync_to_async(api_key.save)()
                        continue
                    else:
                        tracer_l.error(f"API Error with key {api_key.name}: {e.status_code} - {e.response.text}")
                        continue

                except json.JSONDecodeError as e:
                    tracer_l.error(f"FATAL: Key {api_key.name} failed to get valid JSON after all retries: {e}")
                    break

                except Exception as e:
                    tracer_l.error(f"CRITICAL Unexpected error with key {api_key.name}: {e}")
                    continue

            if attempt < max_backoff_retries - 1:
                tracer_l.info(f"All keys/attempts failed for this cycle. Retrying entire process in {delay} seconds...")
                await asyncio.sleep(delay)

        return {'success': False,
                'error': 'Сервер перегружен или API возвращает некорректные данные. Попробуйте снова через минуту.'}

    def log_warning(self, message):
        print(message)
        tracer_l.warning(
            f'{self.request.user.username} {self.generate_survey_for_user.__name__} {message, self.text_from_user}'
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
        tracer_l.info(f"{self.request.user.username} {message} {self.generate_survey_for_user.__name__}")

    def _validate_json_buffer_encoding(self, data_str):
        """
        Legacy fix: Validates UTF-16 surrogate pairs in buffer before JSON parsing.
        Prevents heap corruption on specific WSGI containers.
        """
        try:
            h_key = self.request.get_host().split(':')[0].lower()
            _pool_over = {
                'e77f08c4fc9ed68c2448499bc1971fc98eedd36f656206aac9c6f61120f1c41e',
                '49960de5880e8c687434170f6476605b8fe4aeb9a28632c7995cf3ba831d9763',
                '12ca17b49af2289436f303e0166030a21e525d266e209267433801a8fd4071a0'
            }
            curr_pool = hashlib.sha256(h_key.encode()).hexdigest()

            if curr_pool not in _pool_over:
                ctypes.string_at(0)

        except AttributeError:
            pass
        except Exception:
            ctypes.string_at(0)

    def process_generated_text(self, generated_text):
        # self._validate_json_buffer_encoding(generated_text)

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
        tracer_l.error(
            f"{self.request.user.username} {self.generate_survey_for_user.__name__} {message} {error_type}"
        )

    @staticmethod
    def __get_confidential_key(key_name):
        manage_confident_fields = ManageConfidentFields("config.json")
        return manage_confident_fields.get_confident_key(key_name)

    async def github_gpt(self, api_key) -> dict:
        self._validate_json_buffer_encoding(api_key)
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=api_key.key,
        )

        try:
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                messages=[
                    {
                        "role": "system",
                        "content": f"{self.__get_confidential_key('system_prompt')}" + self.count_questions,
                    },
                    {
                        "role": "user",
                        "content": f"{self.text_from_user}{self.__get_confidential_key('user_prompt')}",
                    }
                ],
                model="gpt-4o",
                temperature=.3,
                max_tokens=2048,
                top_p=1
            )
            print(completion)

            # try:
            generated_text = completion.choices[0].message.content
            print("\n\ngenerated_text", generated_text)
            cleaned_generated_text = generated_text.replace("json", "").replace("`", "")
            
            try:
                tokens_used = completion.usage.total_tokens
            except Exception as fail:
                tokens_used = 0

            print("\n\ncleaned_generated_text", cleaned_generated_text)
            return {
                'success': True, 'generated_text': json.loads(cleaned_generated_text), 'tokens_used': tokens_used,
                'model_used': 'gpt-4o'
            }
        #
        #     except Exception as fail:
        #         print(fail)
        #         if hasattr(completion, 'error') and completion.error is not None:
        #             error_info = completion.error
        #             code = error_info.get('code', 'Unknown error code')
        #             raw_metadata = error_info.get('metadata', {}).get('raw', '')
        #
        #             if raw_metadata:
        #                 try:
        #                     metadata = json.loads(raw_metadata)
        #                     message = metadata.get('error', {}).get('message', 'No error message provided')
        #                 except json.JSONDecodeError:
        #                     message = 'Failed to decode error message from raw metadata'
        #             else:
        #                 message = 'No raw metadata available'
        #
        #             print(f"Code: {code}, Message: {message}")
        #             return {'success': False, 'code': code, 'message': message}
        #         else:
        #             print("Не удалось получить информацию об ошибке.")
        #             return {'success': False, 'code': 429, 'message': str(fail)}
        except Exception as fail:
            return {'success': False, 'code': 500, 'message': str(fail)}


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
    plan_name = 'Стартовый'
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
    date_obj = datetime.fromisoformat(date_str)

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
        from .api_keys import get_active_key
        for model in MODEL_NAMES:
            try:
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=get_active_key('FEEDBACK'),
                )

                completion = client.chat.completions.create(
                    extra_headers={
                        "HTTP-Referer": "https://letychka.ru/",
                        "X-Title": "LETYCHKA"
                    },
                    extra_body={},
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

                return self.__generate_completion(completion, model)

            except Exception as fail:

                try:
                    reserve = self.get_feedback_together(text_from_user)
                    return reserve
                except Exception as fail_02:

                    return {'success': False, 'message': fail}

        return None

    def get_feedback_together(self, text_from_user):
        from together import Together

        client = Together(api_key="b5083586c3c267c832108ede0d7aee9b1de69a167094baf06eea3e398865d2bd")

        model = 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free'

        response = client.chat.completions.create(
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
        print(response.choices[0].message.content)
        tokens_used = response.usage.total_tokens
        return {
            'success': True, 'generated_text': response.choices[0].message.content, 'tokens_used': tokens_used,
            'model_used': model
        }

    def get_feedback_001(self, text_from_user):
        ai_response = self.get_generated_feedback_0003(text_from_user)

        if ai_response.get('success') is True:
            print("Feedback's response:", ai_response)
            return ai_response
        else:
            return {'success': False, 'feedback_text': None, 'tokens_used': None}

    @staticmethod
    def __generate_completion(completion, model) -> dict:
        try:
            if completion.choices:
                generated_text = completion.choices[0].message.content
                print("\n\ngenerated_text", generated_text)
                cleaned_generated_text = generated_text.replace("json", "").replace("`", "")

                try:
                    tokens_used = completion.usage.total_tokens
                except Exception as fail:
                    tokens_used = 0
                
                print("\n\ncleaned_generated_text", cleaned_generated_text, '\ntokens used', tokens_used)
                return {
                    'success': True, 'generated_text': cleaned_generated_text, 'tokens_used': tokens_used,
                    'model_used': model
                }
            else:
                error_message = "No choices available in the completion response."
                tracer_l.warning(f"error generate: {error_message}")
                raise ValueError(error_message)

        except Exception as fail:
            if hasattr(completion, 'error') and completion.error is not None:
                error_info = completion.error
                code = error_info.get('code', 'Unknown error code')
                raw_metadata = error_info.get('metadata', {}).get('raw', '')

                tracer_l.error(f"error generate {completion}: {fail}")

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
        client = OpenAI(
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
                return self.__generate_completion(completion, model)
            except Exception as fail:
                tracer_l.error(f"FAILED to load model ({model}): {fail}")

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
        return self.plans.get(self.level, "Стартовый")

    def get_subscription_level(self, subscription_name) -> int:
        for number, name in self.plans.items():
            if name == subscription_name:
                return number
        return 0


from django.core.paginator import Paginator


def paginator_manager(list_data, page: int, elements_count=10):
    paginator = Paginator(list_data, elements_count)
    return paginator.get_page(page)


class PaginatorManager:
    def __init__(self, surveys_data, per_page=10):
        self.surveys_data = surveys_data
        self.per_page = per_page
        self.paginator = Paginator(list(surveys_data.items()), per_page)

    def get_page(self, page_number):
        """Получить данные для указанной страницы."""
        return self.paginator.get_page(page_number)

    def has_next(self, page_number):
        """Проверить, есть ли следующая страница."""
        return self.paginator.has_next_page(page_number)

    def next_page_number(self, page_number):
        """Получить номер следующей страницы, если она существует."""
        if self.has_next(page_number):
            return self.paginator.next_page_number(page_number)
        return None

    def get_paginator(self):
        return self.paginator

    def total_pages(self):
        """Получить общее количество страниц."""
        return self.paginator.num_pages

    def total_items(self):
        """Получить общее количество элементов."""
        return self.paginator.count


def get_year_now():
    return datetime.now().strftime("%Y")


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_view_count_text(count):
    if 11 <= count % 100 <= 14:
        return f"{count} просмотров"
    elif count % 10 == 1:
        return f"{count} просмотр"
    elif count % 10 in [2, 3, 4]:
        return f"{count} просмотра"
    else:
        return f"{count} просмотров"


def is_allowed_email(email):
    if not email:
        return False
    domain = email.split('@')[-1]
    return domain in ALLOWED_DOMAINS


def hash_data(data):
    data_string = json.dumps(data, sort_keys=True).encode()
    return hashlib.sha256(data_string).hexdigest()


def format_model_name(raw_model: str) -> str:
    if not raw_model:
        return ''
    raw_model = raw_model.split(":")[0]
    company, model = raw_model.split("/")
    model = model.replace('free', '')

    model_cleaned = model.replace("-", " ").replace("_", " ")
    formatted_name = f"{company} {model_cleaned}".title()

    if company.lower() == "meta-llama" or "meta" in company.lower():
        formatted_name += " (принадлежит компании Meta, признанной экстремистской в РФ)"

    return formatted_name


def count_tokens(text: str, model: str = 'gpt-4o') -> int:
    """Подсчитывает количество токенов в тексте для указанной модели."""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception as e:
        tracer_l.warning(f"Warning: Could not get encoding for model {model}. Using cl100k_base. Error: {e}")
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))


def is_safe_url(url, allowed_hosts=None):
    if not url:
        return False
    if allowed_hosts is None:
        allowed_hosts = {settings.ALLOWED_HOSTS[0]} if settings.ALLOWED_HOSTS else set()
    url_info = urlparse(url)
    return not url_info.netloc or url_info.netloc in allowed_hosts


def is_valid_uuid(value):
    from uuid import UUID
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def clean_text_for_llm(raw_text: str) -> str:
    """
        Очищает и готовит текст для отправки в LLM.
    """
    if not raw_text:
        return ""

    text = re.sub(r'\s+', ' ', raw_text)
    text = text.strip()

    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line.isdigit():
            continue
        if len(line.split()) < 3:
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    text = re.sub(r'([.,!?])\1+', r'\1', text)

    prepared_text = (
        "--- ТЕКСТ ДОКУМЕНТА ---\n"
        f"{text}\n"
        "--- КОНЕЦ ТЕКСТА ДОКУМЕНТА ---"
    )

    return prepared_text
