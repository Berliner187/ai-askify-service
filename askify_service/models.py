from django.db import models
import json
import uuid


class Survey(models.Model):
    survey_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=255)
    questions = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    def get_questions(self):
        return json.loads(self.questions)

    def __str__(self):
        return self.title


class UserAnswers(models.Model):
    survey_id = models.UUIDField()  # Поле для общего survey_id
    selected_answer = models.CharField(max_length=255)
    scored_points = models.IntegerField()
    total_points = models.IntegerField()
    user_answers = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Answers for survey {self.survey_id}"

    # class Meta:
    #     db_table = "user_answers"
