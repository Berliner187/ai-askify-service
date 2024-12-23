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
    "meta-llama/llama-3.1-405b-instruct:free",
    "meta-llama/llama-3.2-90b-vision-instruct:free",
    "meta-llama/llama-3.1-70b-instruct:free",
    "liquid/lfm-40b:free",
    "google/gemini-flash-1.5-8b-exp",
    "qwen/qwen-2-7b-instruct:free",
    "openchat/openchat-7b:free"
]

SUBSCRIPTION_TIERS = {
    0: "Стартовый",
    1: "Стандартный",
    2: "Премиум",
    4: "Ультра",
    5: "Enterprise"
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

# PLANS = {
#     "starter": Plan(name="Стартовый", token_limit=10_000, duration=timedelta(days=7), is_paid=False),
#     "standard": Plan(name="Стандартный", token_limit=50_000, duration=timedelta(days=30), is_paid=True),
#     "premium": Plan(name="Премиум", token_limit=150_000, duration=timedelta(days=30), is_paid=True),
#     "ultra": Plan(name="Ультра", token_limit=500_000, duration=timedelta(days=30), is_paid=True),
# }
