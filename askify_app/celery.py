import os
from dotenv import load_dotenv
from celery import Celery

from askify_app.settings import BASE_DIR
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'askify_app.settings')

app = Celery('askify_app')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()
