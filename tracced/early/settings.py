"""Налаштування early: дефолти в коді + блок `early:` з config.yaml поверх."""
import copy

from ..config import _deep_merge

DEFAULTS = {
    "scopes": [24, 48],          # масштаби цифр на сторінці: уся історія + стільки годин після діапазону
    # тариф Solana Tracker задає стелі (PLAN_CAPS); явні значення в config.yaml сильніші за тариф
    "plan": "free",
    "max_trade_pages": 300,      # стеля сторінок /trades за один прогін (500 угод/стор.)
    # вікно входу тягнемо завжди повністю (до стількох сторінок); далі рішення budget.choose_mode:
    # повний діапазон або угоди кожного гаманця (до стількох гаманців)
    "max_window_pages": 60,
    "max_wallet_lookups": 500,
    "budget_guard_pct": 25,      # один прогін ≤ стільки % залишку кредитів (0 = вимкнено)
    "full_fetch_margin": 1.15,   # запас до оцінки сторінок повного діапазону
    "pause_s": 0.35,             # пауза між запитами до ST (free: 3 req/s)
    # людські ліміти (показуються як повідомлення, не як «сторінки»)
    "max_window_hours": 24,      # вікно входу не довше
    "wallet_stats_ttl_hours": 24,
    "max_wallet_trade_pages": 4,  # угоди одного гаманця по токену: сторінок по 250 (боти)
    # тег `fresh`: вік гаманця з публічного RPC у фоні після аналізу (0 = вимкнено)
    "age_lookups_max": 300,
    "rpc_pace_s": 0.5,           # пауза між запитами до публічної ноди (ріже серії без пауз)
    "wallet_age_ttl_hours": 168,
    "markers_max": 200,          # мітки угод одного гаманця на графіку
    "example_job": None,         # id аналізу, закріпленого на головній як приклад (None = найстарший готовий)
    "demo_job": None,            # id аналізу-демо: його токен і діапазон програються зі знімка без запитів до ST
    "replay_s": 12,              # скільки секунд триває програвання демо-аналізу в терміналі
    "runs_per_day": 1,           # живих аналізів на добу з гаманця (адмін — без ліміту)
    "runs_per_hour": 20,         # стартів живих аналізів з однієї адреси за годину; наступний чекає годину
    "runs_global_per_day": 10,   # живих аналізів на весь сайт за добу (адмін поза стелею): будь-який ключ підписує безкоштовно
    "ranges_per_token": 3,       # діапазонів (і аналізів) на один токен; видалив свій — місце вільне
    "run_cap_requests": 2000,    # запитів до Solana Tracker на один прогін не-адміна (адмін — без стелі)
    "finder_pumps": 2,           # скільки пампів пропонує «Find the pump»
    # графік живого токена коштує запитів (огляд ≈2, шматок свічок 1), а дивитись його може будь-хто: добові стелі
    "browse_per_day_guest": 30,  # …з однієї адреси без гаманця
    "browse_per_day": 150,       # …з гаманця
    "browse_global_per_day": 300,   # …на весь сайт (адміни поза стелею; кеш безкоштовний)
    "assistant_per_day": 10,     # запитів до AI-агента на добу з гаманця
    "assistant_per_day_guest": 3,   # …і без гаманця (по IP)
    "assistant_global_per_day": 45, # спільна добова стеля (безкоштовний тариф OpenRouter дає 50)
    "min_invested_usd": 20,      # пил: хто вклав менше — у таблицю не потрапляє
    "page_size": 500,            # для оцінки ціни прогону; стільки ж просимо в /trades (стеля API)
    # ціна повного шляху: темп угод у пампі не тримається далі, тому дірку МІРЯЄМО кількома запитами
    "probe_pages": 3,            # скільки сторінок-проб (0 = не міряти, вірити екстраполяції)
    "probe_min_pages": 200,      # міряти, лише коли груба оцінка така велика, що рішення дороге
    # вибір інтервалу свічок за довжиною відрізка (годин); довше — 1h
    "chart_span_hours": {"1m": 6, "5m": 48, "15m": 24 * 14},
    "suggest_peak_hours": 6,     # пік пампу шукаємо стільки годин після старту
}


PLAN_CAPS = {
    "free":     {"max_trade_pages": 300, "max_wallet_lookups": 500, "max_window_pages": 60,
                 "budget_guard_pct": 25, "pause_s": 0.35},
    "advanced": {"max_trade_pages": 2000, "max_wallet_lookups": 3000, "max_window_pages": 400,
                 "budget_guard_pct": 0, "pause_s": 0.05},
}


def load(cfg=None):
    """дефолти → стелі тарифу → явні значення з config.yaml (сильніші за тариф)."""
    over = (cfg or {}).get("early") or {}
    plan = over.get("plan", DEFAULTS["plan"])
    if plan not in PLAN_CAPS:
        raise ValueError(f"early.plan must be one of {sorted(PLAN_CAPS)}, got {plan!r}")
    s = copy.deepcopy(DEFAULTS)
    _deep_merge(s, PLAN_CAPS[plan])
    _deep_merge(s, over)
    return s


def chart_interval(span_ms, s):
    """Найдрібніший інтервал, при якому свічок лишається розумна кількість."""
    hours = span_ms / 3_600_000
    for itv in ("1m", "5m", "15m"):
        lim = (s.get("chart_span_hours") or {}).get(itv)
        if lim and hours <= lim:
            return itv
    return "1h"


INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
