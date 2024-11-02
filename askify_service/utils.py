import json
import datetime

import openai
import requests

from django.contrib.staticfiles import finders

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


class ManageConfidentFields:
    def __init__(self, filename):
        self.filename = filename

    def __read_confident_file(self):
        with open(f'./askify_app/{self.filename}') as config_file:
            return json.load(config_file)

    def get_confident_key(self, keyname):
        _config = self.__read_confident_file()
        return _config[keyname]


class AccessControlUser:
    @staticmethod
    def validate_text(text):
        """ Проверка допуска к генерации текста от пользователя """
        # if len(text) <
        pass


class GenerationModelsControl:
    def __init__(self):
        pass

    @staticmethod
    def __get_confidential_key(key_name):
        manage_confident_fields = ManageConfidentFields("config.json")
        return manage_confident_fields.get_confident_key(key_name)

    def get_service_0001(self, text_from_user):

        client = openai.OpenAI(
            api_key=self.__get_confidential_key("api_openai"),
            base_url="https://glhf.chat/api/openai/v1",
        )

        completion = client.chat.completions.create(
            model=f"hf:{self.__get_confidential_key('llm_model_name')}",
            messages=[
                {
                    "role": "system",
                    "content": f"{self.__get_confidential_key('system_prompt')}"
                },
                {
                    "role": "user",
                    "content": f"{text_from_user}{self.__get_confidential_key('user_prompt')}"
                }
            ]
        )

        generated_text = completion.choices[0].message.content
        cleaned_generated_text = generated_text.replace("json", "").replace("`", "")

        return cleaned_generated_text

    def response_service_0002(self, text_from_user):
        messages = [
            {
                "role": "system",
                "content": f"{self.__get_confidential_key('system_prompt')}"
            },
            {
                "role": "user",
                "content": f"{text_from_user}{self.__get_confidential_key('user_prompt')}"
            }
        ]

        url = "https://api.arliai.com/v1/chat/completions"
        payload = json.dumps({
            "model": "Meta-Llama-3.1-8B-Instruct",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
            "stream": False
        })
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.__get_confidential_key("api_arliai")}'
        }
        response = requests.post(url, headers=headers, data=payload)
        return response.json()

    def get_service_0002(self, text_from_user):
        completion = self.response_service_0002(text_from_user)

        assistant_response = completion['choices'][0]['message']['content']
        print("Assistant's response:", assistant_response)
        return assistant_response


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


def get_year_now():
    return datetime.datetime.now().strftime("%Y")
