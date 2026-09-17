"""Оркестрація: токен → діапазон входу з сирих угод → гаманці, що купували в ньому → їхні угоди по
токену (уся історія до моменту аналізу) → таблиця за масштабом.

Два шляхи до угод кожного гаманця (обидва — сирі свопи Solana Tracker):
- "trades": уся історія токена від створення до зараз сторінками по 250 — дешево для молодих токенів;
- "wallet-trades": угоди кожного відібраного гаманця окремим запитом (1 запит/гаманець) — для старих
  або дуже активних токенів. Гаманці поза стелею запитів — entry-only (тег no-exits).
Який шлях — вирішує чистий `budget.choose_mode` ПІСЛЯ того, як діапазон витягнуто і кількість гаманців
відома: повний, якщо покриває всіх там, де по-гаманцевий не покрив би, або просто дешевший.
Перед витратами — охоронець квоти (`/credits`). Рядки таблиці рахує `scope.rows_for` з угод, збережених
у результаті, тому масштаб (уся історія / 24 год / 48 год після діапазону) перемикається без запитів.

Усі числа рахують чисті модулі; тут лише порядок кроків, ліміти і журнал ходу.
Повідомлення журналу і помилок — англійською: вони йдуть на сторінку.
"""
import time

from . import budget, ledger, report, scope, window
from .store import PageBudget, TradeStore

HOUR = 3_600_000


class EarlyError(Exception):
    """A reason to stop that a person can read (not a traceback)."""


def token(st, mint):
    info = st.token_info(mint)
    if not info.get("supply"):
        raise EarlyError("Solana Tracker returned no supply for this token, so market cap can't be computed.")
    return info


def overview(st, mint, info, s, cfg=None, now_ms=None):
    """Lifetime candles + pump-detector hints (used for the range suggestions)."""
    from ..config import DEFAULTS
    from .settings import chart_interval
    now_ms = now_ms or int(time.time() * 1000)
    created = info.get("created_time") or (now_ms - 48 * HOUR)
    itv = chart_interval(now_ms - created, s)
    candles = st.chart(mint, itv, created, now_ms)
    detect_cfg = {"detect": dict((cfg or {}).get("detect") or DEFAULTS["detect"])}
    hints = window.suggest(candles, info["supply"], detect_cfg, s.get("suggest_peak_hours", 6))
    return {"interval": itv, "candles": candles, "hints": hints}


def estimate_pages(store, t_from, t_exit, first_page_span_ms, page_size=250):
    """Pages needed for the uncovered gaps if the pace stays as on the first page (a lower bound)."""
    if not first_page_span_ms or first_page_span_ms <= 0:
        return None
    total = sum(b - a for a, b in store.gaps(t_from, t_exit))
    return int(total / first_page_span_ms) + 1


def gap_moment(gaps, frac):
    """Момент на частці `frac` від усього непокритого часу (дірок може бути кілька)."""
    total = sum(b - a for a, b in gaps)
    want = total * max(0.0, min(1.0, frac))
    for a, b in gaps:
        if want <= b - a:
            return int(a + want)
        want -= b - a
    return int(gaps[-1][1])


def probe_rates(fetch, gaps, points):
    """Виміряний темп (угод/с) у кількох точках дірки: по одній сторінці на точку."""
    out = []
    for f in points:
        try:
            ts = (fetch(gap_moment(gaps, f) - 1) or {}).get("trades") or []
        except Exception:  # noqa: BLE001 — проба не має валити прогін
            continue
        if len(ts) < 2:
            continue
        span = (ts[-1]["time"] - ts[0]["time"]) / 1000
        if span > 0:
            out.append((f, len(ts) / span))
    return out


def price_at(st, mint, t_ms):
    """Price at a moment from 5m candles (1 cached request); None if the chart has nothing there."""
    try:
        cs = st.chart(mint, "5m", t_ms - 6 * HOUR, t_ms)
    except Exception:  # noqa: BLE001 — a missing price only affects «unrealized»
        return None
    cs = [c for c in (cs or []) if c.get("time") is not None and c["time"] <= t_ms and c.get("close")]
    return float(cs[-1]["close"]) if cs else None


def _credits(st, log):
    """Credits left on the Solana Tracker key (1 request); None if unknown — then the guard stays silent."""
    try:
        c = st.credits()
    except Exception:  # noqa: BLE001
        c = None
    if c is not None:
        log(f"credits left: {int(c):,}")
    return int(c) if c is not None else None


def run(st, mint, t_from, t_to, s, log=None, store_dir="cache/early",
        max_pages=None, now_ms=None, progress=None):
    log = log or (lambda m: None)
    progress = progress or (lambda phase, done=0, total=None: None)
    now_ms = now_ms or int(time.time() * 1000)
    max_pages = max_pages or s["max_trade_pages"]
    page_size = s.get("page_size", 250)
    guard_pct = int(s.get("budget_guard_pct", 0) or 0)
    req0 = st.requests

    progress("token")
    info = token(st, mint)
    errs = window.validate(t_from, t_to, info.get("created_time"), now_ms,
                           max_window_ms=int(s.get("max_window_hours", 0) * HOUR) or None)
    if errs:
        raise EarlyError(" ".join(errs))
    t_end = now_ms
    created = info.get("created_time") or (t_from - 24 * HOUR)
    log(f"{info.get('symbol') or mint}: supply {info['supply']:,.0f}; range {_iso(t_from)} → {_iso(t_to)} UTC, "
        f"history until {_iso(t_end)}")

    store = TradeStore(store_dir, mint)
    fetch = lambda c: st.trades_page(mint, c)  # noqa: E731
    pages, est_full, est_win = 0, None, 0
    credits = {"seen": None, "at": None}

    def credits_now():
        if credits["seen"] is None:
            return None
        return credits["seen"] - (st.requests - credits["at"])

    def guard(planned):
        if not guard_pct or planned <= 0:
            return
        if credits["seen"] is None:
            credits["seen"] = _credits(st, log)
            credits["at"] = st.requests
        msg = budget.budget_message(planned, credits_now(), guard_pct)
        if msg:
            raise EarlyError(msg)

    # ── 1. діапазон входу: завжди повністю ──
    win_gaps = store.gaps(t_from, t_to)
    if win_gaps:
        ga, gb = win_gaps[0]
        d = st.trades_page(mint, ga - 1)                  # курсор ST виключний: -1, щоб узяти угоди в ga
        pages = 1
        trs = d["trades"]
        store.add(trs)
        last_t = max((tr["time"] for tr in trs if tr["time"] is not None), default=None)
        if trs and last_t:
            store.mark_covered(ga, (last_t - 1) if d["hasNextPage"] else max(gb, last_t))
            span = last_t - min(tr["time"] for tr in trs if tr["time"] is not None)
            est_win = estimate_pages(store, t_from, t_to, span or 1, page_size) or 0
            est_full = estimate_pages(store, created, t_end, span or 1, page_size)
            log(f"first page: {len(trs)} trades over {span / 60000:.0f} min → entry range ≈{est_win + pages} pages, "
                f"whole history ≈{(est_full or 0) + pages} pages")
            if est_win + pages > s["max_window_pages"]:
                raise EarlyError(
                    f"This range alone needs about {est_win + pages} pages of trades (cap "
                    f"{s['max_window_pages']}). Shorten it — what was fetched is kept.")
            guard(est_win)
        else:
            store.mark_covered(ga, gb)
        progress("trades", pages, est_win + pages)
        try:
            pages = store.ensure(t_from, t_to, fetch, s["max_window_pages"], log=log, pages_done=pages,
                                 on_page=lambda n, t: progress("trades", n, max(n, est_win + 1)))
        except PageBudget as e:
            raise EarlyError(
                f"Reached the cap of {e.pages} pages for the entry range; trades up to {_iso(e.covered_to)} UTC "
                f"are cached. Shorten the range or raise the cap and run again.") from e
    else:
        log("entry range is cached — no new requests for it")

    # ── 2. гаманці, що купували в діапазоні ──
    repaired = ledger.repair_quantities(store.trades)     # джерело інколи ламає кількість токенів
    if repaired:
        log(f"{repaired:,} of {len(store.trades):,} trades had a broken token amount from the source — "
            f"repriced at the market rate of their minute (the USD amounts are untouched)")
    win = store.between(t_from, t_to)
    wl, lstats = ledger.build(win, t_from, t_to, t_to)
    early, counts = ledger.classify(wl, t_to, s["min_invested_usd"])
    early.sort(key=lambda l: -l.invested_in_window)
    early_set = {l.wallet for l in early}
    log(f"entry range: {len(win):,} trades · {len(wl):,} buyers · {len(early):,} bought in the range")

    # ── 3. рішення: уся історія токена чи угоди кожного гаманця ──
    gaps = store.gaps(created, t_end)
    gap_ms = sum(b - a for a, b in gaps)
    margin = float(s.get("full_fetch_margin", 1.0))
    cost_full = budget.estimate_gap_pages(len(win), t_to - t_from, gap_ms, page_size, margin)
    n_probe = int(s.get("probe_pages", 0) or 0)
    if gaps and n_probe and cost_full >= int(s.get("probe_min_pages", 200)):
        # темп пампу не тримається наступні години: міряємо дірку, інакше повний шлях виглядає дорожчим, ніж є
        rates = probe_rates(fetch, gaps, budget.probe_points(gap_ms, n_probe))
        measured = budget.pages_from_rates(rates, gap_ms, page_size, margin)
        if measured:
            log(f"measured the rest of the history with {len(rates)} probes: ≈{measured:,} pages "
                f"(the range's pace alone suggested ≈{cost_full:,})")
            cost_full = measured
    lookups_cap = int(s["max_wallet_lookups"])
    choice = budget.choose_mode(cost_full, len(early), budget.Caps(max_pages - pages, lookups_cap))
    mode = choice.mode
    if choice.cost > 0:
        log(f"cheapest complete path: {'whole token history' if mode == 'trades' else 'per-wallet trades'} — {choice.reason}")
        guard(choice.cost + (1 if mode == "wallet-trades" else 0))
    elif mode == "trades":
        log("the whole token history is cached — no new requests")

    # ── 4. угоди кожного відібраного гаманця ──
    wallet_trades, counts_extra = {}, {}
    if mode == "trades" and choice.cost > 0:
        pages_before = pages
        try:
            pages = store.ensure(created, t_end, fetch, max_pages, log=log, pages_done=pages,
                                 on_page=lambda n, t: progress("trades", n, max(n, pages_before + cost_full)))
        except PageBudget as e:
            log(f"the history is denser than estimated: cap {e.pages} pages reached at {_iso(e.covered_to)} UTC — "
                f"switching to per-wallet trades (fetched pages stay cached)")
            pages = e.pages
            mode = "wallet-trades"
            n_look = min(len(early), lookups_cap)
            choice = budget.Choice("wallet-trades", n_look, n_look, len(early), cost_full, "fallback after the page cap")
            guard(n_look + 1)
    price_end = price_at(st, mint, t_end)
    if mode == "trades":
        by_wallet = {}
        for tr in store.between(created, t_end):
            if tr.get("wallet") in early_set:
                by_wallet.setdefault(tr["wallet"], []).append(tr)
            if tr.get("price") and (price_end is None):
                pass
        if price_end is None:
            price_end = next((tr["price"] for tr in reversed(store.between(created, t_end)) if tr.get("price")), None)
        for l in early:
            wallet_trades[l.wallet] = {"trades": scope.pack(by_wallet.get(l.wallet, [])), "source": "trades"}
        counts_extra = {"lookups": 0, "entry_only": 0}
        covered = len(early)
    else:
        lookups, rest = early[:lookups_cap], early[lookups_cap:]
        log(f"fetching each wallet's trades for {len(lookups)}"
            + (f", {len(rest)} left entry-only (cap {lookups_cap})" if rest else ""))
        n_ok, last_seen = 0, (0, None)
        progress("wallets", 0, len(lookups))
        for i, l in enumerate(lookups, 1):
            try:
                wt = [tr for tr in st.wallet_token_trades(l.wallet, mint, s.get("max_wallet_trade_pages", 4))
                      if tr["time"] is not None and tr["time"] <= t_end]
                for tr in wt:
                    if tr.get("price") and tr["time"] > last_seen[0]:
                        last_seen = (tr["time"], tr["price"])
                ledger.repair_quantities(wt, ref=ledger.price_reference(store.trades) if store.trades else None)
                wallet_trades[l.wallet] = {"trades": scope.pack(wt), "source": "wallet-trades"}
                n_ok += 1
            except Exception as e:  # noqa: BLE001 — one wallet must not sink the run
                log(f"  {l.wallet[:8]}…: trades unavailable ({str(e)[:60]})")
                wallet_trades[l.wallet] = {"trades": scope.pack([tr for tr in win if tr["wallet"] == l.wallet]), "source": "entry-only"}
            if i % 25 == 0:
                log(f"  exits: {i}/{len(lookups)}")
                st.flush()
            progress("wallets", i, len(lookups))
        for l in rest:
            wallet_trades[l.wallet] = {"trades": scope.pack([tr for tr in win if tr["wallet"] == l.wallet]), "source": "entry-only"}
        if price_end is None and last_seen[1]:
            price_end = last_seen[1]
        counts_extra = {"lookups": n_ok, "entry_only": len(early) - n_ok}
        covered = n_ok

    # ── 5. таблиця за масштабом «уся історія» ──
    progress("tags")
    st.flush()
    coverage = {"exits_known": covered, "total": len(early), "mode": mode, "cost_full": cost_full,
                "lookups": counts_extra.get("lookups", 0), "entry_only": counts_extra.get("entry_only", 0),
                "lookup_cap": lookups_cap, "plan": s.get("plan", "free"), "credits_left": credits_now(),
                "repaired_trades": repaired}
    result = {
        "info": info,
        "window": {"from": t_from, "to": t_to, "end": t_end},
        "mode": mode,
        "est_pages": est_full,
        "counts": counts,
        "coverage": coverage,
        "wallet_trades": wallet_trades,
        "price_at_end": price_end,
        "fresh_wallets": [],
        "scope": "all",
        "requests": st.requests - req0,
        "pages_fetched": pages,
        "generated_ms": now_ms,
    }
    rows, sm = scope.rows_for(result, "all", s)
    result["rows"], result["summary"] = rows, sm
    counts.update(n_trades=lstats["n_trades"], n_early=len(rows), n_wallets=len(wl), **counts_extra)
    log(f"done ({mode}): {len(rows)} wallets bought in the range; {report.coverage_text(coverage)}; "
        f"requests {result['requests']}")
    progress("done", 1, 1)
    return result


def _iso(ms):
    from ..util import iso_ms
    return iso_ms(ms)
