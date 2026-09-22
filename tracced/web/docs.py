"""Документація сайту: markdown з теки docs/ поруч із кодом.

Сторінки правляться тим самим комітом, що й функція, яку вони описують, і їдуть тим самим деплоєм —
окремий сервіс для документації розірвав би це правило першого ж тижня. Порядок і назви в PAGES:
файлу нема — пункт просто не показується, тож приватні нотатки в тій самій теці сюди не потраплять.
"""
import re
import threading

import jinja2
import markdown

# slug, назва в меню (1–3 слова), значок, рядок під назвою на сторінці «Overview»
PAGES = [
    ("index", "Overview", "🧭", "What tracced answers and how to read it"),
    ("how-it-works", "How it works", "⚙️", "Where every number on the page comes from"),
    ("tags", "Tags", "🏷️", "Ten rules, each one checkable on chain"),
    ("limits", "Limits", "⏳", "What is free, what needs a wallet, what it costs us"),
    ("account", "Your account", "🔑", "Sign-in, watchlist, your own tags, repeats"),
    ("roadmap", "Roadmap", "🗺️", "Shipped, next, and what we will not build"),
]
_MD = markdown.Markdown(extensions=["extra", "toc", "sane_lists", "admonition"])
_lock = threading.Lock()
_cache = {}


def _slugs():
    return {p[0] for p in PAGES}


def page(docs_dir, slug, ctx=None):
    """(html, title) сторінки або (None, None), якщо такої нема.

    Текст спершу проходить через Jinja з тими самими налаштуваннями, що й сайт, тож число в документації
    не може розійтися з реальним лімітом: воно те саме. Кеш у памʼяті — файли міняються лише з деплоєм.
    """
    if slug not in _slugs():
        return None, None
    hit = _cache.get(slug)
    if hit:
        return hit
    path = docs_dir / f"{slug}.md"
    if not path.exists():
        return None, None
    text = jinja2.Template(path.read_text(encoding="utf-8"), autoescape=False).render(**(ctx or {}))
    with _lock:
        _MD.reset()
        html = _MD.convert(text)
    html = html.replace("<table>", '<div class="dtw"><table>').replace("</table>", "</table></div>")   # широка таблиця прокручується сама, а не розсуває сторінку
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else dict((p[0], p[1]) for p in PAGES)[slug]
    out = (html, title)
    _cache[slug] = out
    return out


def _live(docs_dir):
    """Лише ті сторінки, для яких файл справді є: меню не показує того, чого нема."""
    return [{"slug": s, "label": label, "icon": icon, "blurb": blurb}
            for s, label, icon, blurb in PAGES if (docs_dir / f"{s}.md").exists()]


def nav(docs_dir, current):
    return [dict(p, on=p["slug"] == current) for p in _live(docs_dir)]


def around(docs_dir, current):
    """Сусіди сторінки для кнопок внизу: читати документацію підряд має бути так само легко, як книжку."""
    live = _live(docs_dir)
    i = next((n for n, p in enumerate(live) if p["slug"] == current), None)
    if i is None:
        return None, None
    return (live[i - 1] if i > 0 else None), (live[i + 1] if i + 1 < len(live) else None)
