"""
management/commands/db_snapshot.py

Снимок базы для админки. Положить в askify_service/management/commands/
и запускать по cron раз в сутки (или чаще):

    15 4 * * * cd /path/to/project && ./venv/bin/python manage.py db_snapshot
"""
from django.core.management.base import BaseCommand

from askify_service.models import DbSnapshot


class Command(BaseCommand):
    help = "Снимает статистику PostgreSQL и сохраняет в DbSnapshot"

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=90, help="Сколько снимков хранить")

    def handle(self, *args, **opts):
        snap = DbSnapshot.take(keep=opts["keep"])
        self.stdout.write(self.style.SUCCESS(
            f"Снимок #{snap.id}: {snap.db_size / 1024 / 1024:.1f} MB, {snap.collect_ms} ms"
        ))
