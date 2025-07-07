from django.contrib.staticfiles import finders

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from .utils import get_year_now

import qrcode

from io import BytesIO
import random


def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    stream = BytesIO()
    img.save(stream, format='PNG')
    stream.seek(0)
    return ImageReader(stream)


class ConverterPDF:
    @staticmethod
    def get_survey_in_pdf(response, title, questions, sub_level=0, survey_id=None):
        p = canvas.Canvas(response, pagesize=letter)

        p.setTitle(title[:30])
        p.setAuthor("letychka.ru")
        p.setSubject("Автоматически сгенерированный тест")
        p.setKeywords(f"{title[:30]}, создать тест, создать тест по тексту онлайн, ИИ для создания тестов бесплатно, составить тест по тексту онлайн, создать тест онлайн, летучка создать тест, по тексту онлайн, pdf")

        font_path_medium = finders.find('fonts/Manrope-Medium.ttf')
        font_path_bold = finders.find('fonts/Manrope-ExtraBold.ttf')
        font_signature = finders.find('fonts/Unbounded-Medium.ttf')

        pdfmetrics.registerFont(TTFont('Manrope Medium', font_path_medium))
        pdfmetrics.registerFont(TTFont('Manrope Bold', font_path_bold))
        pdfmetrics.registerFont(TTFont('Unbounded Medium', font_signature))

        y = 700
        max_width = 400

        watermark_text = "Создано бесплатно на letychka.ru" if sub_level < 1 else None
        watermark_font = ("Manrope Bold", 16)
        watermark_color = colors.Color(0.7, 0.7, 0.7, alpha=0.2)
        watermark_rotation = 30
        watermark_spacing = 300

        def draw_watermark(canvas):
            """Функция для рисования водяных знаков"""
            qr_img = generate_qr_code(f"https://letychka.ru/c/{survey_id}?utm_source=from_self_pdf_{survey_id}")
            canvas.drawImage(qr_img, x=520, y=700, width=64, height=64, preserveAspectRatio=True, mask='auto')

            canvas.saveState()
            canvas.setFillColor(watermark_color)
            canvas.setFont(*watermark_font)

            # Рисуем знаки под углом по всей странице
            canvas.rotate(random.randint(watermark_rotation-10, watermark_rotation+10))
            text_width = canvas.stringWidth(watermark_text, *watermark_font)

            # Рассчитываем позиции для сетки водяных знаков
            for x in range(-600, 1200, watermark_spacing):
                for y in range(-400, 1200, 100+random.randint(0, 50)):
                    canvas.drawCentredString(x, y, watermark_text)

            canvas.restoreState()

        if watermark_text:
            draw_watermark(p)

        def check_new_page():
            nonlocal y
            if y < 50:
                p.showPage()
                p.setFont('Manrope Medium', 11)
                y = 700

                if watermark_text:
                    draw_watermark(p)

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

        if sub_level < 1:
            p.setFont('Unbounded Medium', 10)
            p.drawString(60, 40, f"Сгенерировано в Летучке • {get_year_now()}")
            p.setFont('Manrope Medium', 10)
            p.drawString(60, 20, f"Сгенерировано автоматически. Подробнее: https://letychka.ru")

        p.showPage()
        p.save()
        return response

