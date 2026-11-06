"""
Создание и привязка аккаунтов через внешних провайдеров (сейчас — Яндекс ID).

Повторяет побочные эффекты register_view, чтобы пользователь из Яндекса
ничем не отличался от зарегистрированного через форму:
  - конвертация гостевого пользователя (демо-режим) в постоянного;
  - перенос демо-теста из сессии;
  - бесплатная подписка (init_free_subscription);
  - счётчик регистраций по IP (без блокировки — см. README).
ArenaProfile создаётся сигналом post_save автоматически.
"""
import logging
import re
import uuid

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models.functions import Length
from django.utils import timezone

from askify_service.models import AuthUser, SocialAccount, Subscription, Survey
from askify_service.utils import get_client_ip, init_free_subscription, is_allowed_email

log = logging.getLogger("askify_app")

# Аналитика считает «реальными» пользователей с username короче 20 символов.
USERNAME_MAX = 19
REG_COUNTER_TTL = 60 * 60 * 24


class AccountError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""

    def __init__(self, code, message):
        super().__init__(code)
        self.code = code
        self.message = message


def resolve_temporary_user(request):
    """Гостевой пользователь текущего посетителя (та же логика, что в views)."""
    guest_staff_id = request.session.get("guest_staff_id")
    if guest_staff_id:
        temp = AuthUser.objects.filter(id_staff=guest_staff_id, email__isnull=True).first()
        if temp:
            return temp

    ip = get_client_ip(request)
    if not ip:
        return None
    return (
        AuthUser.objects.annotate(username_len=Length("username"))
        .filter(hash_user_id=ip, email__isnull=True, username_len__gt=20)
        .first()
    )


def unique_username(seed, exclude_pk=None):
    base = re.sub(r"[^A-Za-z0-9_.\-]", "", seed or "").strip("._-")[:USERNAME_MAX] or "user"
    qs = AuthUser.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    candidate, n = base, 1
    while qs.filter(username=candidate).exists():
        suffix = f"_{n}"
        candidate = base[: USERNAME_MAX - len(suffix)] + suffix
        n += 1
    return candidate


def ensure_free_subscription(user):
    plan_name, end_date, status, billing_cycle, _ = init_free_subscription()
    Subscription.objects.get_or_create(
        staff_id=user.id_staff,
        defaults={
            "plan_name": plan_name,
            "end_date": end_date,
            "status": status,
            "billing_cycle": billing_cycle,
        },
    )


def claim_demo_survey(request, user):
    """Переносит демо-тест гостя на пользователя. Возвращает survey_id или None."""
    demo_survey_id = request.session.get("demo_survey_id")
    if demo_survey_id:
        Survey.objects.filter(survey_id=demo_survey_id).update(id_staff=user.id_staff)
    for key in ("guest_staff_id", "demo_test_created", "demo_survey_id"):
        request.session.pop(key, None)
    request.session.modified = True
    return demo_survey_id


def bump_registration_counter(request):
    key = f"reg_ip_limit_{get_client_ip(request)}"
    cache.set(key, cache.get(key, 0) + 1, timeout=REG_COUNTER_TTL)


def _display_name(profile):
    return (profile.real_name or profile.display_name or profile.login)[:255] or None


def _extra(profile):
    return {
        "login": profile.login,
        "display_name": profile.display_name,
        "real_name": profile.real_name,
    }


def _create_user(request, profile):
    temp = resolve_temporary_user(request)
    username = unique_username(
        profile.login or profile.email.split("@")[0],
        exclude_pk=temp.pk if temp else None,
    )

    user = temp or AuthUser(id_staff=uuid.uuid4())
    user.username = username
    user.email = profile.email
    user.first_name = profile.first_name[:150]
    user.last_name = profile.last_name[:150]
    user.name = _display_name(profile)
    user.hash_user_id = None
    user.confirmed_user = True
    user.set_unusable_password()  # пароль можно задать позже через вход по ссылке
    user.save()

    ensure_free_subscription(user)
    log.info(
        f"YANDEX_OAUTH new user={user.username} staff={user.id_staff} "
        f"from_guest={bool(temp)}"
    )
    return user


def _link_or_create(request, profile):
    """Возвращает (user, created). Вызывается внутри transaction.atomic()."""
    account = (
        SocialAccount.objects.select_for_update()
        .select_related("user")
        .filter(provider=SocialAccount.PROVIDER_YANDEX, uid=profile.uid)
        .first()
    )
    if account:
        if not account.user.is_active:
            raise AccountError("inactive", "Этот аккаунт заблокирован. Напишите в поддержку.")
        account.email = profile.email
        account.extra_data = _extra(profile)
        account.last_login_at = timezone.now()
        account.save(update_fields=["email", "extra_data", "last_login_at"])
        return account.user, False

    if not profile.email:
        raise AccountError(
            "no_email",
            "В аккаунте Яндекса нет почты. Добавьте её в Яндекс ID или зарегистрируйтесь по email.",
        )

    user = AuthUser.objects.select_for_update().filter(email__iexact=profile.email).first()
    created = False

    if user:
        # Почта из Яндекса подтверждена — привязываем к существующему аккаунту
        if not user.is_active:
            raise AccountError("inactive", "Этот аккаунт заблокирован. Напишите в поддержку.")
        if SocialAccount.objects.filter(user=user, provider=SocialAccount.PROVIDER_YANDEX).exists():
            raise AccountError(
                "other_yandex_linked",
                "Этот email уже привязан к другому аккаунту Яндекса. "
                "Войдите тем аккаунтом или по email.",
            )
        if not user.confirmed_user:
            user.confirmed_user = True
            user.save(update_fields=["confirmed_user"])
        log.info(f"YANDEX_OAUTH linked existing user={user.username} by email")
    else:
        if not is_allowed_email(profile.email):
            raise AccountError("email_domain", "Регистрация с этого почтового домена не разрешена.")
        user = _create_user(request, profile)
        created = True

    SocialAccount.objects.create(
        user=user,
        provider=SocialAccount.PROVIDER_YANDEX,
        uid=profile.uid,
        email=profile.email,
        extra_data=_extra(profile),
    )
    return user, created


def login_or_register_with_yandex(request, profile):
    """
    Возвращает (user, created, demo_survey_id).
    demo_survey_id не None, если гостевой демо-тест перенесён на нового пользователя.
    """
    try:
        with transaction.atomic():
            user, created = _link_or_create(request, profile)
            demo_survey_id = claim_demo_survey(request, user) if created else None
    except IntegrityError:
        # Параллельный колбэк уже создал привязку — просто входим
        account = (
            SocialAccount.objects.select_related("user")
            .filter(provider=SocialAccount.PROVIDER_YANDEX, uid=profile.uid)
            .first()
        )
        if not account:
            raise
        log.warning(f"YANDEX_OAUTH race resolved uid={profile.uid}")
        return account.user, False, None

    if created:
        bump_registration_counter(request)
    return user, created, demo_survey_id
