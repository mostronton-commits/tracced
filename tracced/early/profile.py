"""Картка гаманця: його угоди по всіх токенах за останні дні → підсумок нашим леджером.

Джерело — `GET /wallet/{owner}/trades` Solana Tracker: кожен запис є обміном з двома ногами, `from` (що гаманець
віддав) і `to` (що отримав). Гроші (SOL, WSOL, USDC, USDT) позицією не є. Обмін гроші→токен — купівля токена,
токен→гроші — продаж, токен→токен — продаж одного і купівля іншого одночасно.

Далі той самий леджер, що й у таблиці аналізу: середня собівартість, прибуток лише з того, що справді куплено.
Токени, продані в цьому вікні без купівлі в ньому (куплені раніше або прийшли переказом), прибутку не дають і
рахуються окремо, щоб число не видавало перекази за заробіток. Чужих оцінок (PnL, winrate, теги) тут нема.

Усе тут чисте: без мережі, тестується на фікстурах.
"""
from ..util import to_ms
from . import ledger

DAY = 86_400_000
WSOL = "So11111111111111111111111111111111111111112"
CASH = {
    WSOL,
    "So11111111111111111111111111111111111111111",          # нативний SOL, якщо джерело так його позначить
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",         # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",         # USDT
}
CLOSED_SHARE = 99.0          # позиція закрита, коли продано стільки відсотків купленого


def _num(v):
    if isinstance(v, dict):
        v = v.get("usd")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _leg(raw, side):
    leg = raw.get(side) or {}
    tok = leg.get("token") or {}
    return {"mint": leg.get("address"), "amount": _num(leg.get("amount")), "price": _num(leg.get("priceUsd")),
            "symbol": tok.get("symbol"), "name": tok.get("name")}


def normalize_wallet_swap(raw, wallet=None, cash=CASH):
    """Один обмін з `/wallet/{owner}/trades` → 0, 1 або 2 події леджера.

    Подія = {"wallet", "mint", "symbol", "type", "time", "qty", "usd", "sol", "price", "tx", "program"}.
    Сума в доларах: обсяг обміну, коли одна нога — гроші; для токен→токен кожна нога рахується з власної ціни."""
    t = to_ms(raw.get("time"))
    w = raw.get("wallet") or wallet
    if t is None or not w:
        return []
    vol = raw.get("volume")
    vol_usd = _num(vol)
    vol_sol = _num(vol.get("sol")) if isinstance(vol, dict) else _num(raw.get("volumeSol"))
    a, b = _leg(raw, "from"), _leg(raw, "to")
    a_cash, b_cash = a["mint"] in cash, b["mint"] in cash
    out = []

    def event(leg, typ, usd):
        qty = leg["amount"]
        if not leg["mint"] or not qty or qty <= 0 or usd is None:
            return
        price = leg["price"] or (usd / qty if qty else None)
        out.append({"wallet": w, "mint": leg["mint"], "symbol": leg["symbol"], "type": typ, "time": t,
                    "qty": qty, "usd": usd, "sol": vol_sol, "price": price, "tx": raw.get("tx"),
                    "program": raw.get("program")})

    def own_value(leg):
        return leg["amount"] * leg["price"] if (leg["amount"] and leg["price"]) else vol_usd

    if a_cash and b_cash:
        return []                                   # SOL↔USDC: грошей стало інакше, позиції не було
    if a_cash:
        event(b, "buy", vol_usd if vol_usd is not None else own_value(b))
    elif b_cash:
        event(a, "sell", vol_usd if vol_usd is not None else own_value(a))
    else:                                           # токен→токен: продаж одного і купівля іншого
        event(a, "sell", own_value(a))
        event(b, "buy", own_value(b))
    return out


def summary(events, wallet, now_ms, days=30, partial=False):
    """Підсумок гаманця за останні `days` днів з подій (normalize_wallet_swap).

    PnL — сума реалізованого по токенах, куплених і проданих у вікні (середня собівартість, як у таблиці).
    Win rate — частка прибуткових серед закритих позицій (продано ≥ 99 % купленого). Утримання — від першої
    купівлі до останнього продажу закритої позиції. `unbacked_tokens` — токени, які гаманець продавав у вікні,
    не купивши в ньому: їхній прибуток невідомий і в PnL не входить."""
    since = now_ms - days * DAY
    evs = [e for e in events if e.get("time") is not None and since <= e["time"] <= now_ms]
    by_mint, symbols = {}, {}
    for e in evs:
        by_mint.setdefault(e["mint"], []).append(e)
        if e.get("symbol"):
            symbols[e["mint"]] = e["symbol"]
    pnl = pnl_sol = invested = 0.0
    sol_ok = True
    closed = wins = open_ = unbacked = 0
    holds, per_token = [], []
    for mint, es in by_mint.items():
        book, _ = ledger.build(es, 0, now_ms, now_ms)
        l = book.get(wallet)
        if l is None:
            continue
        if l.buys == 0:
            unbacked += 1                           # лише продажі: купив раніше або отримав переказом
            continue
        pnl += l.realized
        invested += l.invested
        if l.sol_seen and not l.sol_gap:
            pnl_sol += l.realized_sol
        else:
            sol_ok = False
        share = l.sold_qty / l.bought_qty * 100 if l.bought_qty else 0.0
        if share >= CLOSED_SHARE:
            closed += 1
            wins += l.realized > 0
            if l.first_buy_t is not None and l.last_sell_t is not None:
                holds.append((l.last_sell_t - l.first_buy_t) / 60_000)
        else:
            open_ += 1
        per_token.append({"mint": mint, "symbol": symbols.get(mint), "realized_usd": l.realized,
                          "closed": share >= CLOSED_SHARE})
    per_token.sort(key=lambda x: -x["realized_usd"])
    oldest = min((e["time"] for e in evs), default=None)
    return {
        "wallet": wallet,
        "days": days,
        "since_ms": since,
        "oldest_ms": oldest,
        "swaps": len(evs),
        "tokens": closed + open_,
        "pnl_usd": pnl,
        "pnl_sol": pnl_sol if (sol_ok and (closed + open_)) else None,
        "invested_usd": invested,
        "closed": closed,
        "wins": wins,
        "open": open_,
        "win_rate": (wins / closed) if closed else None,
        "avg_hold_min": (sum(holds) / len(holds)) if holds else None,
        "unbacked_tokens": unbacked,
        "best": [t for t in per_token if t["realized_usd"] > 0][:3],
        "partial": bool(partial),
    }


def compact_identity(raw):
    """Ідентичність гаманця від Solana Tracker (KOL, Twitter, платформи) → лише те, що показуємо.

    Це ідентифікація з названим джерелом, а не оцінка. Невідомий гаманець → None."""
    if not isinstance(raw, dict) or not raw:
        return None
    out = {}
    for k in ("name", "twitter", "type"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:80]
    for k in ("tags", "platforms"):
        v = raw.get(k)
        if isinstance(v, list):
            vals = [str(x)[:40] for x in v if isinstance(x, (str, int)) and str(x).strip()]
            if vals:
                out[k] = vals[:8]
    sns = raw.get("sns")
    if isinstance(sns, dict) and isinstance(sns.get("domain"), str):
        out["sns"] = sns["domain"][:80]
    return out or None
