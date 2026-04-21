from django.contrib.staticfiles import finders

from io import BytesIO
from django.template.loader import get_template
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa
from pypdf import PdfReader, PdfWriter
from django.http import HttpResponse

from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import math

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


class PDFGenerator:

    @staticmethod
    def _create_watermark_pdf():
        """
        Создает PDF со стильным, продающим вотермарком (Product-Led Growth).
        """
        buffer = BytesIO()
        p = canvas.Canvas(buffer)

        font_path = finders.find('fonts/Unbounded-Medium.ttf')
        pdfmetrics.registerFont(TTFont('Unbounded-Brutal', font_path))
        width, height = p._pagesize

        p.saveState()
        p.setFont('Unbounded-Brutal', 36)

        p.setFillColor(colors.Color(150 / 255, 150 / 255, 170 / 255, alpha=0.1))
        p.translate(width / 2, height / 2)
        p.rotate(45)
        p.drawCentredString(0, 0, "СГЕНЕРИРОВАНО НА LETYCHKA.RU")
        p.restoreState()

        p.saveState()
        p.setFont('Unbounded-Brutal', 10)
        p.setFillColor(colors.Color(0, 0, 0, alpha=0.5))

        cta_text = "[ создайте свой тест или шпору с помощью ИИ – letychka.ru ]"

        p.drawCentredString(width / 2, 70, cta_text)
        p.restoreState()

        p.save()
        buffer.seek(0)
        return buffer

    @staticmethod
    def _render_content_pdf(template_path, context_dict={}):
        """
        Рендерит основной контент из HTML в PDF В ПАМЯТИ.
        """
        template = get_template(template_path)
        context_dict['font_path_medium'] = finders.find('fonts/Manrope-Medium.ttf')
        context_dict['font_path_bold'] = finders.find('fonts/Manrope-ExtraBold.ttf')
        context_dict['font_path_signature'] = finders.find('fonts/Unbounded-Medium.ttf')

        html = template.render(context_dict)
        result = BytesIO()

        pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
        if pdf.err:
            print(f"PISA ERROR: {pdf.err}")
            return None

        result.seek(0)
        return result

    @staticmethod
    def generate_from_survey(survey, subscription_level):
        """
        Главная функция: рендерит контент, рендерит вотермарк, склеивает их.
        """
        context = {
            'title': survey.title,
            'questions': survey.get_questions(),
            'creation_date': survey.created_at.strftime('%d.%m.%Y'),
            'survey_id': survey.survey_id,
        }

        # 1. Создаем PDF с контентом
        content_pdf_buffer = PDFGenerator._render_content_pdf('test_template.html', context)
        if not content_pdf_buffer:
            return HttpResponse("Ошибка генерации контента PDF", status=500)

        output_buffer = BytesIO()
        writer = PdfWriter()
        content_reader = PdfReader(content_pdf_buffer)

        if subscription_level < 1:
            writer.encrypt("", permissions_flag=0b000000000000000000001111110100)

            watermark_pdf_buffer = PDFGenerator._create_watermark_pdf()
            watermark_reader = PdfReader(watermark_pdf_buffer)
            watermark_page = watermark_reader.pages[0]

            for page in content_reader.pages:
                page.merge_page(watermark_page, over=True)
                writer.add_page(page)
        else:
            for page in content_reader.pages:
                writer.add_page(page)

        writer.write(output_buffer)
        pdf_data = output_buffer.getvalue()

        response = HttpResponse(pdf_data, content_type='application/pdf')
        safe_title = "".join(c for c in survey.title if c.isalnum() or c in (" ", "_")).rstrip()
        response['Content-Disposition'] = f'attachment; filename="{safe_title}.pdf"'
        return response
