"""
askify_service/management/commands/traffic_purge.py

Ротация TrafficLog: удаляет хиты старше N дней пачками, чтобы не держать
долгую блокировку и не раздувать WAL.

Страница «Трафик-контрол» читает только последние 8 дней (сегодня, вчера,
тот же день неделю назад). Всё, что старше, никто не читает.

    python manage.py traffic_purge                # оставить 30 дней
    python manage.py traffic_purge --days 14
    python manage.py traffic_purge --dry-run      # только посчитать

Cron, раз в сутки в 04:40:
    40 4 * * * cd /path/to/project && ./venv/bin/python manage.py traffic_purge
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from askify_service.models import TrafficLog


class Command(BaseCommand):
    help = "Удаляет записи TrafficLog старше N дней"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--batch", type=int, default=5000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        if o["days"] < 8:
            self.stderr.write("Меньше 8 дней нельзя: страница сравнивает с тем же днём неделю назад.")
            return
        edge = timezone.now() - timedelta(days=o["days"])
        qs = TrafficLog.objects.filter(created_at__lt=edge)
        total = qs.count()
        self.stdout.write(f"Старше {o['days']} дней: {total} записей")
        if o["dry_run"] or not total:
            return

        deleted, t0 = 0, time.monotonic()
        while True:
            ids = list(qs.order_by("id").values_list("id", flat=True)[: o["batch"]])
            if not ids:
                break
            deleted += TrafficLog.objects.filter(id__in=ids).delete()[0]
            time.sleep(0.05)  # дать воздуха живым запросам

        # вернуть место под новые строки и обновить статистику планировщика
        with connection.cursor() as cur:
            cur.execute(f"VACUUM (ANALYZE) {TrafficLog._meta.db_table}")
        self.stdout.write(self.style.SUCCESS(
            f"Удалено {deleted} за {time.monotonic() - t0:.1f} с, VACUUM ANALYZE выполнен"
        ))
