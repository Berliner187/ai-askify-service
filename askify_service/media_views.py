"""
media_views.py — журнал Летучки: /media/, /media/<slug>/, счётчик, RSS.

Лежит рядом с views.py. Тонкий слой над media_core: всё тяжёлое (разбор markdown)
кэшируется по mtime файла, список статей — на минуту в кэше Django.
"""
import os
from datetime import datetime
from xml.sax.saxutils import escape

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import BlogPost
from .views import check_legal_process, get_client_ip, get_username, get_year_now, get_view_count_text
from .media_core import (
    SLUG_RE, assemble, json_for_script, load_post, pick_related, plural, rubrics_of, ru_date,
)

BLOG_DIR = os.path.join(settings.BASE_DIR, "blog")
SITE = "https://letychka.ru"
LIST_CACHE_KEY = "media:list:v1"
LIST_CACHE_TTL = 60
DEFAULT_OG = f"{SITE}/static/letychka-banner-1703.webp"


def _q(value):
    from urllib.parse import quote
    return quote(value, safe="")


def _build_posts():
    """Публикация = запись в BlogPost + файл blog/<slug>.md. Файл — единственный источник текста."""
    items = []
    for bp in BlogPost.objects.all():
        path = os.path.join(BLOG_DIR, f"{bp.slug}.md")
        if not SLUG_RE.fullmatch(bp.slug) or not os.path.isfile(path):
            continue
        post = dict(load_post(path, os.path.getmtime(path)))
        post["date"] = post["meta_date"] or bp.created_at.date()
        post["views"] = bp.view_count
        items.append(post)
    return assemble(items)


def _posts():
    return cache.get_or_set(LIST_CACHE_KEY, _build_posts, LIST_CACHE_TTL)


def _ctx(request):
    username = get_username(request)
    return {"username": username if username else 0, "year": get_year_now()}


@check_legal_process
def media_index(request):
    posts = _posts()
    total = len(posts)
    canonical = request.build_absolute_uri(request.path)
    jsonld = json_for_script({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Журнал Летучки",
        "url": canonical,
        "inLanguage": "ru",
        "isPartOf": {"@type": "WebSite", "name": "Летучка", "url": SITE},
        "hasPart": [
            {"@type": "BlogPosting", "headline": p["title"], "url": f"{SITE}/media/{p['slug']}/", "datePublished": p["date_iso"]}
            for p in posts[:20]
        ],
    })
    context = {
        **_ctx(request),
        "posts": posts,
        "lead": posts[0] if posts else None,
        "total": total,
        "total_word": plural(total, ("материал", "материала", "материалов")),
        "updated_ru": ru_date(max((p["updated"] for p in posts), default=datetime.now().date())),
        "rubrics": rubrics_of(posts),
        "canonical_url": canonical,
        "jsonld": mark_safe(jsonld),
    }
    return render(request, "blog_index.html", context)


@check_legal_process
def blog_view(request, slug):
    """Имя маршрута остаётся прежним: media_view — старые {% url %} и ссылки не ломаются."""
    if not SLUG_RE.fullmatch(slug):
        return render(request, "404.html", status=404)

    posts = _posts()
    idx = next((i for i, p in enumerate(posts) if p["slug"] == slug), None)
    if idx is None:
        return render(request, "404.html", status=404)

    post = posts[idx]
    canonical = request.build_absolute_uri(request.path)
    og_image = post["cover"] if post["cover"].startswith("http") else (SITE + post["cover"] if post["cover"] else DEFAULT_OG)

    jsonld = json_for_script({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": post["title"],
                "description": post["description"],
                "image": og_image,
                "datePublished": post["date_iso"],
                "dateModified": post["updated_iso"],
                "inLanguage": "ru",
                "mainEntityOfPage": canonical,
                "articleSection": post["rubric"],
                "author": {"@type": "Organization", "name": "Летучка", "url": SITE},
                "publisher": {"@type": "Organization", "name": "Летучка", "url": SITE},
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Летучка", "item": SITE + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Журнал", "item": SITE + "/media/"},
                    {"@type": "ListItem", "position": 3, "name": post["title"], "item": canonical},
                ],
            },
        ],
    })

    # posts идут от новых к старым: «следующий» (новее) — слева по списку
    newer = posts[idx - 1] if idx > 0 else None
    older = posts[idx + 1] if idx + 1 < len(posts) else None

    context = {
        **_ctx(request),
        "post": post,
        "newer": newer,
        "older": older,
        "related": pick_related(posts, post),
        "views_text": get_view_count_text(post["views"]) if post["views"] else "",
        "canonical_url": canonical,
        "og_image": og_image,
        "share_url": _q(canonical),
        "share_text": _q(post["title"]),
        "quiz_json": mark_safe(json_for_script(post["quiz"])) if post["quiz"] else "",
        "quiz_word": plural(len(post["quiz"]), ("вопрос", "вопроса", "вопросов")),
        "jsonld": mark_safe(jsonld),
    }
    return render(request, "blog.html", context)


@csrf_exempt
@require_POST
def blog_view_beacon(request, slug):
    """Просмотр считаем отдельным запросом из JS (sendBeacon): боты без JS не накручивают, а отрисовка не ждёт запись в БД."""
    if SLUG_RE.fullmatch(slug):
        post = BlogPost.objects.filter(slug=slug).first()
        if post:
            post.add_unique_view(get_client_ip(request))
    return HttpResponse(status=204)


def media_rss(request):
    posts = _posts()[:30]
    items = "".join(
        "<item><title>{t}</title><link>{u}</link><guid>{u}</guid><pubDate>{d}</pubDate>"
        "<category>{c}</category><description>{s}</description></item>".format(
            t=escape(p["title"]), u=f"{SITE}/media/{p['slug']}/",
            d=p["date"].strftime("%a, %d %b %Y 00:00:00 +0300"), c=escape(p["rubric"]), s=escape(p["description"]),
        )
        for p in posts
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Журнал Летучки</title><link>{SITE}/media/</link>"
        "<description>Разборы и приёмы для тех, кто готовит тесты и проверяет знания</description>"
        f"<language>ru</language>{items}</channel></rss>"
    )
    return HttpResponse(xml, content_type="application/rss+xml; charset=utf-8")
