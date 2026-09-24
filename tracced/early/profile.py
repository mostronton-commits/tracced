"""Картка гаманця: його угоди по всіх токенах за останні дні → підсумок нашим леджером.

Джерело — `GET /wallet/{owner}/trades` Solana Tracker: кожен запис є обміном з двома ногами, `from` (що гаманець
віддав) і `to` (що отримав). Гроші (SOL, стейблкоїни, стейкнутий SOL; список CASH) позицією не є. Обмін гроші→токен — купівля токена,
токен→гроші — продаж, токен→токен — продаж одного і купівля іншого одночасно.

Далі той самий леджер, що й у таблиці аналізу: середня собівартість, прибуток лише з того, що справді куплено.
Токени, продані в цьому вікні без купівлі в ньому (куплені раніше або прийшли переказом), прибутку не дають і
рахуються окремо, щоб число не видавало перекази за заробіток. Чужих оцінок (PnL, winrate, теги) тут нема.

Усе тут чисте: без мережі, тестується на фікстурах.
"""
from ..util import to_ms

DAY = 86_400_000
WSOL = "So11111111111111111111111111111111111111112"
# Гроші, а не позиції: через них купують і в них продають. Без стейблкоїнів, у яких котирують частину пулів (USD1 на
# Bonk), кожна купівля через них виглядала б як «продаж USD1 без купівлі» — на dev 24.09 таких було 24–99 на гаманець.
# Адреси звірені з DexScreener 24.09.2026.
CASH = {
    WSOL,
    "So11111111111111111111111111111111111111111",          # нативний SOL, якщо джерело так його позначить
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",         # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",         # USDT
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",          # USD1 (World Liberty Financial)
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo",         # PYUSD
    "USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA",          # USDS
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",         # JitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",          # mSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",          # bSOL
}
CLOSED_SHARE = 99.0          # позиція закрита, коли продано стільки відсотків купленого
VERSION = 4                  # змінився порахунок — нова версія, і картки з кешу рахуються заново


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


class _Book:
    """Одна позиція гаманця в одному токені: середня собівартість, та сама арифметика, що в ledger.build."""
    __slots__ = ("mint", "symbol", "qty", "cost", "cost_sol", "invested", "realized", "realized_sol", "bought", "sold",
                 "buys", "sells", "orphan_sells", "sol_seen", "sol_gap", "first_buy_t", "last_sell_t", "last_t")

    def __init__(self, mint, symbol):
        self.mint, self.symbol = mint, symbol
        self.qty = self.cost = self.cost_sol = self.invested = self.realized = self.realized_sol = 0.0
        self.bought = self.sold = 0.0
        self.buys = self.sells = self.orphan_sells = 0
        self.sol_seen = self.sol_gap = False
        self.first_buy_t = self.last_sell_t = self.last_t = None

    @property
    def share(self):
        return self.sold / self.bought * 100 if self.bought else 0.0


def _chrono(evs):
    """Події від старих до нових, і в межах однієї секунди теж.

    `/wallet/{owner}/trades` віддає обміни від нових до старих, а час угод — цілі секунди. Стабільне сортування
    лише за часом лишило б купівлю і продаж однієї секунди в порядку джерела, продаж першим: він став би
    продажем без позиції, а купівля — відкритою позицією. Тому спадний вхід спершу перевертаємо."""
    evs = list(evs)
    ts = [e["time"] for e in evs]
    down = sum(1 for x, y in zip(ts, ts[1:]) if x > y)
    up = sum(1 for x, y in zip(ts, ts[1:]) if x < y)
    if down > up:
        evs.reverse()
    evs.sort(key=lambda x: x["time"])
    return evs


def _replay(evs):
    """Події → позиції по токенах і реалізоване кожного продажу в часі [(ms, $)].

    Правила ті самі, що в ledger.build, щоб картка і таблиця ніколи не рахували по-різному: продаж без позиції —
    не вихід і не прибуток; продаж понад куплене рахується лише на куплену частину."""
    books, deltas = {}, []
    for e in _chrono(evs):
        qty, usd = float(e.get("qty") or 0), float(e.get("usd") or 0)
        if qty <= 0:
            continue
        sol = e.get("sol")
        sol = float(sol) if sol is not None else None
        b = books.get(e["mint"])
        if b is None:
            b = books[e["mint"]] = _Book(e["mint"], e.get("symbol"))
        b.symbol = b.symbol or e.get("symbol")
        b.last_t = e["time"]
        if e["type"] == "buy":
            b.buys += 1
            b.qty += qty
            b.cost += usd
            b.invested += usd
            b.bought += qty
            if sol is not None:
                b.cost_sol += sol
                b.sol_seen = True
            else:
                b.sol_gap = True
            if b.first_buy_t is None:
                b.first_buy_t = e["time"]
        elif e["type"] == "sell":
            if b.qty <= 0:
                b.orphan_sells += 1                  # купив раніше або отримав переказом
                continue
            b.sells += 1
            part = min(qty, b.qty)
            avg = b.cost / b.qty
            got = usd * (part / qty)
            d = got - avg * part
            b.realized += d
            deltas.append((e["time"], d))
            if sol is not None:
                avg_sol = b.cost_sol / b.qty
                b.realized_sol += sol * (part / qty) - avg_sol * part
                b.cost_sol -= avg_sol * part
                b.sol_seen = True
            else:
                b.sol_gap = True
            b.sold += part
            b.qty -= part
            b.cost -= avg * part
            b.last_sell_t = e["time"]
    return books, deltas


DIST = ((">500", 500, None), ("200-500", 200, 500), ("50-200", 50, 200), ("0-50", 0, 50), ("-50-0", -50, 0), ("<-50", None, -50))


def _bucket(roi):
    for name, lo, hi in DIST:
        if (lo is None or roi >= lo) and (hi is None or roi < hi):
            return name
    return "<-50"


def _days(deltas):
    """Реалізоване по днях (UTC): [(початок дня, $)] за зростанням, лише дні з продажами."""
    by = {}
    for t, d in deltas:
        day = t - t % DAY
        by[day] = by.get(day, 0.0) + d
    return sorted(by.items())


def _streaks(daily):
    best = worst = cur_w = cur_l = 0
    for _, v in daily:
        cur_w, cur_l = (cur_w + 1, 0) if v > 0 else (0, cur_l + 1) if v < 0 else (0, 0)
        best, worst = max(best, cur_w), max(worst, cur_l)
    return best, worst


def _drawdown(daily):
    """Найбільше падіння накопиченого реалізованого від піку, у доларах."""
    peak = cum = dd = 0.0
    for _, v in daily:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def summary(events, wallet, now_ms, days=30, partial=False):
    """Підсумок гаманця за останні `days` днів з подій (normalize_wallet_swap).

    PnL — сума реалізованого по токенах, куплених і проданих у вікні (середня собівартість, як у таблиці).
    Win rate — частка прибуткових серед закритих позицій (продано ≥ 99 % купленого). Утримання — від першої
    купівлі до останнього продажу закритої позиції. `unbacked_tokens` — токени, які гаманець продавав у вікні,
    не купивши в ньому: їхній прибуток невідомий і в PnL не входить. Розподіл — закриті позиції за ROI у %,
    дні — реалізоване по днях UTC, з них найкращий і найгірший день, серії і найбільше просідання."""
    since = now_ms - days * DAY
    evs = [e for e in events if e.get("time") is not None and since <= e["time"] <= now_ms]
    books, deltas = _replay(evs)
    pnl = pnl_sol = invested = 0.0
    sol_ok = True
    closed = wins = open_ = unbacked = 0
    holds, per_token = [], []
    dist = {name: 0 for name, _, _ in DIST}
    for b in books.values():
        if b.buys == 0:
            unbacked += 1                           # лише продажі: купив раніше або отримав переказом
            continue
        pnl += b.realized
        invested += b.invested
        if b.sol_seen and not b.sol_gap:
            pnl_sol += b.realized_sol
        else:
            sol_ok = False
        if b.share >= CLOSED_SHARE:
            closed += 1
            wins += b.realized > 0
            if b.invested > 0:
                dist[_bucket(b.realized / b.invested * 100)] += 1
            if b.first_buy_t is not None and b.last_sell_t is not None:
                holds.append((b.last_sell_t - b.first_buy_t) / 60_000)
        else:
            open_ += 1
        per_token.append({"mint": b.mint, "symbol": b.symbol, "realized_usd": b.realized, "closed": b.share >= CLOSED_SHARE})
    per_token.sort(key=lambda x: -x["realized_usd"])
    daily = _days(deltas)
    best_w, best_l = _streaks(daily)
    hi = max(daily, key=lambda x: x[1], default=None)
    lo = min(daily, key=lambda x: x[1], default=None)
    oldest = min((e["time"] for e in evs), default=None)
    return {
        "wallet": wallet,
        "days": days,
        "since_ms": since,
        "oldest_ms": oldest,
        "swaps": len({e.get("tx") or id(e) for e in evs}),   # обмін токена на токен — дві події, але один обмін
        "buys": sum(1 for e in evs if e["type"] == "buy"),
        "sells": sum(1 for e in evs if e["type"] == "sell"),
        "volume_usd": sum(float(e.get("usd") or 0) for e in evs),
        "tokens": closed + open_,
        "pnl_usd": pnl,
        "pnl_sol": pnl_sol if (sol_ok and (closed + open_)) else None,
        "invested_usd": invested,
        "closed": closed,
        "wins": wins,
        "losses": closed - wins,
        "open": open_,
        "win_rate": (wins / closed) if closed else None,
        "avg_hold_min": (sum(holds) / len(holds)) if holds else None,
        "unbacked_tokens": unbacked,
        "best": [t for t in per_token if t["realized_usd"] > 0][:3],
        "dist": dist,
        "daily": [[d, round(v, 2)] for d, v in daily],
        "best_day": {"ms": hi[0], "usd": hi[1]} if hi else None,
        "worst_day": {"ms": lo[0], "usd": lo[1]} if lo else None,
        "win_streak": best_w,
        "loss_streak": best_l,
        "max_drawdown_usd": _drawdown(daily),
        "partial": bool(partial),
    }


def heatmap(events, now_ms, days=30):
    """Коли гаманець торгує: обміни за днем тижня (пн = 0) і годиною, UTC. Браузер зсуває на свій пояс."""
    since = now_ms - days * DAY
    grid, seen = [[0] * 24 for _ in range(7)], set()
    for e in events:
        t = e.get("time")
        if t is None or not since <= t <= now_ms or (e.get("tx") and e["tx"] in seen):
            continue
        seen.add(e.get("tx"))
        s = t // 1000
        grid[(s // 86400 + 3) % 7][(s // 3600) % 24] += 1      # 1 січня 1970 — четвер
    return grid


def recent_tokens(events, now_ms, days=30, n=12):
    """Останні токени гаманця з результатом кожного: що купив, що продав, скільки заробив, закрито чи ні."""
    since = now_ms - days * DAY
    books, _ = _replay([e for e in events if e.get("time") is not None and since <= e["time"] <= now_ms])
    out = []
    for b in sorted(books.values(), key=lambda x: -(x.last_t or 0))[:n]:
        state = "sold only" if b.buys == 0 else ("closed" if b.share >= CLOSED_SHARE else "open")
        out.append({"mint": b.mint, "symbol": b.symbol, "state": state, "last_ms": b.last_t, "buys": b.buys,
                    "sells": b.sells + b.orphan_sells, "invested_usd": b.invested,
                    "realized_usd": b.realized if b.buys else None,
                    "roi": (b.realized / b.invested * 100) if (state == "closed" and b.invested > 0) else None})
    return out


def card(events, wallet, now_ms, partial=False):
    """Усе для картки гаманця одним словником: 30 днів на верхньому рівні, 7 і 30 днів у `periods`, мапа
    активності і останні токени. Жодного запиту понад ті, що вже принесли обміни."""
    d30 = summary(events, wallet, now_ms, 30, partial)
    return dict(d30, periods={"7": summary(events, wallet, now_ms, 7, partial), "30": d30},
                heat=heatmap(events, now_ms), recent=recent_tokens(events, now_ms))


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
    av = raw.get("avatar")
    if isinstance(av, str) and av.startswith("https://") and len(av) < 300 and '"' not in av and "<" not in av:
        out["avatar"] = av                          # лише у KOL: їхні аватари Solana Tracker тримає на своєму CDN
    return out or None
