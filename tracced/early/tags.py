"""Теги-факти по гаманцю на цьому токені. Кожен тег має визначення, яке показуємо людині в підказці.

Це не оцінки і не чужі мітки: кожен тег виводиться з чисел, які вже стоять у таблиці або з блокчейну,
і людина може перевірити чи оскаржити його. Порядок у DEFS = порядок показу.
"""
import statistics

SEC = 1000
MIN = 60_000
HOUR = 3_600_000

DEFS = {
    "dev":        "The wallet that created the token's pool",
    "sniper":     "Bought within 60 s of token creation",
    "fresh":      "Wallet younger than 24 h at its first buy",
    "bot-like":   "30+ trades with a median hold under 2 min, or 5+ buy→sell pairs within 5 s",
    "pre-range":  "Also bought before the range",
    "transfer-in": "Sold more than it was ever seen buying — the rest arrived another way, usually a transfer",
    "re-bought":  "Bought again after the range",
    "bundle":     "First SOL from the same wallet as 2+ others here — likely one operator. From an exchange or an app (1,000+ transactions a day) only when the wallets were created together, within 30 min",
    "no-exits":   "Exits not fetched (over the cap)",
    "seen-before": "Also an early buyer in another analysis you saved — shown as a chain link, click it for the list",
}
BUNDLE_MIN = 3        # стільки гаманців списку з одним спонсором = бандл
BURST_MS = 30 * 60_000   # від біржі чи застосунку — лише гаманці, народжені за пів години один від одного
BUNDLE_REV = 3        # версія правила бандлів: результат зі старшою перераховує їх при запуску (без нових перевірок віку)

SNIPER_MS = 60 * SEC
FRESH_MS = 24 * HOUR
BOT_TRADES = 30
BOT_HOLD_MIN = 2.0
BOT_PAIRS = 5
PAIR_MS = 5 * SEC


def is_fresh(first_buy_ms, age):
    """`fresh` за фактом віку: найстаріша транзакція ≤ 24 год до першої покупки тут (лише точний вік)."""
    if not age or not age.get("exact") or not age.get("oldest_ms") or not first_buy_ms:
        return False
    return 0 <= first_buy_ms - age["oldest_ms"] <= FRESH_MS


def could_be_fresh(first_buy_ms, age):
    """Чи може гаманець ще виявитись `fresh`. Точний вік відповідає сам. Неточний (прочитано лише найновішу частину
    історії) каже «ні», коли навіть найстаріша прочитана транзакція була більш як за добу до першої покупки: перша
    транзакція гаманця ще старша. Інакше — «може», і вік треба дочитати."""
    if not age or not age.get("oldest_ms") or not first_buy_ms:
        return False
    if age.get("exact"):
        return is_fresh(first_buy_ms, age)
    return first_buy_ms - age["oldest_ms"] <= FRESH_MS


def with_tag(tag_list, tag):
    """Список тегів у порядку DEFS з доданим тегом."""
    have = set(tag_list or []) | {tag}
    return [t for t in DEFS if t in have]


def median_hold_minutes(buy_times, sell_times):
    """Медіана «продаж − найближча попередня покупка» у хвилинах; None, якщо нема пар."""
    if not buy_times or not sell_times:
        return None
    buys = sorted(buy_times)
    holds = []
    for t in sorted(sell_times):
        prev = [b for b in buys if b <= t]
        if prev:
            holds.append((t - prev[-1]) / MIN)
    return statistics.median(holds) if holds else None


def quick_pairs(buy_times, sell_times, within_ms=PAIR_MS):
    """Скільки продажів сталося в межах within_ms після якоїсь покупки."""
    buys = sorted(buy_times)
    n = 0
    for t in sell_times:
        if any(0 <= t - b <= within_ms for b in buys):
            n += 1
    return n


def compute(f, created_ms=None, buy_times=(), sell_times=(), wallet_first_tx_ms=None):
    """Список тегів для рядка фактів `f` (див. ledger.facts)."""
    out = []
    fb = f.get("first_buy_ms")
    if fb and created_ms and 0 <= fb - created_ms <= SNIPER_MS:
        out.append("sniper")
    if fb and wallet_first_tx_ms and 0 <= fb - wallet_first_tx_ms <= FRESH_MS:
        out.append("fresh")
    trades = (f.get("buys") or 0) + (f.get("sells") or 0)
    hold = median_hold_minutes(buy_times, sell_times)
    if hold is None:
        hold = f.get("hold_minutes")
    botlike = (trades >= BOT_TRADES and hold is not None and hold < BOT_HOLD_MIN) or \
              (quick_pairs(buy_times, sell_times) >= BOT_PAIRS)
    if botlike:
        out.append("bot-like")
    if f.get("bought_before_range"):
        out.append("pre-range")
    if f.get("partial_history"):
        out.append("transfer-in")      # продав більше, ніж купував: решта прийшла переказом, а не з біржі
    if f.get("bought_after_range"):
        out.append("re-bought")
    if f.get("source") == "entry-only":
        out.append("no-exits")
    return out
