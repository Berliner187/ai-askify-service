import uuid
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from askify_service.models import Survey

User = get_user_model()
ARCHIVE_EMAIL = "letychka-archive@gmail.com"

class Command(BaseCommand):
    help = "Переносит тесты мертвых гостей в архив и удаляет гостевые аккаунты"

    def handle(self, *args, **options):
        now = timezone.now()
        
        archive_user, _ = User.objects.get_or_create(
            email=ARCHIVE_EMAIL,
            defaults={
                "username": "letychka-archive",
                "name": "Архив Летучки",
                "confirmed_user": True,
                "is_active": True,
                "id_staff": uuid.uuid4(),
            }
        )

        hour_ago = now - timezone.timedelta(hours=1)
        guests = User.objects.filter(
            date_joined__lte=hour_ago,
            username__startswith="guest_",
            test_balance=0
        ).exclude(email=ARCHIVE_EMAIL)

        guest_staff_ids = list(guests.values_list("id_staff", flat=True))

        if not guest_staff_ids:
            self.stdout.write(self.style.SUCCESS("Нет мертвых гостей для зачистки."))
            return

        updated_surveys = Survey.objects.filter(id_staff__in=guest_staff_ids).update(
            id_staff=archive_user.id_staff
        )

        deleted_users, _ = guests.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Зачистка завершена: перенесено {updated_surveys} тестов, удалено {deleted_users} гостей."
            )
        )
