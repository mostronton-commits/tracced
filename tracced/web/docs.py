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
    ("compare", "Compare", "⚖️", "Why not just look at Axiom or GMGN"),
    ("how-it-works", "How it works", "⚙️", "Where every number on the page comes from"),
    ("tags", "Tags", "🏷️", "Nine rules, each one checkable on chain"),
    ("limits", "Limits", "⏳", "What is free and what needs a wallet"),
    ("account", "Your account", "🔑", "Sign-in, lists, your own tags, repeats"),
    ("api", "API", "🔌", "A token check for partners, in beta"),
    ("roadmap", "Roadmap", "🗺️", "Shipped, next, and what we will not build"),
    ("updates", "Updates", "🆕", "What each version brought, newest first"),
    ("project", "The project", "📌", "Why it exists and what it refuses to do"),
]
# guides (28.11): answers to what traders search for, in docs/guides/, each with real numbers from tracced's analyses.
# The overview is guides/index.md; the order here is the menu's
GUIDES = [
    ("index", "All guides", "📚", "What traders ask, answered with on-chain data"),
    ("check-if-a-coin-is-bundled", "Is it bundled?", "📦", "How to check a pump.fun launch for bundles"),
    ("find-insider-wallets", "Insider wallets", "🔎", "Find who bought a Solana token before the pump"),
    ("dev-sold", "Dev sold", "🧑‍💻", "What it means and how to check it"),
    ("jito-bundles-snipers", "Bundles vs snipers", "⚡", "Jito bundles, bundlers and snipers, told apart"),
    ("copy-trading-early-buyers", "Copy trading", "🪞", "Can you copy the wallets that bought first"),
    ("solana-launches-in-numbers", "Launches in numbers", "📊", "What tracced's analyses show about launches"),
]
SECTIONS = {"docs": PAGES, "guides": GUIDES}
_MD = markdown.Markdown(extensions=["extra", "toc", "sane_lists", "admonition"])
_lock = threading.Lock()
_cache = {}


def latest(docs_dir):
    """Найновіша версія зі сторінки Updates: {"v": "0.7.0", "date": "Oct 4, 2026"} або None. Позначка «що нового» біля
    гаманця світиться, поки людина не побачила саме цю версію (власник, 04.10)."""
    try:
        text = (docs_dir / "updates.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^##\s+(\S+)(?:\s+<span class="ud">([^<]+)</span>)?', text, re.M)
    return {"v": m.group(1), "date": (m.group(2) or "").strip()} if m else None


def _slugs(section="docs"):
    return {p[0] for p in SECTIONS[section]}


def _dir(docs_dir, section):
    return docs_dir if section == "docs" else docs_dir / section


def page(docs_dir, slug, ctx=None, section="docs"):
    """(html, title) сторінки або (None, None), якщо такої нема.

    Текст спершу проходить через Jinja з тими самими налаштуваннями, що й сайт, тож число в документації
    не може розійтися з реальним лімітом: воно те саме. Кеш у памʼяті — файли міняються лише з деплоєм.
    """
    if slug not in _slugs(section):
        return None, None
    hit = _cache.get((section, slug))
    if hit:
        return hit
    path = _dir(docs_dir, section) / f"{slug}.md"
    if not path.exists():
        return None, None
    text = jinja2.Template(path.read_text(encoding="utf-8"), autoescape=False).render(**(ctx or {}))
    with _lock:
        _MD.reset()
        html = _MD.convert(text)
    html = re.sub(r"<table(\s[^>]*)?>", lambda m: '<div class="dtw"><table%s>' % (m.group(1) or ""), html)
    html = html.replace("</table>", "</table></div>")        # широка таблиця прокручується сама, а не розсуває сторінку
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else dict((p[0], p[1]) for p in SECTIONS[section])[slug]
    out = (html, title)
    _cache[(section, slug)] = out
    return out


def source(docs_dir, slug, ctx=None, section="docs"):
    """The page as plain markdown, numbers filled in like on the site: what an AI assistant reads (llms.txt links here).
    None if there is no such page."""
    if slug not in _slugs(section):
        return None
    path = _dir(docs_dir, section) / f"{slug}.md"
    if not path.exists():
        return None
    return jinja2.Template(path.read_text(encoding="utf-8"), autoescape=False).render(**(ctx or {})).strip() + "\n"


def _live(docs_dir, section="docs"):
    """Лише ті сторінки, для яких файл справді є: меню не показує того, чого нема."""
    d = _dir(docs_dir, section)
    return [{"slug": s, "label": label, "icon": icon, "blurb": blurb}
            for s, label, icon, blurb in SECTIONS[section] if (d / f"{s}.md").exists()]


def nav(docs_dir, current, section="docs"):
    return [dict(p, on=p["slug"] == current) for p in _live(docs_dir, section)]


def around(docs_dir, current, section="docs"):
    """Сусіди сторінки для кнопок внизу: читати документацію підряд має бути так само легко, як книжку."""
    live = _live(docs_dir, section)
    i = next((n for n, p in enumerate(live) if p["slug"] == current), None)
    if i is None:
        return None, None
    return (live[i - 1] if i > 0 else None), (live[i + 1] if i + 1 < len(live) else None)
