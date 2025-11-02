from django.core.management.base import BaseCommand
from askify_service.models import Survey, Question
import json


class Command(BaseCommand):
    help = 'Populates the Question model from existing Survey JSON data'

    def handle(self, *args, **options):
        self.stdout.write('Starting question population...')
        Question.objects.all().delete()

        for survey in Survey.objects.all():
            try:
                questions_data = survey.get_questions()
                for q_data in questions_data:
                    Question.objects.create(
                        survey=survey,
                        text=q_data['question'],
                        options=q_data['options'],
                        correct_answer=q_data['correct_answer']
                    )
            except (json.JSONDecodeError, TypeError, KeyError):
                self.stderr.write(f'Could not process survey {survey.id}')

        self.stdout.write(self.style.SUCCESS('Successfully populated questions!'))
