"""Таблиця фактів: колонки CSV, сортування, markdown для CLI."""
import csv
import json
import os

from ..util import iso_ms

COLUMNS = [
    "wallet", "first_buy_utc", "first_range_buy_utc", "entry_range_mcap", "entry_mcap_first", "entry_mcap_avg",
    "buys_in_range", "invested_in_range_usd", "bought_before_range", "invested_before_range_usd", "buys", "invested_usd",
    "first_sell_utc", "last_sell_utc", "exit_mcap_avg", "sells", "proceeds_usd",
    "sold_share_pct", "holding_share_pct", "realized_usd", "unrealized_usd", "multiple",
    "hold_minutes", "bought_after_range", "partial_history", "source", "tags", "solscan_url",
]


def to_row(f):
    r = dict(f)
    r["first_buy_utc"] = iso_ms(f.get("first_buy_ms"))
    r["first_range_buy_utc"] = iso_ms(f.get("first_range_buy_ms"))
    r["first_sell_utc"] = iso_ms(f.get("first_sell_ms"))
    r["last_sell_utc"] = iso_ms(f.get("last_sell_ms"))
    r["solscan_url"] = f"https://solscan.io/account/{f['wallet']}"
    r["tag_list"] = list(f.get("tags") or [])
    r["tags"] = "|".join(r["tag_list"])
    for k in ("entry_mcap_first", "entry_mcap_avg", "entry_range_mcap", "exit_mcap_avg", "invested_usd",
              "invested_in_range_usd", "invested_before_range_usd", "proceeds_usd", "realized_usd", "unrealized_usd"):
        if r.get(k) is not None:
            r[k] = round(r[k], 2)
    for k in ("sold_share_pct", "holding_share_pct", "hold_minutes"):
        if r.get(k) is not None:
            r[k] = round(r[k], 1)
    if r.get("multiple") is not None:
        r["multiple"] = round(r["multiple"], 2)
    return r


RENAMED = {"buys_in_window": "buys_in_range", "invested_in_window_usd": "invested_in_range_usd",
           "bought_after_window": "bought_after_range"}


def upgrade_result(result):
    """Результати, збережені до перейменування window → range: старі ключі → нові (на місці)."""
    if not result:
        return result
    for r in result.get("rows") or []:
        for old, new in RENAMED.items():
            if old in r and new not in r:
                r[new] = r.pop(old)
        if r.get("tags") or r.get("tag_list"):
            r["tag_list"] = [("pre-range" if t == "pre-window" else t) for t in (r.get("tag_list") or (r.get("tags") or "").split("|")) if t]
            r["tags"] = "|".join(r["tag_list"])
    c = result.get("counts") or {}
    if "pre_window_only" in c and "pre_range_only" not in c:
        c["pre_range_only"] = c.pop("pre_window_only")
    sm = result.get("summary") or {}
    if "invested_window" in sm and "invested_range" not in sm:
        sm["invested_range"] = sm.pop("invested_window")
    return result


def coverage_text(cov):
    """Один людський рядок: для скількох гаманців відомі виходи і чому саме так."""
    if not cov:
        return ""
    k, n = int(cov.get("exits_known") or 0), int(cov.get("total") or 0)
    if cov.get("mode") == "trades":
        return f"Exits known for all {n:,} wallets · full trade history" + ("" if cov.get("cost_full") else " · from cache")
    if k >= n:
        return f"Exits known for all {n:,} wallets · each wallet's trades fetched"
    return (f"Exits known for {k:,} of {n:,} wallets · the rest tagged no-exits "
            f"(cap {int(cov.get('lookup_cap') or 0):,} wallets per analysis)")


def summary(rows):
    """Підсумки для плиток: усе — з рядків таблиці, без нових джерел."""
    n = len(rows)
    exited = sum(1 for r in rows if (r.get("sold_share_pct") or 0) >= 99)
    holding = sum(1 for r in rows if r.get("sold_share_pct") is not None and r["sold_share_pct"] < 50)
    best = max((r.get("multiple") or 0) for r in rows) if rows else 0
    invested = sum((r.get("invested_in_range_usd") or 0) for r in rows)
    realized = sum((r.get("realized_usd") or 0) for r in rows)
    out = {"n": n, "exited": exited, "holding": holding, "best_multiple": best,
           "invested_range": invested, "realized_total": realized,
           "max_in_range": max((r.get("invested_in_range_usd") or 0) for r in rows) if rows else 0,
           "max_abs_realized": max(abs(r.get("realized_usd") or 0) for r in rows) if rows else 0}
    out.update(outcomes(rows))
    return out


def outcomes(rows):
    """Скільки з цих гаманців вийшли в плюс і наскільки — рахуємо з тих самих чисел, що в таблиці.

    Гаманці з тегом `no-exits` не рахуються нікуди: їхніх продажів ми не бачили, і записати їх у збиток
    означало б видати відсутність даних за факт. Вони йдуть окремим числом `unknown`.
    """
    b = {"x2": 0, "up": 0, "down": 0, "wipe": 0, "unknown": 0}
    for r in rows:
        inv = r.get("invested_usd") or r.get("invested_in_range_usd") or 0
        if "no-exits" in (r.get("tag_list") or []) or inv <= 0:
            b["unknown"] += 1
            continue
        k = ((r.get("realized_usd") or 0) + (r.get("unrealized_usd") or 0)) / inv
        b["x2" if k >= 1 else "up" if k > 0 else "down" if k > -0.5 else "wipe"] += 1
    return {"outcomes": b}


def sort_rows(rows):
    """Найбільший реалізований результат зверху; ті, хто ще тримає, — за нереалізованим."""
    return sorted(rows, key=lambda r: -((r.get("realized_usd") or 0) + (r.get("unrealized_usd") or 0)))


def write_csv(rows, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLUMNS})


def write_json(result, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


def money(v):
    """$ у короткому вигляді; будь-що не-числове (None, порожньо, Undefined) → «—»."""
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except Exception:  # noqa: BLE001 — і TypeError/ValueError, і jinja2 Undefined
        return "—"
    sign, v = ("-" if v < 0 else ""), abs(v)
    for lim, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= lim:
            return f"{sign}${v / lim:.2f}{suf}" if v < 10 * lim else f"{sign}${v / lim:.1f}{suf}"
    return f"{sign}${v:,.0f}"


def markdown(result, limit=30):
    info, w = result["info"], result["window"]
    c = result["counts"]
    lines = [
        f"# {info.get('symbol') or info['mint']} — ранні гаманці",
        "",
        f"- Токен: `{info['mint']}`, створено {iso_ms(info.get('created_time'))} UTC, "
        f"supply {info.get('supply'):,.0f}, капа зараз {money(info.get('mcap'))}",
        f"- Вікно входу: {iso_ms(w['from'])} … {iso_ms(w['to'])} UTC; продажі до {iso_ms(w['exit'])} UTC",
        f"- Угод у відрізку: {c['n_trades']:,} | гаманців з покупками у вікні: {c['n_early']} "
        f"| пізніші: {c['late']} | лише продажі (купували до «від»): {c['pre_range_only']} | пил: {c['dust']}",
        f"- Режим: {result.get('mode', 'trades')}" + (f" (повний відрізок ≈{result['est_pages']} сторінок)" if result.get('est_pages') else ""),
        f"- Запитів ST: {result['requests']} (сторінок угод: {result['pages_fetched']}, з кешу: "
        f"{result.get('pages_cached', 0)})" + (f" | залишок кредитів: {result['credits']}" if result.get("credits") is not None else ""),
        "- Позначки: ⚠ — частина історії поза відрізком (продавав куплене до «від»); + — докуповував після «до». "
        "«Вклав» = у вікні / усього до горизонту. Капа входу/виходу — середня за покупками/продажами. "
        "«Результат» = реалізовано + нереалізовано на кінець горизонту.",
        "",
        "| # | гаманець | купив (UTC) | капа входу | вклав (вікно / всього) | продав (UTC) | капа виходу | отримав | продано % | результат $ | ×",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(result["rows"][:limit], 1):
        tot = (r.get("realized_usd") or 0) + (r.get("unrealized_usd") or 0)
        mark = ("⚠" if r.get("partial_history") else "") + ("+" if r.get("bought_after_range") else "")
        inv = money(r.get("invested_in_range_usd"))
        if r.get("bought_after_range"):
            inv += f" / {money(r['invested_usd'])}"
        lines.append(
            f"| {i} | `{r['wallet'][:6]}…{r['wallet'][-4:]}`{mark} | {r['first_buy_utc']} | {money(r['entry_mcap_avg'])} | "
            f"{inv} | {r['first_sell_utc'] or '—'} | {money(r['exit_mcap_avg'])} | "
            f"{money(r['proceeds_usd'])} | {r['sold_share_pct']:.0f}% | {money(tot)} | "
            f"{(str(r['multiple']) + '×') if r.get('multiple') else '—'} |"
        )
    if len(result["rows"]) > limit:
        lines.append(f"\n…ще {len(result['rows']) - limit} гаманців у CSV.")
    return "\n".join(lines) + "\n"
