PAYMENT_STATUSES = {
    'NEW': 'MAPI получил запрос Init. После этого он создает новый платеж со статусом NEW и возвращает его идентификатор в параметре PaymentId, а также ссылку на платежную форму в параметре PaymentURL.',
    'FORM_SHOWED': 'Мерчант перенаправил клиента на страницу платежной формы PaymentURL и страница загрузилась у клиента в браузере.',
    'AUTHORIZING': 'Платеж обрабатывается MAPI и платежной системой.',
    '3DS_CHECKING': 'Платеж проходит проверку 3D-Secure.',
    '3DS_CHECKED': 'Платеж успешно прошел проверку 3D-Secure.',
    'AUTHORIZED': 'Платеж авторизован, деньги заблокированы на карте клиента.',
    'CONFIRMING': 'Подтверждение платежа обрабатывается MAPI и платежной системой.',
    'CONFIRMED': 'Платеж подтвержден, деньги списаны с карты клиента.',
    'REVERSING': 'Мерчант запросил отмену авторизованного, но еще неподтвержденного платежа. Возврат обрабатывается MAPI и платежной системой.',
    'PARTIAL_REVERSED': 'Частичный возврат по авторизованному платежу завершился успешно.',
    'REVERSED': 'Полный возврат по авторизованному платежу завершился успешно.',
    'REFUNDING': 'Мерчант запросил отмену подтвержденного платежа. Возврат обрабатывается MAPI и платежной системой.',
    'PARTIAL_REFUNDED': 'Частичный возврат по подтвержденному платежу завершился успешно.',
    'REFUNDED': 'Полный возврат по подтвержденному платежу завершился успешно.',
    'CANCELED': 'Мерчант отменил платеж.',
    'DEADLINE_EXPIRED': 'Клиент не завершил платеж в срок жизни ссылки на платежную форму PaymentURL. 2. Платеж не прошел проверку 3D-Secure в срок.',
    'REJECTED': 'Банк отклонил платеж.',
    'AUTH_FAIL': 'Платеж завершился ошибкой или не прошел проверку 3D-Secure.'
}

MODEL_NAMES = [
    "google/gemini-2.0-flash-exp:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-4-maverick:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "deepseek/deepseek-chat:free",
    "qwen/qwq-32b:free",
    "deepseek/deepseek-v3-base:free"
]

# --- AI provider pricing & presets (используется в модалке «Здоровье AI-провайдеров») ---
# Стоимость указана в USD за 1 000 000 токенов (blended, ориентировочно).
AI_MODEL_PRICING = {
    "gpt-4o-mini": 0.25,
    "gpt-4o": 5.00,
    "gpt-4.1-mini": 0.40,
    "gpt-4.1": 4.50,
    "gpt-4-turbo": 15.00,
    "gpt-3.5-turbo": 1.00,
    "o1-mini": 2.50,
    "o3-mini": 2.20,
    "gemini-2.5-flash": 0.30,
    "gemini-2.0-flash": 0.20,
    "gemini-1.5-flash": 0.15,
    "gemini-1.5-pro": 2.50,
    "gemini-3.1-pro": 3.50,
    "claude-3-5-haiku": 1.00,
    "claude-3-5-sonnet": 6.00,
    "claude-3-7-sonnet": 6.00,
    "claude-opus": 10.00,
    "deepseek-chat": 0.20,
    "deepseek-reasoner": 0.25,
    "deepseek-v4-flash": 0.20,
    "deepseek-v4-pro": 2.00,
}

AI_PROVIDER_DEFAULT_PRICE = {
    "openai": 0.60,
    "azure": 0.60,
    "openrouter": 0.50,
    "gemini": 0.40,
    "google": 0.40,
    "anthropic": 9.00,
    "deepseek": 0.60,
    "together": 0.50,
    "github": 0.50,
}

# Пресеты для формы добавления ключа: base_url + типовые модели.
AI_PROVIDER_PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["openai/gpt-4o-mini", "google/gemini-2.0-flash-001", "anthropic/claude-3.5-sonnet"],
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": ["gemini-2.0-flash", "gemini-1.5-flash"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "models": ["meta-llama/Llama-4-Maverick-17B-128E-Instruct-Turbo"],
    },
    "github": {
        "base_url": "https://models.github.ai/inference",
        "models": ["openai/gpt-4o", "openai/gpt-4o-mini"],
    },
    "custom": {"base_url": "", "models": []},
}

AI_KEY_PURPOSES = ["SURVEY", "FEEDBACK", "AD", "CHAT", "EMBEDDING", "OTHER"]


SUBSCRIPTION_TIERS = {
    0: "Стартовый",
    1: "Стандартный",
    2: "Премиум",
    3: "Ультра",
    4: "Стандартный Год",
    5: "Премиум Год",
    99: "Лайтовый",
}

ALLOWED_DOMAINS = [
    'gmail.com',
    'yandex.ru',
    'ya.ru',
    'yandex.com',
    'mail.ru',
    'inbox.ru',
    'rambler.ru',
    'outlook.com',
    'icloud.com',
    'list.ru',
    'bk.ru',
    'inbox.ru',
    'rambler.ru',
    'hotmail.ru',
    'tut.by'
]
