from django.contrib.staticfiles import finders

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .utils import get_year_now


class ConverterPDF:
    @staticmethod
    def get_survey_in_pdf(response, title, questions):
        p = canvas.Canvas(response, pagesize=letter)

        font_path_medium = finders.find('fonts/Manrope-Medium.ttf')
        font_path_bold = finders.find('fonts/Manrope-ExtraBold.ttf')
        font_signature = finders.find('fonts/Unbounded-Medium.ttf')

        pdfmetrics.registerFont(TTFont('Manrope Medium', font_path_medium))
        pdfmetrics.registerFont(TTFont('Manrope Bold', font_path_bold))
        pdfmetrics.registerFont(TTFont('Unbounded Medium', font_signature))

        p.setFont('Manrope Bold', 16)
        p.drawString(80, 750, f"{title}")

        p.setFont('Manrope Medium', 11)

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