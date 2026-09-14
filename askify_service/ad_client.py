import requests
import time
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class AdleanClient:
    def __init__(self):
        self.url = "https://api.adlean.pro/engine/send_message"
        self.api_key = settings.ADLEAN_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def send_event(self, text, role, chat_id, user_id, user_type="non_authorized"):
        payload = {
            "text": text,
            "role": role,
            "timestamp": int(time.time()),
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "user_type": user_type,
            "user_metadata": {
                "lang": "ru"
            }
        }
        try:
            response = self.session.post(self.url, json=payload, timeout=3.0)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Adlean API Error: {e}")
        return None
