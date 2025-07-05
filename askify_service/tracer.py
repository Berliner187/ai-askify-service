import logging
import requests
from threading import Thread

from django.conf import settings

from askify_app.settings import DEBUG


WARNING_SYMBOL = "🚧"
ERROR_SYMBOL = "❌"
CRITICAL_SYMBOL = "⚡️☠️"
CONFIRM_SYMBOL = "✅"


class TelegramHandler(logging.Handler):
    """
        Кастомный обработчик для отправки логов в Telegram.
        Работает в отдельном потоке, чтобы не блокировать основной процесс.
    """

    def __init__(self):
        super().__init__()
        self.token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        self.chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', None)

    def emit(self, record):
        if DEBUG:
            return
        if not self.token or not self.chat_id or record.levelno < logging.WARNING:
            return

        log_entry = self.format(record)

        if record.levelno == logging.CRITICAL:
            icon = CRITICAL_SYMBOL
        elif record.levelno == logging.ERROR:
            icon = ERROR_SYMBOL
        elif record.levelno == logging.WARNING:
            icon = WARNING_SYMBOL
        else:
            icon = ""

        message = f"{icon} <b>{record.levelname}</b>\n\n"
        message += f"<pre>{log_entry}</pre>"

        thread = Thread(target=self.send_message, args=(message,))
        thread.start()

    def send_message(self, message):
        """ Отправка сообщений в дежурный бот. Вызывается в отдельном потоке."""
        url = f'https://api.telegram.org/bot{self.token}/sendMessage'
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"CRITICAL: Failed to send log to Telegram. Error: {e}")
