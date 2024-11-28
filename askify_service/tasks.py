from celery import shared_task
from django.utils import timezone
from .models import Subscription


@shared_task
def check_subscriptions():
    now = timezone.now()
    expired_subscriptions = Subscription.objects.filter(status='active', end_date__lt=now)

    for subscription in expired_subscriptions:
        subscription.status = 'inactive'
        subscription.save()
