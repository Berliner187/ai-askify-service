from django.http import HttpResponse
from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models import Avg, Count, Max, Min
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Sum
from django.db.models import Sum, F, Value, FloatField
from django.db.models.functions import Coalesce

from datetime import timedelta, datetime
import json
import uuid
import hashlib
import random

from .converter_pdf import *


class Survey(models.Model):
    survey_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=255)
    # questions = models.JSONField()
    questions = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    id_staff = models.UUIDField()
    model_name = models.CharField(max_length=255, blank=True, null=True)
    show_answers = models.BooleanField(default=False)

    def get_questions(self):
        return json.loads(self.questions)

    def __str__(self):
        return self.title

    def save_questions(self, questions_data):
        """
        Сохраняет вопросы в формате JSON, предварительно перемешивая варианты ответов.

        Args:
            questions_data (list): Список словарей вопросов. Каждый словарь должен
                                   содержать 'question', 'options' и 'correct_answer'.
        """
        shuffled_questions = []
        for q_data in questions_data:
            if 'options' in q_data and isinstance(q_data['options'], list):
                options = list(q_data['options'])
                random.shuffle(options)

                new_q_data = {
                    "question": q_data.get('question', ''),
                    "options": options,
                    "correct_answer": q_data.get('correct_answer', '')
                }
                shuffled_questions.append(new_q_data)
            else:
                shuffled_questions.append(q_data)

        self.questions = json.dumps(shuffled_questions, ensure_ascii=False)

    def generate_pdf(self, subscription_level):
        response = HttpResponse(content_type='application/pdf')
        safe_title = "".join(c for c in self.title if c.isalnum() or c in (" ", "_")).rstrip()
        response['Content-Disposition'] = f'attachment; filename="{safe_title}.pdf"'

        converter_pdf = ConverterPDF()
        response = converter_pdf.get_survey_in_pdf(
            response, self.title, self.get_questions(), subscription_level, self.survey_id)

        return response


class SurveyView(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='views')
    view_hash = models.CharField(max_length=255, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)


class UserAnswers(models.Model):
    survey_id = models.UUIDField()
    selected_answer = models.CharField(max_length=255)
    scored_points = models.IntegerField()
    total_points = models.IntegerField()
    user_answers = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    id_staff = models.UUIDField()

    def __str__(self):
        return f"Answers for survey {self.survey_id}"

    def get_user_answers(self):
        return json.loads(self.user_answers)

    def save_user_answers(self, answers):
        self.user_answers = json.dumps(answers)

    @classmethod
    def calculate_user_statistics(cls, id_staff):
        from django.db.models import Q

        surveys = Survey.objects.filter(id_staff=id_staff).only('survey_id', 'title')
        total_tests = surveys.count()

        answers = (
            cls.objects
            .filter(id_staff=id_staff)
            .values('survey_id')
            .annotate(
                scored=Coalesce(Sum('scored_points'), 0),
                total=Coalesce(Sum('total_points'), 0)
            )
        )

        survey_results = {a['survey_id']: a for a in answers}

        passed_tests = 0
        best_result = None

        for survey in surveys:
            result = survey_results.get(survey.survey_id)
            if not result or result['total'] == 0:
                continue

            ratio = result['scored'] / result['total']
            if result['scored'] > 0:
                passed_tests += 1

            if best_result is None or ratio > (best_result['scored'] / best_result['total']):
                best_result = {
                    'title': survey.title,
                    'scored': result['scored'],
                    'total': result['total']
                }

        best_result_str = (
            f"{best_result['title']} – {best_result['scored']} из {best_result['total']}"
            if best_result else "Пока пусто"
        )

        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'best_result': best_result_str,
        }


class AuthUser(AbstractUser):
    id_staff = models.UUIDField(default=uuid.uuid4, blank=False, null=False)
    hash_user_id = models.CharField(max_length=100, blank=False, null=True)

    groups = models.ManyToManyField(
        Group,
        related_name='customuser_set',
        blank=True,
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name='customuser_set',
        blank=True,
    )

    confirmed_user = models.BooleanField(default=False, null=False, blank=False)
    name = models.CharField(max_length=255, unique=False, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = str(self.email).split('@')[0]
        super().save(*args, **kwargs)


class AuthAdditionalUser(models.Model):
    user = models.OneToOneField(AuthUser, on_delete=models.CASCADE, related_name='additional_info')
    id_telegram = models.IntegerField(null=True, blank=True)
    id_vk = models.IntegerField(null=True, blank=True)
    id_yandex = models.IntegerField(null=True, blank=True)


class Subscription(models.Model):
    staff_id = models.UUIDField(blank=False, null=False, unique=True)
    plan_name = models.CharField(max_length=100)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('canceled', 'Canceled'),
    ])
    billing_cycle = models.CharField(max_length=20, choices=[
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ])
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def get_human_plan(self):
        plan_mapping = {
            'free_plan': 'Стартовый на 7 дней',
            'standard_plan': 'Стандартный план на 30 дней',
            'premium_plan': 'Премиум план на 30 дней',
            'standard_plan_year': 'Стандартный план на 365 дней',
            'premium_plan_year': 'Премиум план на 365 дней',
            'ultra_plan': 'Ультра план на 30 дней',
        }
        return plan_mapping.get(self.plan_name, self.plan_name)

    def check_sub_status(self, save=False):
        """
            Проверяет, истекла ли подписка, и возвращает
            актуальный статус: 'active' или 'inactive'/'canceled'.
        """
        now = timezone.now()

        if self.end_date < now:
            new_status = 'inactive'
        else:
            new_status = 'active'

        if save and new_status != self.status:
            self.status = new_status
            self.save(update_fields=['status'])

        return new_status

    def activate_subscription(self, duration_days, new_plan_name=None):
        now = timezone.now()
        if self.status == 'active' and self.end_date > now:
            self.end_date = self.end_date + timedelta(days=duration_days)
        else:
            self.start_date = now
            self.end_date = now + timedelta(days=duration_days)

        self.status = 'active'
        if new_plan_name: self.plan_name = new_plan_name
        self.save(update_fields=['status', 'start_date', 'end_date', 'plan_name'])

    def __str__(self):
        return f'Subscription {self.plan_name} for {self.staff_id}'


class AvailableSubscription(models.Model):
    PLAN_TYPES = [
        ('free_plan', 'Free – 7 days'),
        ('standard_plan', 'Standard Plan – 30 days'),
        ('premium_plan', 'Premium Plan – 30 days'),
        ('tokens_plan', 'Tokens Package'),
    ]

    plan_name = models.CharField(max_length=100, unique=True)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES)
    amount = models.FloatField()
    expiration_date = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.plan_type == 'free_plan':
            self.amount = 0
            self.expiration_date = timezone.now() + timedelta(days=7)
        elif self.plan_type == 'lite_plan':
            self.amount = 99
            self.expiration_date = timezone.now() + timedelta(days=7)
        elif self.plan_type == 'ultra_plan':
            self.amount = 990
            self.expiration_date = timezone.now() + timedelta(days=30)
        elif self.plan_type in ['standard_plan', 'premium_plan']:
            self.amount = 420 if self.plan_type == 'standard_plan' else 590
            self.expiration_date = timezone.now() + timedelta(days=30)
        elif self.plan_type in ['standard_plan_year', 'premium_plan_year']:
            self.amount = 2640 if self.plan_type == 'standard_plan_year' else 4800
            self.expiration_date = timezone.now() + timedelta(days=365)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Available Subscription: {self.plan_name} - {self.amount} (Expires on: {self.expiration_date})'


class Payment(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    staff_id = models.UUIDField(null=False, blank=False)
    payment_id = models.CharField(max_length=100, unique=True)
    order_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])

    def __str__(self):
        return f'Payment {self.payment_id} for {self.subscription.plan_name} - {self.amount}'


class TransactionTracker(models.Model):
    staff_id = models.UUIDField(null=False, blank=False, unique=False)
    payment_id = models.CharField(max_length=100, unique=False)
    order_id = models.CharField(max_length=100, unique=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (f"{self.staff_id}: {self.amount} on {self.date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{self.payment_id} {self.order_id}")


class BlockedUsers(models.Model):
    id_staff = models.UUIDField(null=True, blank=True, unique=True)
    ip_address = models.GenericIPAddressField(unique=True)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.ip_address


class FeedbackFromAI(models.Model):
    survey_id = models.UUIDField(blank=False)
    id_staff = models.UUIDField(blank=False)
    feedback_data = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    model_name = models.CharField(max_length=255, blank=True, null=True)


def get_token_limit(plan_name):
    token_limits = {
        'стартовый': 10_000,
        'лайтовый': 15_000,
        'стандартный': 50_000,
        'премиум': 150_000,
        'ультра': 2_500_000,
        'стандартный год': 50_000,
        'премиум год': 150_000,
    }
    return token_limits.get(plan_name.lower(), 0)


def get_daily_test_limit(plan_name):
    """
    Возвращает дневной лимит на количество создаваемых тестов для данного плана.
    """
    daily_test_limits = {
        'стартовый': 10,
        'лайтовый': 15,
        'стандартный': 50,
        'премиум': 150,
        'ультра': 800,
        'стандартный год': 50,
        'премиум год': 150,
    }
    return daily_test_limits.get(plan_name.lower(), 0)


def slugify_title(title):
    translit_mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '',
        'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya', ' ': '-',
        '-': '-',  # Сохраняем дефисы
        ':': '',  # Убираем двоеточие
        '–': '-',  # Заменяем длинный дефис на обычный
    }

    title = str(title)

    slug = ''.join(translit_mapping.get(char, char) for char in title.lower())

    slug = slug.replace('--', '-')
    slug = slug.strip('-')

    return slug


class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    unique_ips = models.TextField(default='')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify_title(self.title)
        super().save(*args, **kwargs)

    def hash_ip(self, ip):
        return hashlib.sha256(ip.encode()).hexdigest()

    def is_unique_view(self, ip):
        hashed_ip = self.hash_ip(ip)
        if hashed_ip in self.unique_ips.split(','):
            return False
        return True

    def add_unique_view(self, ip):
        if self.is_unique_view(ip):
            self.view_count += 1
            self.unique_ips += self.hash_ip(ip) + ','
            self.save()

    def __str__(self):
        return self.title


def is_user_subscribed_and_has_tokens(user_id):
    try:
        subscription = Subscription.objects.get(staff_id=user_id, status='active')
        if subscription.end_date < datetime.now():
            return False

        tokens_used = TokensUsed.get_tokens_usage(user_id)
        token_limit = get_token_limit(subscription.plan_name)

        total_used = tokens_used['tokens_survey_used'] + tokens_used['tokens_feedback_used']
        return total_used < token_limit

    except Subscription.DoesNotExist:
        return False


class TokensUsed(models.Model):
    id = models.IntegerField(primary_key=True)
    id_staff = models.UUIDField(blank=False, null=False)
    tokens_survey_used = models.IntegerField(blank=False, default=0, null=False)
    tokens_feedback_used = models.IntegerField(blank=False, default=0, null=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.id:
            last_id = TokensUsed.objects.order_by('id').last()
            self.id = (last_id.id + 1) if last_id else 100_000
        super().save(*args, **kwargs)

    @classmethod
    def get_tokens_usage(cls, staff_id):
        """
            Метод для получения использованных токенов для конкретного пользователя за последний месяц
            (с начала предыдущего месяца до текущего дня включительно).
        """
        today = timezone.now().date()
        first_day_of_current_month = today.replace(day=1)

        first_day_of_last_month = (first_day_of_current_month - timedelta(days=1)).replace(day=1)
        tokens = cls.objects.filter(
            id_staff=staff_id,
            created_at__date__gte=first_day_of_last_month,
            created_at__date__lte=today
        ).aggregate(
            total_survey_tokens=Sum('tokens_survey_used'),
            total_feedback_tokens=Sum('tokens_feedback_used')
        )

        return {
            'tokens_survey_used': tokens['total_survey_tokens'] or 0,
            'tokens_feedback_used': tokens['total_feedback_tokens'] or 0,
        }

    @classmethod
    def get_tokens_usage_last_months(cls, staff_id):  # Переименованный метод
        """
            Метод для получения использованных токенов для конкретного пользователя за последний месяц
            (с начала предыдущего месяца до текущего дня включительно).
            Используется для ОБЩЕЙ СТАТИСТИКИ использования токенов.
        """
        today = timezone.now().date()
        first_day_of_current_month = today.replace(day=1)
        last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)

        tokens = cls.objects.filter(
            id_staff=staff_id,
            created_at__date__gte=first_day_of_last_month,
            created_at__date__lte=last_day_of_last_month
        ).aggregate(
            total_survey_tokens=Sum('tokens_survey_used'),
            total_feedback_tokens=Sum('tokens_feedback_used')
        )

        return {
            'tokens_survey_used': tokens['total_survey_tokens'] or 0,
            'tokens_feedback_used': tokens['total_feedback_tokens'] or 0,
        }

    @classmethod
    def get_tokens_usage_today(cls, staff_id):  # Переименованный метод
        """
            Метод для получения использованных токенов для конкретного пользователя за последний месяц
            (с начала предыдущего месяца до текущего дня включительно).
            Используется для ОБЩЕЙ СТАТИСТИКИ использования токенов.
        """
        today = timezone.now().date()

        tokens = cls.objects.filter(
            id_staff=staff_id,
            created_at__date__gte=today,
            created_at__date__lte=today
        ).aggregate(
            total_survey_tokens=Sum('tokens_survey_used'),
            total_feedback_tokens=Sum('tokens_feedback_used')
        )

        return {
            'tokens_survey_used': tokens['total_survey_tokens'] or 0,
            'tokens_feedback_used': tokens['total_feedback_tokens'] or 0,
        }

    def has_available_tokens(self, plan_name):
        tokens_used = self.get_tokens_usage(self.id_staff)
        token_limit = get_token_limit(plan_name)

        total_used = tokens_used['tokens_survey_used'] + tokens_used['tokens_feedback_used']
        return total_used < token_limit

    def add_tokens(self, survey_tokens=0, feedback_tokens=0):
        """Метод для добавления использованных токенов."""
        self.tokens_survey_used += survey_tokens
        self.tokens_feedback_used += feedback_tokens
        self.save()


class APIKey(models.Model):
    name = models.CharField(max_length=100)
    provider = models.CharField(max_length=50)
    purpose = models.CharField(max_length=20)
    key = models.TextField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.provider})"

    class Meta:
        db_table = 'api_keys'


class APIKeyUsage(models.Model):
    api_key = models.ForeignKey(APIKey, on_delete=models.CASCADE, related_name='usages')
    timestamp = models.DateTimeField(default=timezone.now)
    success = models.BooleanField(default=True)
    endpoint = models.CharField(max_length=255, blank=True, null=True)
    response_time_ms = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"Usage of {self.api_key.name} at {self.timestamp}"

    class Meta:
        db_table = 'api_key_usage'
