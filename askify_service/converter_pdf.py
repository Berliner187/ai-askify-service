from django.contrib.staticfiles import finders

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .utils import get_year_now


class ConverterPDF:
    @staticmethod
    def get_survey_in_pdf(response, title, questions, sub_level=0):
        p = canvas.Canvas(response, pagesize=letter)

        font_path_medium = finders.find('fonts/Manrope-Medium.ttf')
        font_path_bold = finders.find('fonts/Manrope-ExtraBold.ttf')
        font_signature = finders.find('fonts/Unbounded-Medium.ttf')

        pdfmetrics.registerFont(TTFont('Manrope Medium', font_path_medium))
        pdfmetrics.registerFont(TTFont('Manrope Bold', font_path_bold))
        pdfmetrics.registerFont(TTFont('Unbounded Medium', font_signature))

        y = 700
        max_width = 400

        watermark_text = "ЛЕТУЧКА БЕСПЛАТНАЯ ВЕРСИЯ" if sub_level < 1 else None
        watermark_font = ("Manrope Bold", 16)
        watermark_color = colors.Color(0.7, 0.7, 0.7, alpha=0.15)  # Серый с прозрачностью
        watermark_rotation = 30  # Угол поворота
        watermark_spacing = 150  # Расстояние между водяными знаками

        def draw_watermark(canvas):
            """Функция для рисования водяных знаков"""
            canvas.saveState()
            canvas.setFillColor(watermark_color)
            canvas.setFont(*watermark_font)

            # Рисуем знаки под углом по всей странице
            canvas.rotate(watermark_rotation)
            text_width = canvas.stringWidth(watermark_text, *watermark_font)

            # Рассчитываем позиции для сетки водяных знаков
            for x in range(-600, 800, watermark_spacing):
                for y in range(-400, 900, watermark_spacing):
                    canvas.drawCentredString(x, y, watermark_text)

            canvas.restoreState()

        def check_new_page():
            nonlocal y
            if y < 50:
                # Если нужна новая страница - рисуем watermark на текущей
                if watermark_text:
                    draw_watermark(p)
                p.showPage()
                # На новой странице сразу рисуем watermark
                if watermark_text:
                    draw_watermark(p)
                p.setFont('Manrope Medium', 11)
                y = 700

        # На первой странице рисуем watermark сразу
        if watermark_text:
            draw_watermark(p)

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

        cnt_q_title = 0
        for question in questions:
            question_text = question['question']
            options = question['options']

            text_object = p.beginText(60, y)
            text_object.setFont('Manrope Medium', 12)

            cnt_q_title += 1

            for line in question_text.splitlines():
                words = line.split(' ')
                current_line = f"{cnt_q_title}. " + ''
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

        p.setFont('Unbounded Medium', 9)

        if sub_level < 1:
            p.drawString(60, 40, f"Сгенерировано в Летучке • {get_year_now()}")

        p.showPage()
        p.save()
        return response

