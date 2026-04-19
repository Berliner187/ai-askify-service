import logging
import requests
from threading import Thread
from django.conf import settings


WARNING_SYMBOL = "🚧"
ERROR_SYMBOL = "❌"
CRITICAL_SYMBOL = "⚡️☠️"
CONFIRM_SYMBOL = "✅"


class MaxHandler(logging.Handler):
    """
    Новый хендлер для МАКС.
    Заменяет старый TelegramHandler.
    """

    def __init__(self):
        super().__init__()
        self.token = getattr(settings, 'MAX_BOT_TOKEN', None)
        self.user_id = getattr(settings, 'MAX_ALERT_USER_ID', None)
        self.base_url = "https://platform-api.max.ru/messages"

    def emit(self, record):
        # Если нет токена или ID — выходим молча
        if not self.token or not self.user_id:
            return

        try:
            log_entry = self.format(record)

            icon = ""
            if record.levelno == logging.CRITICAL:
                icon = CRITICAL_SYMBOL
            elif record.levelno == logging.ERROR:
                icon = ERROR_SYMBOL
            elif record.levelno == logging.WARNING:
                icon = WARNING_SYMBOL

            # Собираем месседж. Макс жрет HTML, судя по твоим тестам.
            message = f"{icon} <b>{record.levelname}</b>\n\n<pre>{log_entry}</pre>"

            # Запускаем в фоне
            Thread(target=self.send_message, args=(message,), daemon=True).start()
        except Exception:
            self.handleError(record)

    def send_message(self, message):
        # Тот самый URL с квери-параметром, который у тебя сработал
        url = f"{self.base_url}?user_id={self.user_id}"

        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }

        payload = {
            "text": message,
            "format": "html"
        }

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code != 200:
                # Если сервак Макса выплюнул ошибку — пишем в консоль
                print(f"MAX_API_ERROR: {r.status_code} - {r.text}")
        except Exception as e:
            print(f"MAX_SEND_FAILED: {e}")
