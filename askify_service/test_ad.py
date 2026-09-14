import os
import django

# Инициализируем настройки Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'askify_project.settings') # ЗАМЕНИ на свое имя проекта
django.setup()

from askify_service.ad_client import AdleanClient
import json

def test_api():
    client = AdleanClient()
    
    print("--- ТЕСТ 1: СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ---")
    res_user = client.send_event(
        text="Составь тест по истории России про Петра 1",
        role="user",
        chat_id="test_chat_123",
        user_id="test_user_123",
        user_type="non_authorized"
    )
    print(f"Ответ API (User): {json.dumps(res_user, indent=2, ensure_ascii=False)}")

    print("\n--- ТЕСТ 2: ОТВЕТ АССИСТЕНТА (Ждем рекламу) ---")
    res_assistant = client.send_event(
        text="Вот твой тест по истории: 1. В каком году Петр 1 стал царем? варианты: 1682, 1700...",
        role="assistant",
        chat_id="test_chat_123",
        user_id="test_user_123",
        user_type="non_authorized"
    )
    print(f"Ответ API (Assistant): {json.dumps(res_assistant, indent=2, ensure_ascii=False)}")

if __name__ == "__main__":
    test_api()
