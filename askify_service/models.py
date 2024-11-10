from django.http import HttpResponse
from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models import Avg, Count, Max, Min
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import get_language

from datetime import timedelta
import datetime
import json
import uuid

from .utils import *


class Survey(models.Model):
    survey_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=255)
    # questions = models.JSONField()
    questions = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    id_staff = models.UUIDField()

    def get_questions(self):
        return json.loads(self.questions)

    def __str__(self):
        return self.title

    def save_questions(self, questions):
        self.questions = json.dumps(questions)

    def generate_pdf(self):
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{self.title}.pdf"'

        converter_pdf = ConverterPDF()
        response = converter_pdf.get_survey_in_pdf(response, self.title, self.get_questions())

        return response


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
        user_surveys = Survey.objects.filter(id_staff=id_staff)
        user_answers = cls.objects.filter(id_staff=id_staff)

        total_scored_points = 0

        total_points = 0
        for answer in user_answers:
            total_scored_points += answer.scored_points
            total_points += answer.total_points

        total_tests = user_surveys.count()
        # average_score = user_answers.aggregate(Avg('scored_points'))['scored_points__avg'] or 0
        # passed_tests =
        try:
            average_score = round(total_scored_points / total_tests, 2)
        except ZeroDivisionError:
            average_score = 0

        return {
            'total_tests': total_tests,
            'average_score': average_score,
        }


class AuthUser(AbstractUser):
    id_arrival = models.CharField(max_length=100, blank=True, null=True)
    id_staff = models.UUIDField(default=uuid.uuid4, blank=False, null=False)

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

    def __str__(self):
        return self.username

    def log_activity(self, request):
        language_code = get_language() if hasattr(request, 'LANGUAGE_CODE') else None

        try:
            UserActivity.objects.create(
                id_staff=self.id_staff,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT'),
                referer=request.META.get('HTTP_REFERER'),
                language_code=language_code,
                created_at=timezone.now()
            )
        except Exception as fail:
            pass


class UserActivity(models.Model):
    id_staff = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, null=True, blank=True)
    referer = models.URLField(null=True, blank=True)
    language_code = models.CharField(max_length=10, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Subscription(models.Model):
    staff_id = models.UUIDField()
    plan_name = models.CharField(max_length=100)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('canceled', 'Canceled'),
    ])
    billing_cycle = models.CharField(max_length=20, choices=[
        ('weakly', 'Weakly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ])
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def remaining_time(self):
        return self.end_date - datetime.datetime.now()

    def __str__(self):
        return f'Subscription {self.plan_name} for {self.staff_id}'


class Payment(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    payment_id = models.CharField(max_length=100, unique=True, default=generate_payment_id)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])

    def __str__(self):
        return f'Payment {self.payment_id} for {self.subscription.plan_name} - {self.amount}'


class AvailableSubscription(models.Model):
    PLAN_TYPES = [
        ('free', 'Free – 7 days'),
        ('standard', 'Standard – 30 days'),
        ('plus', 'Plus – 90 days'),
    ]

    plan_name = models.CharField(max_length=100, unique=True)
    amount = models.FloatField()
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES)
    expiration_date = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.plan_type == 'free':
            self.expiration_date = timezone.now() + datetime.timedelta(days=7)
        elif self.plan_type == 'standard':
            self.expiration_date = timezone.now() + datetime.timedelta(days=30)
        elif self.plan_type == 'plus':
            self.expiration_date = timezone.now() + datetime.timedelta(days=30)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Available Subscription: {self.plan_name} - {self.amount} (Expires on: {self.expiration_date})'


class BlockedUsers(models.Model):
    id_staff = models.UUIDField(null=True, blank=True, unique=True)
    ip_address = models.GenericIPAddressField(unique=True)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.ip_address
