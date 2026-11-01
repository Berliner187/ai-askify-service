"""
media_core.py — разбор статей журнала из .md. Чистый Python, без Django.

Формат файла blog/<slug>.md. Всё необязательно: старые статьи («# Заголовок» первой строкой) работают как есть.

    title: Как сделать тест по тексту за 5 минут
    description: Описание для поисковиков, до 160 знаков
    lead: Короткий вводный абзац для списка и шапки статьи
    rubric: Методика
    date: 2026-10-12
    updated: 2026-10-30
    cover: /static/blog_img/cover-01.png

    # Как сделать тест по тексту        <- H1 берётся как заголовок и убирается из тела

    Текст статьи...

    ::: quiz
    ? Вопрос
    - Неверный вариант
    + Верный вариант
    - Ещё вариант
    > Пояснение, которое покажем после ответа
    :::
"""
import html
import json
import re
from datetime import date, datetime
from functools import lru_cache

import markdown
from markdown.extensions.toc import slugify_unicode

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
H1_RE = re.compile(r"<h1[^>]*>.*?</h1>\s*", re.S)
TABLE_RE = re.compile(r"(<table>.*?</table>)", re.S)
FIRST_P_RE = re.compile(r"<p>(.*?)</p>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img(?![^>]*\bloading=)")
QUIZ_RE = re.compile(r"^:::[ \t]*quiz[ \t]*\n(.*?)^:::[ \t]*$", re.S | re.M)
DEFAULT_RUBRIC = "Статьи"
WORDS_PER_MIN = 190

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн",
                "июл", "авг", "сен", "окт", "ноя", "дек"]


def ru_date(d):
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def ru_date_short(d):
    return f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year}"


def plural(n, forms):
    """plural(3, ('материал', 'материала', 'материалов'))"""
    n = abs(int(n))
    a, b = n % 100, n % 10
    if 11 <= a <= 14:
        return forms[2]
    if b == 1:
        return forms[0]
    if 2 <= b <= 4:
        return forms[1]
    return forms[2]


def _make_md():
    return markdown.Markdown(
        extensions=["meta", "extra", "sane_lists", "smarty", "toc"],
        extension_configs={
            "toc": {"slugify": slugify_unicode, "permalink": "#", "permalink_title": "Ссылка на раздел"},
            "smarty": {"substitutions": {"left-double-quote": "«", "right-double-quote": "»"}},
        },
        output_format="html",
    )


def _plain(text):
    return html.unescape(TAG_RE.sub("", text)).strip()


def _shorten(text, limit):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # режем по границе предложения или слова, чтобы не обрывать на полуслове
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > limit * 0.55:
        return cut[:end + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def _parse_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def parse_quiz(block):
    """Блок ::: quiz → [{q, options, answer, why}]. Битые вопросы молча отбрасываем."""
    out, cur = [], None
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("?"):
            cur = {"q": line[1:].strip(), "options": [], "answer": None, "why": ""}
            out.append(cur)
        elif cur is None:
            continue
        elif line[0] in "+-" and (len(line) == 1 or line[1] == " "):
            cur["options"].append(line[1:].strip())
            if line[0] == "+":
                cur["answer"] = len(cur["options"]) - 1
        elif line.startswith(">"):
            cur["why"] = line[1:].strip()
    return [q for q in out if q["q"] and len(q["options"]) >= 2 and q["answer"] is not None]


@lru_cache(maxsize=128)
def load_post(path, mtime):
    """Кэш по (путь, mtime): правишь .md на сервере — страница обновляется сама."""
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    quiz = []
    m = QUIZ_RE.search(source)
    if m:
        quiz = parse_quiz(m.group(1))
        source = source[:m.start()] + source[m.end():]

    md = _make_md()
    body = md.convert(source)
    meta = {k: " ".join(v).strip() for k, v in getattr(md, "Meta", {}).items()}
    tokens = md.toc_tokens

    slug = re.sub(r"\.md$", "", path.replace("\\", "/").rsplit("/", 1)[-1])
    title = meta.get("title")
    if tokens and tokens[0]["level"] == 1:
        title = title or html.unescape(tokens[0]["name"])
        sections = tokens[0]["children"] + tokens[1:]
        body = H1_RE.sub("", body, count=1)
    else:
        sections = tokens
    title = title or slug.replace("-", " ").capitalize()

    toc = [{"id": t["id"], "name": html.unescape(t["name"])} for t in sections if t["level"] <= 2]

    body = TABLE_RE.sub(r'<div class="doc-table">\1</div>', body)
    body = IMG_RE.sub('<img loading="lazy" decoding="async"', body)

    first_p = FIRST_P_RE.search(body)
    first_text = _plain(first_p.group(1)) if first_p else title
    lead = meta.get("lead") or _shorten(first_text, 220)
    description = meta.get("description") or _shorten(lead, 160)

    words = len(re.findall(r"\w+", _plain(body)))
    mtime_dt = datetime.fromtimestamp(mtime).date()

    return {
        "slug": slug,
        "title": title,
        "lead": lead,
        "description": description,
        "rubric": meta.get("rubric") or DEFAULT_RUBRIC,
        "meta_date": _parse_date(meta.get("date")),
        "updated": _parse_date(meta.get("updated")) or mtime_dt,
        "cover": meta.get("cover", ""),
        "html": body,
        "toc": toc,
        "quiz": quiz,
        "minutes": max(1, round(words / WORDS_PER_MIN)),
        "words": words,
    }


def assemble(posts):
    """
    posts: [{... load_post(), "date": date, "views": int}] в любом порядке.
    -> новые сверху; каждому проставлены number (по порядку выхода), строки дат и поисковая строка.
    """
    ordered = sorted(posts, key=lambda p: (p["date"], p["slug"]))
    for i, p in enumerate(ordered, 1):
        p["number"] = i
        p["number_str"] = f"{i:02d}"
        p["date_iso"] = p["date"].isoformat()
        p["updated_iso"] = p["updated"].isoformat()
        p["date_ru"] = ru_date(p["date"])
        p["date_short"] = ru_date_short(p["date"])
        p["search"] = " ".join((p["title"], p["lead"], p["rubric"])).lower().replace("ё", "е")
    ordered.reverse()
    return ordered


def rubrics_of(posts):
    seen = {}
    for p in posts:
        seen[p["rubric"]] = seen.get(p["rubric"], 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))]


def pick_related(posts, current, limit=3):
    """Сначала та же рубрика, потом самые свежие. Без текущей статьи."""
    rest = [p for p in posts if p["slug"] != current["slug"]]
    same = [p for p in rest if p["rubric"] == current["rubric"]]
    other = [p for p in rest if p["rubric"] != current["rubric"]]
    return (same + other)[:limit]


def json_for_script(obj):
    """JSON внутрь <script> без риска закрыть тег."""
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")
