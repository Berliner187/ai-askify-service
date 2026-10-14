import os
from django.core.cache import cache

BOT_KEYWORDS = [
    'bot', 'spider', 'crawler', 'python-requests', 'httpx', 'curl', 'wget', 
    'go-http-client', 'headless', 'postman', 'aiohttp', 'yandexbot', 
    'googlebot', 'bingbot', 'semrush', 'ahrefs', 'dotbot', 'petalbot'
]

def get_real_client_ip(request) -> str:
    """Извлечение реального IP за прокси Nginx / Cloudflare."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_CF_CONNECTING_IP') or request.META.get('REMOTE_ADDR') or "127.0.0.1"
    return ip

def is_bot_request(request, ip: str, ua: str) -> bool:
    """Комбинированный анализ бота."""
    ua_lower = ua.lower()
    
    if not ua or any(keyword in ua_lower for keyword in BOT_KEYWORDS):
        return True
    
    if cache.get(f"honeypot_bot:{ip}"):
        return True
        
    return False

def log_traffic(request, page_name: str = "general"):
    """
    Вызывается одной строкой в любых вьюхах:
    log_traffic(request, "Главная")
    log_traffic(request, "take_test")
    """
    try:
        from .models import TrafficLog
        
        ip = get_real_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')[:250]
        
        is_bot = is_bot_request(request, ip, ua)
        
        TrafficLog.objects.create(
            ip=ip,
            path=str(page_name)[:140],
            user_agent=ua,
            is_bot=is_bot
        )
    except Exception as e:
        pass
