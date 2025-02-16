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

        y = 700
        max_width = 400

        def check_new_page():
            nonlocal y
            if y < 50:
                p.showPage()
                p.setFont('Manrope Medium', 11)
                y = 700

        p.setFont('Manrope Bold', 14)
        text_object = p.beginText(60, y+40)
        p.setFont('Manrope Medium', 11)

        for line in title.splitlines():
            words = line.split(' ')
            current_line = ''
            for word in words:
                if p.stringWidth(current_line + word + ' ', 'Manrope Bold', 16) < max_width:
                    current_line += word + ' '
                else:
                    text_object.textLine(current_line)
                    current_line = word + ' '
                    y -= 15
                    check_new_page()
            text_object.textLine(current_line)

        p.drawText(text_object)
        y -= 20

        for question in questions:
            question_text = question['question']
            options = question['options']

            text_object = p.beginText(60, y)
            text_object.setFont('Manrope Medium', 12)

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
                        check_new_page()
                text_object.textLine(current_line)

            p.drawText(text_object)
            y -= 20

            count = 1
            for option in options:
                p.drawString(60, y, f"{count}) {option}")
                y -= 15
                count += 1
                check_new_page()

            y -= 10

        p.showPage()
        p.save()
        return response

