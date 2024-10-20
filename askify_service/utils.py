import json


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
        """ Проверка пропуска текста от пользователя """
        # if len(text) <
        pass
