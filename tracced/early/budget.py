"""Повні дані найдешевшим шляхом: чисте рішення «повний діапазон чи угоди кожного гаманця».

Після того, як вікно входу витягнуто, ми знаємо точну кількість ранніх гаманців (n_early) і можемо
оцінити, скільки сторінок коштує решта діапазону до горизонту (cost_full). Два шляхи дають ті самі
факти про виходи: повний діапазон (усі угоди токена) або угоди кожного гаманця окремо (1 запит на
гаманець). Правило: беремо повний шлях, якщо він влазить у стелю і або покриває всіх там, де
по-гаманцевий шлях не покрив би (стеля гаманців), або просто дешевший. Повнота важливіша за ціну.

Охоронець квоти: один прогін не має з'їдати більше за частку залишку кредитів (free-тариф 2 500/міс).
Ніякого вводу-виводу тут немає — усе рахується з чисел, які передає pipeline.
"""
import math
from typing import NamedTuple, Optional


class Caps(NamedTuple):
    pages_left: int        # скільки сторінок ще можна витратити в цьому прогоні
    lookups: int           # стеля гаманців для по-гаманцевого шляху


class Choice(NamedTuple):
    mode: str              # "trades" | "wallet-trades"
    cost: int              # запитів на обраний шлях (оцінка)
    covered: int           # для скількох гаманців будуть відомі виходи
    total: int             # n_early
    cost_full: int         # ціна повного шляху (для пояснення людині)
    reason: str            # коротке пояснення для журналу


def choose_mode(cost_full, n_early, caps):
    """Найдешевший з ПОВНИХ шляхів; якщо повний не влазить — по-гаманцевий для min(n_early, стеля)."""
    cost_full = max(0, int(cost_full))
    n_early = max(0, int(n_early))
    n_look = max(0, min(n_early, int(caps.lookups)))
    full_fits = cost_full <= int(caps.pages_left)
    wallets_complete = n_look >= n_early
    if n_early == 0:
        return Choice("wallet-trades", 0, 0, 0, cost_full, "no early wallets")
    if full_fits and not wallets_complete:
        return Choice("trades", cost_full, n_early, n_early, cost_full,
                      f"full range ≈{cost_full} pages covers everyone; per-wallet would cover only {n_look} of {n_early}")
    if full_fits and cost_full <= n_early:
        return Choice("trades", cost_full, n_early, n_early, cost_full,
                      f"full range ≈{cost_full} pages is cheaper than {n_early} per-wallet lookups")
    if wallets_complete:
        return Choice("wallet-trades", n_look, n_look, n_early, cost_full,
                      f"{n_early} per-wallet lookups are cheaper than ≈{cost_full} pages")
    return Choice("wallet-trades", n_look, n_look, n_early, cost_full,
                  f"full range ≈{cost_full} pages is over the cap ({caps.pages_left} left); per-wallet covers {n_look} of {n_early}")


def estimate_gap_pages(n_window_trades, window_ms, gap_ms, page_size=250, margin=1.0):
    """Сторінок на непокриту дірку при щільності угод, як у вікні (нижня оцінка з запасом margin)."""
    if gap_ms <= 0:
        return 0
    if window_ms <= 0 or n_window_trades <= 0:
        return 1
    return max(1, math.ceil(gap_ms * (n_window_trades / page_size) / window_ms * margin))


def budget_message(planned, credits_left, pct):
    """None — можна витрачати; інакше речення для людини, чому прогін зупинено до витрат."""
    if not pct or credits_left is None or planned <= 0:
        return None
    allowed = int(credits_left * pct / 100)
    if planned <= allowed:
        return None
    return (f"This range would take about {planned:,} requests, but one run may use {allowed:,} of the "
            f"{credits_left:,} left this month. Shorten the range or raise the limit in config.yaml.")
