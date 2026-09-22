"""Документація сайту: markdown з теки docs/ поруч із кодом.

Сторінки правляться тим самим комітом, що й функція, яку вони описують, і їдуть тим самим деплоєм —
окремий сервіс для документації розірвав би це правило першого ж тижня. Порядок і назви в PAGES:
файлу нема — пункт просто не показується, тож приватні нотатки в тій самій теці сюди не потраплять.
"""
import re
import threading

import markdown

PAGES = [
    ("index", "What tracced does"),
    ("how-it-works", "How an analysis works"),
    ("tags", "Tags and what each one means"),
    ("limits", "Limits and what they cost"),
    ("account", "Your account, watchlist and repeats"),
    ("roadmap", "Roadmap"),
]
_MD = markdown.Markdown(extensions=["extra", "toc", "sane_lists"])
_lock = threading.Lock()
_cache = {}


def _slugs():
    return {s for s, _ in PAGES}


def page(docs_dir, slug):
    """(html, title) сторінки або (None, None), якщо такої нема. Кеш у памʼяті: файли міняються з деплоєм."""
    if slug not in _slugs():
        return None, None
    hit = _cache.get(slug)
    if hit:
        return hit
    path = docs_dir / f"{slug}.md"
    if not path.exists():
        return None, None
    text = path.read_text(encoding="utf-8")
    with _lock:
        _MD.reset()
        html = _MD.convert(text)
    html = html.replace("<table>", '<div class="dtw"><table>').replace("</table>", "</table></div>")   # широка таблиця прокручується сама, а не розсуває сторінку
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else dict(PAGES)[slug]
    out = (html, title)
    _cache[slug] = out
    return out


def nav(docs_dir, current):
    """Пункти бічного меню: лише ті сторінки, для яких файл справді є."""
    return [{"slug": s, "label": label, "on": s == current}
            for s, label in PAGES if (docs_dir / f"{s}.md").exists()]
