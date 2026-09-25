"""Дашборд власника: хто з підключених гаманців що робить на сайті і скільки кредитів це коштує.

Сировина — журнал подій (accounts.EventLog, output/early/usage/YYYY-MM.jsonl), акаунти і результати аналізів. Тут лише
чиста логіка, без aiohttp і без мережі: її можна тестувати на вигаданих подіях.
"""
import datetime
import math
import re
import zoneinfo
from urllib.parse import parse_qs, urlsplit

HOUR = 3_600_000

# Кліки, які сторінка шле в журнал (EarlyUI.use), і які властивості в них можна. Усе інше відкидається: назва не з
# цього списку, властивість не з її рядка, значення не з VAL.
UI = {
    "card-open": ("src",), "card-close": (), "card-period": ("p",), "pin": ("on",),
    "filter": ("k",), "hide": ("tag", "on"), "filters-reset": (), "filters-toggle": ("on",), "funder": ("on",),
    "sort": ("key", "dir", "via"), "select": ("count",), "select-all": ("on",), "select-clear": (),
    "export": ("format", "sel", "filtered", "where"), "agent-open": (), "agent-close": (),
    "show-more": ("all",), "find-pump": (), "limit-window": ("kind",),
    "range-set": ("end",), "range-add": (), "range-reset": (), "tf": ("tf",), "chart-nav": ("to",),
    "list-tab": (), "copy": ("what",), "ext": ("to",), "cur": ("to",), "tz": ("to",), "leave": ("secs",),
}
# короткий рядок: адреса гаманця (32-44 символи) чи набраний людиною текст сюди не пролазять фізично
VAL = re.compile(r"^[A-Za-z0-9_.:-]{1,24}$")
JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,40}$")
LAG_MAX_MS = 600_000


def _val(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and math.isfinite(v):
        v = max(-1e9, min(1e9, v))
        return int(v) if isinstance(v, int) or v == int(v) else round(v, 2)
    if isinstance(v, str) and VAL.match(v):
        return v
    return None


def clean_batch(body, now_ms, max_events=30):
    """Пачка кліків зі сторінки → [{name, p, ts}], лише те, що пройшло білий список. Годиннику браузера не віримо:
    час кліку — «зараз» мінус те, наскільки він старший за найновіший у пачці (не більше 10 хвилин)."""
    items = body.get("e") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    rows = []
    for it in items[:max_events]:
        if not (isinstance(it, list) and len(it) == 3) or it[0] not in UI or not isinstance(it[1], dict):
            continue
        name, props, t = it
        p = {k: _val(props[k]) for k in UI[name] if k in props}
        rows.append((name, {k: v for k, v in p.items() if v is not None},
                     t if isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) else None))
    newest = max((t for _, _, t in rows if t is not None), default=None)
    return [{"name": name, "p": p,
             "ts": int(now_ms - (min(max(newest - t, 0), LAG_MAX_MS) if newest is not None and t is not None else 0))}
            for name, p, t in rows]


def page_of(referer, host):
    """Де клікали — зі шляху Referer цього ж сайту: (сторінка, про що вона). Чужий сайт чи /admin — None."""
    try:
        u = urlsplit(referer or "")
    except ValueError:
        return None
    if not u.netloc or u.netloc != host:
        return None
    path = u.path.rstrip("/") or "/"
    if path == "/admin" or path.startswith("/admin/"):
        return None                                     # власник, що дивиться дашборд, — не користувач продукту
    if path == "/":
        return "home", None
    if path.startswith("/job/"):
        jid = path[5:].split("/")[0]
        return "job", jid if JOB_RE.match(jid) else None
    if path == "/token":
        mint = (parse_qs(u.query).get("mint") or [""])[0]
        return "token", mint if MINT_RE.match(mint) else None
    if path == "/me":
        return "me", None
    if path == "/docs" or path.startswith("/docs/"):
        slug = path[6:] or "index"
        return "docs", slug if SLUG_RE.match(slug) else None
    return "other", None


def zone(name):
    """Часовий пояс доби дашборда; невідомий (чи образ без бази поясів) — UTC."""
    try:
        return zoneinfo.ZoneInfo(str(name or "UTC"))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return datetime.timezone.utc


def _host(v):
    """Лаунчпад коротко: pump.fun, а не https://pump.fun/board."""
    v = str(v or "").strip().lower().split("://", 1)[-1].split("/", 1)[0]
    return (v[4:] if v.startswith("www.") else v)[:24] or None


def run_facts(job):
    """Що рядок журналу знає про закінчений прогін — з полів самого аналізу, без жодного запиту. Те саме рахується і
    для аналізів, зроблених до журналу (дашборд підтягує їх з файлів результатів)."""
    r = job.result or {}
    info = r.get("info") or {}
    t0, t1, created = job.t_from or 0, job.t_to or 0, info.get("created_time") or 0
    ok = job.status == "done" and bool(job.result)
    mcap = info.get("mcap")
    return {"job": job.id, "mint": job.mint, "symbol": job.symbol, "ok": 1 if ok else 0,
            "err": None if ok else (job.error or "")[:120] or None,
            "st": job.spent,                                  # None — невідомо (обірваний рестартом)
            "secs": round((job.finished_ms - job.started_ms) / 1000, 1) if job.finished_ms and job.started_ms else None,
            "wait_s": round((job.started_ms - job.created_ms) / 1000, 1) if job.started_ms and job.created_ms else None,
            "rows": len(r.get("rows") or []) if ok else None,
            "mode": r.get("mode"),
            "range_min": round((t1 - t0) / 60_000) if t1 > t0 else None,
            "age_h": round((t0 - created) / HOUR, 1) if created and t0 >= created else None,          # вік токена на початку пампу
            "after_h": round((job.created_ms - t1) / HOUR, 1) if job.created_ms and t1 and job.created_ms >= t1 else None,   # від пампу до аналізу
            "mcap": round(mcap) if isinstance(mcap, (int, float)) and mcap > 0 else None,
            "pad": _host(info.get("launchpad")),
            "best": round(float((r.get("summary") or {}).get("best_multiple") or 0), 2) or None}
