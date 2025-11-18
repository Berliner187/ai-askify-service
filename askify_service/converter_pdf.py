from django.contrib.staticfiles import finders

from io import BytesIO
from django.template.loader import get_template
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa
from django.http import HttpResponse

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
    def render_to_pdf(template_path, context_dict={}):
        template = get_template(template_path)

        context_dict['font_path_medium'] = finders.find('fonts/Manrope-Medium.ttf')
        context_dict['font_path_bold'] = finders.find('fonts/Manrope-ExtraBold.ttf')
        context_dict['font_path_signature'] = finders.find('fonts/Unbounded-Medium.ttf')

        html = template.render(context_dict)
        result = BytesIO()

        pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)

        if not pdf.err:
            return result.getvalue()
        return None

    @staticmethod
    def generate_from_survey(survey, subscription_level):
        context = {
            'title': survey.title,
            'questions': survey.get_questions(),
            'watermark': subscription_level < 1,
            'creation_date': survey.created_at.strftime('%d.%m.%Y'),
            'survey_id': survey.survey_id,
        }

        pdf_data = PDFGenerator.render_to_pdf('test_template.html', context)

        if pdf_data:
            response = HttpResponse(pdf_data, content_type='application/pdf')
            safe_title = "".join(c for c in survey.title if c.isalnum() or c in (" ", "_")).rstrip()
            response['Content-Disposition'] = f'attachment; filename="{safe_title}.pdf"'
            return response

        return HttpResponse("Ошибка генерации PDF", status=500)

