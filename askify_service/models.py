import datetime

from django.db import models
import json
import uuid

from django.http import HttpResponse
from django.contrib.staticfiles import finders
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .utils import *


class Survey(models.Model):
    survey_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(max_length=255)
    questions = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    def get_questions(self):
        return json.loads(self.questions)

    def __str__(self):
        return self.title

    def generate_pdf(self):
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="тест.pdf"'

        p = canvas.Canvas(response, pagesize=letter)

        font_path_medium = finders.find('fonts/Manrope-Medium.ttf')
        font_path_bold = finders.find('fonts/Manrope-ExtraBold.ttf')
        font_signature = finders.find('fonts/Unbounded-Medium.ttf')

        pdfmetrics.registerFont(TTFont('Manrope Medium', font_path_medium))
        pdfmetrics.registerFont(TTFont('Manrope Bold', font_path_bold))
        pdfmetrics.registerFont(TTFont('Unbounded Medium', font_signature))

        p.setFont('Manrope Bold', 16)
        p.drawString(80, 750, f"{self.title}")

        p.setFont('Manrope Medium', 11)

        questions = self.get_questions()
        y = 700

        for question in questions:
            question_text = question['question']
            options = question['options']

            text_object = p.beginText(80, y)
            text_object.setFont('Manrope Medium', 11)
            text_object.setTextOrigin(80, y)

            max_width = 400

            for line in question_text.splitlines():
                words = line.split(' ')
                current_line = ''
                for word in words:
                    if p.stringWidth(current_line + word + ' ', 'Manrope Medium', 11) < max_width:
                        current_line += word + ' '
                    else:
                        text_object.textLine(current_line)
                        current_line = word + ' '
                        y -= 15
                text_object.textLine(current_line)

            p.drawText(text_object)
            y -= 20

            count = 1
            for option in options:
                p.drawString(100, y, f"{count}) {option}")
                y -= 15
                count += 1

            y -= 10

        p.setFont('Unbounded Medium', 7)
        p.drawString(80, 40, f"Created by Летучка, {get_year_now()}")

        p.showPage()
        p.save()
        return response


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
