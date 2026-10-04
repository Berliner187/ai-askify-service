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
from functools import lru_cache

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

from askify_app.settings import OPENAI_API_KEY, OPENAI_PROXY_URL
from openai import AsyncOpenAI

proxy_url = getattr(settings, 'OPENAI_PROXY_URL', None)
http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    http_client=http_client
)

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        self.max_retries = 3
        self.count_questions = q_count

    def get_text_from_request(self):
        return self.data

    def load_forbidden_words(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        forbidden_words_file_path = os.path.join(base_dir, '../askify_app', "forbidden_words.txt")
        if os.path.exists(forbidden_words_file_path):
            with open(forbidden_words_file_path) as f:
                return [w.strip().lower() for w in f.read().splitlines()]
        return []

    def check_forbidden_words(self):
        if any(w in str(self.text_from_user).lower() for w in self.forbidden_words):
            tracer_l.warning(f"Detected forbidden words in input from {self.request.user.username}")
            return True
        return False

    def _validate_json_buffer_encoding(self, data_str):
        pass

    @staticmethod
    def __get_confidential_key(key_name):
        try:
            from askify_service.utils import ManageConfidentFields
            manage_confident_fields = ManageConfidentFields("config.json")
            return manage_confident_fields.get_confident_key(key_name)
        except Exception:
            prompts = {
                'system_prompt': 'Создай тест в формате JSON. Количество вопросов: ',
                'user_prompt': '\nВерни строго JSON объект с полями title и questions.'
            }
            return prompts.get(key_name, '')

    async def openai_generate(self, specific_key=None) -> dict:
        """
        ЕДИНОЕ БОЕВОЕ ЯДРО:
        1. Берет ключ из БД (или specific_key / .env fallback).
        2. Пробивает через HTTP-прокси.
        3. Записывает использованный ключ для статистики.
        """
        from askify_service.models import APIKey

        if self.check_forbidden_words():
            return {
                'success': False,
                'error': 'Обнаружен недопустимый контент. Пожалуйста, измените текст.'
            }

        if specific_key:
            keys_pool = [specific_key]
        else:
            keys_pool = await sync_to_async(list)(
                APIKey.objects.filter(purpose="SURVEY", is_active=True).order_by('-created_at')
            )

        proxy_url = getattr(settings, 'OPENAI_PROXY_URL', None) or os.getenv("OPENAI_PROXY_URL")
        env_api_key = getattr(settings, 'OPENAI_API_KEY', None) or os.getenv("OPENAI_API_KEY")

        if not keys_pool and env_api_key:
            keys_pool = [None]

        if not keys_pool:
            tracer_l.error("NO API KEYS: База пуста и в .env нет OPENAI_API_KEY!")
            return {'success': False, 'error': 'Нет доступных ключей API для генерации.'}

        system_prompt = f"{self.__get_confidential_key('system_prompt')}{self.count_questions}"
        user_prompt = f"{self.data}{self.__get_confidential_key('user_prompt')}"

        for api_key_obj in keys_pool:
            db_key = api_key_obj
            if db_key and db_key.key:
                raw_key = db_key.key.strip()
                base_url = db_key.base_url or None
                model_name = getattr(db_key, 'model_name', None) or "gpt-4o-mini"
            else:
                raw_key = env_api_key.strip()
                base_url = None
                model_name = "gpt-4o-mini"

            # Прокси: если внешний хост (OpenAI / Azure) — пускаем через прокси
            is_local = base_url and ("localhost" in base_url or "127.0.0.1" in base_url)
            use_proxy = proxy_url if (proxy_url and not is_local) else None

            http_client = httpx.AsyncClient(proxy=use_proxy, timeout=60.0) if use_proxy else None

            client = AsyncOpenAI(
                api_key=raw_key,
                base_url=base_url,
                http_client=http_client,
                timeout=55.0
            )

            try:
                tracer_l.info(
                    f"START GEN: user={self.request.user.username}, model={model_name}, "
                    f"proxy={'YES' if use_proxy else 'NO'}, key_id={getattr(db_key, 'id', 'ENV')}"
                )

                kwargs = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                }

                if "gpt" in model_name.lower():
                    kwargs["response_format"] = {"type": "json_object"}

                completion = await client.chat.completions.create(**kwargs)

                generated_text = completion.choices[0].message.content
                tokens_used = getattr(completion.usage, 'total_tokens', 0)

                # Очистка и ремонт JSON
                cleaned_text = generated_text.replace("```json", "").replace("```", "").strip()

                try:
                    parsed_json = json.loads(cleaned_text)
                except json.JSONDecodeError:
                    tracer_l.warning("OpenAI вернул неидеальный JSON. Применяем json_repair...")
                    parsed_json = json_repair.loads(cleaned_text)

                if not isinstance(parsed_json, (dict, list)):
                    raise ValueError("Не удалось распарсить JSON из ответа модели")

                tracer_l.info(f"SUCCESS GEN: tokens={tokens_used}, key_id={getattr(db_key, 'id', 'ENV')}")

                return {
                    'success': True,
                    'generated_text': parsed_json,
                    'tokens_used': tokens_used,
                    'model_used': model_name,
                    'api_key_used': db_key,
                }

            except APIStatusError as e:
                tracer_l.warning(f"APIStatusError on key {getattr(db_key, 'name', 'ENV')}: {e.status_code}")
                # Если 401 — гасим дохлый ключ в БД
                if e.status_code == 401 and db_key:
                    tracer_l.critical(f"Key {db_key.name} (ID: {db_key.id}) is 401 INVALID. Deactivating.")
                    db_key.is_active = False
                    await sync_to_async(db_key.save)(update_fields=['is_active'])
                continue

            except Exception as e:
                tracer_l.error(f"Generation error on key {getattr(db_key, 'name', 'ENV')}: {e}")
                continue

            finally:
                if http_client:
                    await http_client.aclose()

        return {
            'success': False,
            'error': 'Сервер генерации временно перегружен. Пожалуйста, попробуйте через минуту.'
        }

    async def generate_with_failover(self):
        """Если вьюха вызывает старый failover — перенаправляем в боевой openai_generate"""
        return await self.openai_generate()

    async def github_gpt(self, api_key=None):
        """Если вьюха вызывает старый github_gpt — перенаправляем в боевой openai_generate"""
        return await self.openai_generate(specific_key=api_key)

    async def smart_generate(self):
        """Если включен локальный debug в LM Studio"""
        if getattr(settings, 'DEBUG', False) is True:
            try:
                local_client = AsyncOpenAI(
                    base_url="http://localhost:1234/v1",
                    api_key="lm-studio",
                    timeout=httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=10.0)
                )
                res = await self._execute_generation(local_client, model="openai/gpt-oss-20b")
                if res.get('success'):
                    return res
            except Exception as e:
                tracer_l.warning(f"Local machine LM Studio unavailable: {e}")

        return await self.openai_generate()

    async def _execute_generation(self, client, model):
        try:
            completion = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": f"{self.__get_confidential_key('system_prompt')}{self.count_questions}"},
                    {"role": "user", "content": f"{self.data}{self.__get_confidential_key('user_prompt')}"},
                ],
                temperature=0.3,
                max_tokens=4096
            )
            cleaned = completion.choices[0].message.content.replace("```json", "").replace("```", "").strip()
            parsed = json_repair.loads(cleaned)
            return {'success': True, 'generated_text': parsed, 'tokens_used': 0, 'model_used': model, 'api_key_used': None}
        except Exception as e:
            return {'success': False, 'message': str(e)}


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
            "temperature": 0.3,
            "max_tokens": 2048,
            "stream": False
        })
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.__get_confidential_key("api_arliai")}'
        }
        response = requests.post(url, headers=headers, data=payload)
        return response.json()

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


@lru_cache(maxsize=4)
def get_encoding(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str = 'gpt-4o') -> int:
    encoding = get_encoding(model)
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
