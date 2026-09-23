"""Масштаб цифр: ті самі гаманці і ті самі угоди, але рахунок до різного моменту.

Діапазон входу лише відбирає гаманці (хто купував у ньому). Факти по кожному з них рахуються з усіх
його угод по токену, збережених у результаті (`result["wallet_trades"]`), до кінця масштабу:
- "all" — уся історія до моменту аналізу;
- "24h" / "48h" — стільки годин після кінця діапазону (щоб порівнювати гаманці на рівних).
Перемикання масштабу нічого не коштує: жодних запитів, лише перерахунок з тих самих угод.
"""
from . import ledger, report, tags

HOUR = 3_600_000
SCOPES = ("all", "24h", "48h")


def scopes_for(s):
    return ["all"] + [f"{int(h)}h" for h in (s.get("scopes") or [24, 48])]


def end_for(scope, t_to, t_end):
    if scope == "all":
        return t_end
    return min(t_end, t_to + int(scope[:-1]) * HOUR)


def pack(trades):
    """Компактний запис угоди для файлу результату: [час, сторона, кількість, $, ціна, SOL].

    Шосте поле додане пізніше: результати, зняті до нього, мають пʼять елементів і читаються так само,
    просто без суми в SOL. Тому розпакування дивиться на довжину, а не припускає формат."""
    return [[tr["time"], tr["type"], tr.get("qty"), tr.get("usd"), tr.get("price"), tr.get("sol")]
            for tr in sorted(trades, key=lambda x: x["time"] or 0) if tr.get("type") in ("buy", "sell")]


def unpack(wallet, packed):
    return [{"wallet": wallet, "type": t[1], "time": t[0], "qty": t[2], "usd": t[3], "price": t[4],
             "sol": (t[5] if len(t) > 5 else None)}
            for t in packed]


def price_at_end(result, t_end):
    """Остання відома ціна ≤ t_end: зі свічки, збереженої при аналізі, або з угод гаманців."""
    best = (0, None)
    for v in (result.get("wallet_trades") or {}).values():
        for t in v.get("trades") or []:
            if t[0] <= t_end and t[4] and t[0] > best[0]:
                best = (t[0], t[4])
    stored = result.get("price_at_end")
    if t_end >= (result.get("window") or {}).get("end", 0) and stored:
        return stored
    return best[1] or stored


def rows_for(result, scope, s=None):
    """(rows, summary) для масштабу з `result["wallet_trades"]`; None лише для результату старого формату (без угод).

    Порожній словник — це не старий формат, а діапазон, у якому ніхто не купив: тоді рядків нема, і це нормально."""
    wt = result.get("wallet_trades")
    if wt is None:
        return None
    w = result["window"]
    supply = (result.get("info") or {}).get("supply") or 0
    created = (result.get("info") or {}).get("created_time")
    t_end = end_for(scope, w["to"], w["end"])
    price = price_at_end(result, t_end) or 0
    fresh = set(result.get("fresh_wallets") or [])
    bundle = result.get("bundle") or {}
    info_ = result.get("info") or {}
    dev = (info_.get("creator") or info_.get("deployer") or "").strip()   # творець токена серед покупців — окремий факт
    facts = []
    for wallet, v in wt.items():
        trs = [tr for tr in unpack(wallet, v.get("trades") or []) if tr["time"] <= t_end]
        L, _ = ledger.build(trs, 0, w["to"], t_end, range_from=w["from"])
        l = L.get(wallet)
        if l is None:
            continue
        f = ledger.facts(l, supply, price) if v.get("source") != "entry-only" else ledger.facts_entry_only(l, supply)
        if v.get("source") == "wallet-trades":
            f["source"] = "wallet-trades"
        f["tags"] = tags.compute(f, created_ms=created, buy_times=l.buy_times, sell_times=l.sell_times)
        if wallet in fresh:
            f["tags"] = tags.with_tag(f["tags"], "fresh")
        if wallet in bundle:
            f["tags"] = tags.with_tag(f["tags"], "bundle")
        if dev and wallet == dev:
            f["tags"] = tags.with_tag(f["tags"], "dev")
        facts.append(f)
    rows = report.sort_rows([report.to_row(f) for f in facts])
    return rows, report.summary(rows)
