import uuid
from django.db import transaction
from .models import AuthUser, AuthAdditionalUser, Subscription

from askify_service.utils import init_free_subscription


def get_or_create_telegram_user(telegram_data: dict):
    tg_id = int(telegram_data['id'])
    tg_username = telegram_data.get('username')
    first_name = telegram_data.get('first_name', '')
    last_name = telegram_data.get('last_name', '')

    user = None

    try:
        return AuthAdditionalUser.objects.get(id_telegram=tg_id).user
    except AuthAdditionalUser.DoesNotExist:
        pass

    if tg_username:
        user = AuthUser.objects.filter(username__iexact=tg_username).first()

    if not user:
        user = AuthUser.objects.filter(username=str(tg_id)).first()

    if user:
        AuthAdditionalUser.objects.update_or_create(
            user=user,
            defaults={'id_telegram': tg_id}
        )

        if not user.first_name and first_name:
            user.first_name = first_name
            user.save(update_fields=['first_name'])

    else:
        final_username = tg_username
        if not final_username:
            final_username = f"tg_{tg_id}"

        counter = 0
        base_username = final_username
        while AuthUser.objects.filter(username=final_username).exists():
            counter += 1
            final_username = f"{base_username}_{counter}"

        with transaction.atomic():
            user = AuthUser.objects.create(
                username=final_username,
                first_name=first_name,
                last_name=last_name,
                confirmed_user=True,
                id_staff=uuid.uuid4()
            )
            user.set_unusable_password()
            user.save()

            AuthAdditionalUser.objects.create(
                user=user,
                id_telegram=tg_id
            )

    if not Subscription.objects.filter(staff_id=user.id_staff).exists():
        try:
            print(f"FIX: Creating missing subscription for {user.username}")
            plan_name, end_date, status, billing_cycle, discount = init_free_subscription()

            Subscription.objects.create(
                staff_id=user.id_staff,
                plan_name=plan_name,
                end_date=end_date,
                status=status,
                billing_cycle=billing_cycle
            )
        except Exception as e:
            print(f"CRITICAL SUBSCRIPTION ERROR: {e}")

    return user
