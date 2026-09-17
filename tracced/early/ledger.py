"""Леджер гаманця по одному токену: покупки і продажі → факти.

Метод середньої ціни (той самий, що в KOLS data/wallet_pnl.py::positions): кожен продаж
закриває частину позиції за середньою ціною входу, різниця — реалізований результат.
Нічого не оцінюємо: лише те, що прямо випливає з угод.

Угода тут = {"wallet", "type": "buy"|"sell", "time": ms, "qty", "usd", "price", "tx", "program"}.
"""
import bisect
import statistics

from ..util import to_ms


def normalize(raw):
    """Сирий запис Solana Tracker /trades → наш формат. Кількість = amount, сума = volume (USD)."""
    return {
        "wallet": raw.get("wallet"),
        "type": raw.get("type"),
        "time": to_ms(raw.get("time")),
        "qty": raw.get("amount"),
        "usd": raw.get("volume"),
        "price": raw.get("priceUsd"),
        "tx": raw.get("tx"),
        "program": raw.get("program"),
    }


class Ledger:
    __slots__ = ("wallet", "buys", "sells", "qty", "cost", "invested", "proceeds", "realized",
                 "bought_qty", "sold_qty", "first_buy_t", "first_buy_price", "last_buy_t",
                 "first_sell_t", "last_sell_t", "buys_in_window", "invested_in_window",
                 "buys_after_window", "sold_without_buy", "oversold", "buy_times", "sell_times",
                 "first_range_buy_t", "first_range_buy_price", "buys_before_range", "invested_before_range")

    def __init__(self, wallet):
        self.wallet = wallet
        self.buys = self.sells = 0
        self.qty = self.cost = 0.0            # відкрита позиція і її собівартість
        self.invested = self.proceeds = self.realized = 0.0
        self.buys_in_window = 0               # покупки до «до» включно — «зайшов рано»
        self.invested_in_window = 0.0
        self.bought_qty = self.sold_qty = 0.0
        self.first_buy_t = self.last_buy_t = None
        self.first_buy_price = None
        self.first_sell_t = self.last_sell_t = None
        self.buys_after_window = 0
        self.sold_without_buy = 0             # продаж без позиції = купував до «від»
        self.oversold = 0                     # продав більше, ніж мав у відрізку
        self.buy_times = []                   # для тегів-фактів (утримання, швидкі пари)
        self.sell_times = []
        self.first_range_buy_t = None         # перша покупка САМЕ в діапазоні [range_from … t_to] — «ранній вхід»
        self.first_range_buy_price = None
        self.buys_before_range = 0            # купував ще до діапазону (lifetime-масштаб)
        self.invested_before_range = 0.0


MINUTE = 60_000
REPAIR_FACTOR = 1000         # у скільки разів ціна має розійтись із ринковою, щоб не вірити кількості


def price_reference(trades):
    """Ринкова ціна по хвилинах: медіана цін угод кожної хвилини.

    Медіана стійка до кількох зіпсованих значень, тому її можна рахувати прямо з сирого потоку.
    Повертає (відсортовані хвилини, медіани) для пошуку найближчої хвилини з даними.
    """
    by_min = {}
    for tr in trades:
        t, pr = tr.get("time"), tr.get("price")
        if t is None or not pr or pr <= 0:
            continue
        by_min.setdefault(t // MINUTE, []).append(float(pr))
    mins = sorted(by_min)
    return mins, [statistics.median(by_min[m]) for m in mins]


def repair_quantities(trades, ref=None, factor=REPAIR_FACTOR):
    """Лагодить угоди, у яких джерело віддало кількість токенів іншого порядку.

    Приблизно в одній угоді з тисячі Solana Tracker повертає `amount`, зміщений на багато порядків
    (баг десяткових у деяких агрегаторах: гаманець «продає» 5.8e-11 токена за $1 821). Сума в доларах
    при цьому правильна, а похідна ціна — ні, і через неї ламаються капа виходу, множник і частка
    проданого. Беремо ринкову ціну тієї хвилини, кількість перераховуємо з доларів; долари не чіпаємо.

    Міняє список на місці. Повертає, скільки угод полагоджено.
    """
    mins, meds = ref if ref is not None else price_reference(trades)
    if not mins:
        return 0
    fixed = 0
    for tr in trades:
        t, usd = tr.get("time"), float(tr.get("usd") or 0)
        if t is None or usd <= 0:
            continue
        i = bisect.bisect_left(mins, t // MINUTE)
        cands = [j for j in (i - 1, i) if 0 <= j < len(mins)]
        if not cands:
            continue
        m = min(cands, key=lambda j: abs(mins[j] - t // MINUTE))
        market = meds[m]
        price = float(tr.get("price") or 0)
        qty = float(tr.get("qty") or 0)
        if market <= 0:
            continue
        if price > 0 and qty > 0 and 1 / factor <= price / market <= factor:
            continue                                  # ціна в межах ринкової — віримо кількості
        tr["price"], tr["qty"], tr["repaired"] = market, usd / market, True
        fixed += 1
    return fixed


def build(trades, t_from, t_to, t_exit, range_from=None):
    """Леджери всіх гаманців за угодами в [t_from … t_exit]. Повертає (dict wallet→Ledger, stats).

    Діапазон входу — [range_from … t_to] (за замовчуванням від t_from): покупки в ньому — «в діапазоні»,
    раніше — «до діапазону», пізніше — «після». t_from може бути 0 (уся історія токена)."""
    L = {}
    stats = {"n_trades": 0}
    rf = t_from if range_from is None else range_from
    for tr in sorted(trades, key=lambda x: x["time"] or 0):
        t = tr["time"]
        if t is None or t < t_from or t > t_exit:
            continue
        qty = float(tr.get("qty") or 0)
        usd = float(tr.get("usd") or 0)
        price = float(tr.get("price") or 0)
        if qty <= 0 or not tr.get("wallet"):
            continue
        stats["n_trades"] += 1
        l = L.get(tr["wallet"])
        if l is None:
            l = L[tr["wallet"]] = Ledger(tr["wallet"])
        if tr["type"] == "buy":
            l.buys += 1
            l.qty += qty
            l.cost += usd
            l.invested += usd
            l.bought_qty += qty
            if l.first_buy_t is None:
                l.first_buy_t, l.first_buy_price = t, price
            l.last_buy_t = t
            l.buy_times.append(t)
            if t > t_to:
                l.buys_after_window += 1
            elif t >= rf:
                l.buys_in_window += 1
                l.invested_in_window += usd
                if l.first_range_buy_t is None:
                    l.first_range_buy_t, l.first_range_buy_price = t, price
            else:
                l.buys_before_range += 1
                l.invested_before_range += usd
        elif tr["type"] == "sell":
            if l.qty <= 0:
                l.sold_without_buy += 1       # продаж без позиції у відрізку = купував до «від»
                continue                      # у «продав» не потрапляє: це не вихід з нашої покупки
            l.sells += 1
            if l.first_sell_t is None:
                l.first_sell_t = t
            l.last_sell_t = t
            l.sell_times.append(t)
            part = min(qty, l.qty)
            avg = l.cost / l.qty
            got = usd * (part / qty)
            l.realized += got - avg * part
            l.proceeds += got
            l.sold_qty += part
            l.qty -= part
            l.cost -= avg * part
            if part < qty - 1e-9:
                l.oversold += 1
    return L, stats


def classify(ledgers, t_to, min_invested_usd):
    """Розкладає леджери: ранні (є покупка в діапазоні, не пил) / решта з причинами."""
    early, counts = [], {"pre_range_only": 0, "before_range_only": 0, "late": 0, "dust": 0}
    for l in ledgers.values():
        if l.first_range_buy_t is None:
            if l.first_buy_t is None:
                counts["pre_range_only"] += 1      # лише продажі — купував до «від», покупок не бачимо
            elif l.first_buy_t > t_to:
                counts["late"] += 1
            else:
                counts["before_range_only"] += 1   # купував лише до діапазону
        elif l.invested_in_window < min_invested_usd:
            counts["dust"] += 1
        else:
            early.append(l)
    return early, counts


def facts_from_stats(l, st, supply):
    """Вхід — з нашого леджера вікна (точно), виходи — зі статистики гаманця по токену (ST, за весь
    час до моменту запиту). Для гарячих токенів, де повний список угод коштує тисячі сторінок."""
    entry_first = (l.first_buy_price or 0) * supply
    entry_avg = (l.invested / l.bought_qty) * supply if l.bought_qty else None
    bought = float(st.get("bought") or 0) or l.bought_qty
    sold = float(st.get("sold") or 0)
    proceeds = float(st.get("proceeds") or 0)
    exit_avg = (proceeds / sold) * supply if (sold > 0 and proceeds > 0) else None
    sold_share = min(sold / bought * 100, 100.0) if bought else 0.0
    first_sell, last_sell = st.get("first_sell"), st.get("last_sell")
    hold_min = None
    if first_sell and l.first_buy_t and first_sell >= l.first_buy_t:
        hold_min = (first_sell - l.first_buy_t) / 60_000
    buys_total = int(st.get("buys") or 0)
    return {
        "wallet": l.wallet,
        "first_buy_ms": l.first_buy_t,
        "entry_mcap_first": entry_first,
        "entry_mcap_avg": entry_avg,
        "buys_in_range": l.buys_in_window,
        "invested_in_range_usd": l.invested_in_window,
        "buys": max(buys_total, l.buys),
        "invested_usd": float(st.get("invested") or 0) or l.invested,
        "first_sell_ms": first_sell,
        "last_sell_ms": last_sell,
        "exit_mcap_avg": exit_avg,
        "sells": int(st.get("sells") or 0),
        "proceeds_usd": proceeds,
        "sold_share_pct": sold_share,
        "holding_share_pct": max(0.0, 100.0 - sold_share),
        "realized_usd": float(st.get("realized") or 0),
        "unrealized_usd": float(st.get("unrealized") or 0),
        "multiple": (exit_avg / entry_avg) if (exit_avg and entry_avg) else None,
        "hold_minutes": hold_min,
        "bought_after_range": buys_total > l.buys,
        "partial_history": bool(st.get("first_buy")) and st["first_buy"] < (l.first_buy_t or 0) - 1000,
        "source": "wallet-stats",
    }


def facts(l, supply, price_at_exit):
    """Колонки таблиці з леджера. Капа = ціна × supply."""
    entry_first = (l.first_buy_price or 0) * supply
    entry_avg = (l.invested / l.bought_qty) * supply if l.bought_qty else None
    exit_avg = (l.proceeds / l.sold_qty) * supply if l.sold_qty else None
    sold_share = (l.sold_qty / l.bought_qty * 100) if l.bought_qty else 0.0
    unrealized = (l.qty * price_at_exit - l.cost) if (l.qty > 0 and price_at_exit) else 0.0
    hold_min = None
    entry_t = l.first_range_buy_t if l.first_range_buy_t is not None else l.first_buy_t
    first_sell_after = next((t for t in l.sell_times if entry_t is not None and t >= entry_t), None)
    if first_sell_after is not None:
        hold_min = (first_sell_after - entry_t) / 60_000    # від входу в діапазоні до першого продажу після нього
    return {
        "wallet": l.wallet,
        "first_buy_ms": l.first_buy_t,
        "first_range_buy_ms": l.first_range_buy_t,
        "entry_range_mcap": (l.first_range_buy_price or 0) * supply,
        "bought_before_range": l.buys_before_range > 0,
        "invested_before_range_usd": l.invested_before_range,
        "entry_mcap_first": entry_first,
        "entry_mcap_avg": entry_avg,
        "buys_in_range": l.buys_in_window,
        "invested_in_range_usd": l.invested_in_window,
        "buys": l.buys,
        "invested_usd": l.invested,
        "first_sell_ms": l.first_sell_t,
        "last_sell_ms": l.last_sell_t,
        "exit_mcap_avg": exit_avg,
        "sells": l.sells,
        "proceeds_usd": l.proceeds,
        "sold_share_pct": sold_share,
        "holding_share_pct": max(0.0, 100.0 - sold_share),
        "realized_usd": l.realized,
        "unrealized_usd": unrealized,
        "multiple": (exit_avg / entry_avg) if (exit_avg and entry_avg) else None,
        "hold_minutes": hold_min,
        "bought_after_range": l.buys_after_window > 0,
        "partial_history": (l.sold_without_buy > 0 or l.oversold > 0),
        "source": "trades",
    }


def facts_entry_only(l, supply):
    """Лише вхід (виходи невідомі): для гаманців поза стелею запитів у режимі wallet-stats."""
    f = facts(l, supply, 0)
    for k in ("first_sell_ms", "last_sell_ms", "exit_mcap_avg", "multiple", "hold_minutes"):
        f[k] = None
    for k in ("sells", "proceeds_usd", "sold_share_pct", "realized_usd", "unrealized_usd"):
        f[k] = None
    f["holding_share_pct"] = None
    f["source"] = "entry-only"
    return f
