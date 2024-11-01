import json
import openai

import datetime


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

    def get_service_0001(self, text_from_user):
        manage_confident_fields = ManageConfidentFields("config.json")

        client = openai.OpenAI(
            api_key=manage_confident_fields.get_confident_key("api_openai"),
            base_url="https://glhf.chat/api/openai/v1",
        )

        completion = client.chat.completions.create(
            model=f"hf:{manage_confident_fields.get_confident_key('llm_model_name')}",
            messages=[
                {
                    "role": "system",
                    "content": f"{manage_confident_fields.get_confident_key('system_prompt')}"
                },
                {
                    "role": "user",
                    "content": f"{text_from_user}{manage_confident_fields.get_confident_key('user_prompt')}"
                }
            ]
        )

        generated_text = completion.choices[0].message.content
        cleaned_generated_text = generated_text.replace("json", "").replace("`", "")

        return cleaned_generated_text


def get_year_now():
    return datetime.datetime.now().strftime("%Y")
