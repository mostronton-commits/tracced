"""Insights: короткі висновки про покупців токена у відсотках (трейдер, 01.10: «висновки по токену, а не голі цифри»).

Ті самі правила сторінка результату малює над графіком (job.html, findings()); тут — для рядка під кожним токеном на
головній. Лише факти, без оцінок: кожен рядок — частка того, що сталося. Повтори в інших аналізах людини тут не
рахуються: вони свої в кожного, а головна однакова для всіх."""
from ..early import exchanges as exch_mod

MIN_ROWS = 20           # менше гаманців — частки нічого не кажуть
HOME_MAX = 2            # на головній — два найсильніші


def _pct(a, b):
    """Частка у відсотках; «100%» лише коли справді всі (299 з 300 — це 99%, а не 100%)."""
    if not b:
        return 0
    p = round(100 * a / b)
    return 99 if a < b and p >= 100 else p


def _tags(row):
    tl = row.get("tag_list")
    return tl if isinstance(tl, list) else [t for t in str(row.get("tags") or "").split("|") if t]


def of_result(r, checked=None):
    """Висновки готового результату в порядку важливості → [{k, pct, text, sev}].

    checked — скільки гаманців перевіряли на вік (fresh рахується лише серед них)."""
    rows = (r or {}).get("rows") or []
    n = len(rows)
    if not n:
        return []
    out = []

    def inv(x):
        return float(x.get("invested_in_range_usd") or 0)
    tot = sum(inv(x) for x in rows) or 1.0
    if any("dev" in _tags(x) for x in rows):
        out.append({"k": "dev", "sev": "warn", "pct": None, "text": "Creator bought in the range"})
    bundled = [x for x in rows if "bundle" in _tags(x)]
    sh = _pct(sum(inv(x) for x in bundled), tot)
    if bundled and sh >= 10:
        out.append({"k": "bundle", "sev": "warn", "pct": sh, "text": f"{sh}% bought through bundles"})
    # fresh — серед перевірених на вік: ages, коли результат їх зберіг, інакше заплановані (enrich.total, як у вижимці
    # агента). Старий результат міг перевірити більше (учасників бандлів) — тоді знаменник те, що справді перевірено
    en = (r or {}).get("enrich") or {}
    fresh = sum(1 for x in rows if "fresh" in _tags(x))
    chk = len((r or {}).get("ages") or {}) or min(n, int(en.get("total") or checked or n))
    if fresh > chk:
        chk = max(fresh, int(en.get("done") or 0))
    chk = chk or 1
    if fresh >= 10 and fresh / chk >= 0.1:
        out.append({"k": "fresh", "sev": "warn", "pct": _pct(fresh, chk), "text": f"{_pct(fresh, chk)}% fresh wallets"})
    prof = sorted((float(x.get("realized_usd") or 0) for x in rows if (x.get("realized_usd") or 0) > 0), reverse=True)
    if len(prof) >= MIN_ROWS:
        s10 = _pct(sum(prof[:10]), sum(prof))
        if s10 >= 40:
            out.append({"k": "top", "sev": "info", "pct": s10, "text": f"Top 10 took {s10}% of the profit"})
    if n >= MIN_ROWS:
        sold = [x.get("sold_share_pct") for x in rows]
        so = _pct(sum(1 for v in sold if (v or 0) >= 99), n)
        hold = _pct(sum(1 for v in sold if v is not None and v < 50), n)
        if so >= 60:
            out.append({"k": "sold", "sev": "info", "pct": so, "text": f"{so}% already sold out"})
        elif hold >= 40:
            out.append({"k": "hold", "sev": "info", "pct": hold, "text": f"{hold}% still holding"})
    funders = (r or {}).get("funders") or {}
    ex = sum(1 for f in funders.values() if exch_mod.name_of(f))
    if ex >= 10 and ex / len(funders) >= 0.05:
        out.append({"k": "cex", "sev": "info", "pct": _pct(ex, len(funders)), "text": f"{_pct(ex, len(funders))}% funded from exchanges"})
    if n >= MIN_ROWS:
        won = _pct(sum(1 for x in rows if (x.get("realized_usd") or 0) > 0), n)
        out.append({"k": "won", "sev": "info", "pct": won, "text": f"{won}% took a profit"})
    return out


def headline(r, checked=None, k=HOME_MAX):
    """Рядок для головної: два найсильніші висновки через « · »; порожній, коли сказати нічого."""
    return " · ".join(x["text"] for x in of_result(r, checked)[:k])
