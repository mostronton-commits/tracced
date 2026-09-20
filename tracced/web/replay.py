"""Демо-реплей: термінал показує, як виглядає справжній аналіз, але кожне число — зі збереженого результату.

Записаний журнал демо короткий (кеш, 3 запити), тож просто програти його нудно. Натомість збираємо
послідовність тих самих рядків, що пише конвеєр (сторінки угод → діапазон → шлях → виходи → теги → done),
з чисел результату: скільки угод, гаманців, сторінок, які теги. Нічого не вигадуємо: сума «+new» по
сторінках дорівнює кількості угод, часи монотонні між межами діапазону, запити — лише якщо вони записані.
Детерміновано і без мережі; фази рівно ті, що знає term.js: token · trades · wallets · tags · done.
"""
import math
import time
from collections import Counter

from ..early import report

PHASES = ("token", "trades", "wallets", "tags", "done")
TAG_ORDER = ("sniper", "fresh", "bundle", "bot-like", "pre-range", "re-bought", "no-exits")


def _utc(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime((ms or 0) / 1000))


def _short(ms):
    return time.strftime("%m-%d %H:%M", time.gmtime((ms or 0) / 1000))


def _split(total, k):
    """total цілих на k частин, остання добирає остачу; нулів не буває, поки total ≥ k."""
    base, rem = divmod(int(total), k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def replay_lines(result, t_from, t_to, page_size=250, budget_s=12.0, max_pages=12):
    """→ [(рядок або None, фаза, done, total, пауза_с)], у порядку показу."""
    info, counts, cov = result.get("info") or {}, result.get("counts") or {}, result.get("coverage") or {}
    sym = info.get("symbol") or "token"
    supply = float(info.get("supply") or 0)
    n_trades = int(counts.get("n_trades") or 0)
    n_wallets = int(counts.get("n_wallets") or 0)
    n_early = int(counts.get("n_early") or 0)
    end = (result.get("window") or {}).get("end") or t_to
    mode = result.get("mode") or cov.get("mode") or "trades"
    requests = result.get("requests")
    pages = max(1, math.ceil(n_trades / max(1, int(page_size))))
    k = min(pages, max_pages)
    tagc = Counter(t for r in (result.get("rows") or []) for t in (r.get("tag_list") or []))
    exits_total = int(cov.get("total") or n_early)
    exits_known = int(cov.get("exits_known") or exits_total)

    # бюджет часу за вагами: заголовок 1 · сторінки 4 · діапазон і шлях 1 · виходи 3.5 · теги 1 · done 1.5 = 12
    u = float(budget_s) / 12.0
    out = []
    out.append((f"{sym}: supply {supply:,.0f}; range {_utc(t_from)} → {_utc(t_to)} UTC, history until {_utc(end)}",
                "token", 0, None, 0.6 * u))
    out.append((f"first page: {min(n_trades, page_size):,} trades → entry range ≈{pages:,} page{'s' if pages != 1 else ''}",
                "token", 0, None, 0.4 * u))

    # сторінки угод: k рядків, разом рівно n_trades; час рухається від from до to
    cum = 0
    for i, new in enumerate(_split(n_trades, k), 1):
        cum += new
        p_lo = round((i - 1) * pages / k) + 1
        p_hi = round(i * pages / k)
        upto = t_from + (t_to - t_from) * (cum / n_trades if n_trades else 1)
        head = f"page {p_hi}" if p_hi <= p_lo else f"pages {p_lo}–{p_hi}"
        out.append((f"{head}: {new:,} trades (+{new:,} new), up to {_short(upto)}", "trades", p_hi, pages, 4.0 * u / k))

    out.append((f"entry range: {n_trades:,} trades · {n_wallets:,} buyers · {n_early:,} bought in the range",
                "trades", pages, pages, 0.5 * u))
    path = "whole token history" if mode == "trades" else "each wallet's own trades"
    cost = f"{int(requests):,} request{'s' if int(requests) != 1 else ''}" if requests else "cached"
    out.append((f"cheapest complete path: {path} — {cost}", "trades", pages, pages, 0.5 * u))

    # виходи: до 7 кроків; у режимі повної історії рядок каже, звідки вони
    steps = min(7, max(1, exits_known))
    for i, done in enumerate(_split(exits_known, steps), 1):
        cum_done = sum(_split(exits_known, steps)[:i])
        line = (f"exits from the full history: {cum_done:,}/{exits_total:,} wallets" if mode == "trades"
                else f"  exits: {cum_done}/{exits_total}")
        out.append((line, "wallets", cum_done, exits_total, 3.5 * u / steps))

    shown = [f"{t} {tagc[t]:,}" for t in TAG_ORDER if tagc.get(t)]
    out.append(("tags: " + (" · ".join(shown) if shown else "none"), "tags", 0, None, 1.0 * u))
    out.append((f"done ({mode}): {n_early:,} wallets bought in the range; {report.coverage_text(cov) or 'exits from the result'}; "
                f"requests {int(requests):,}" if requests else
                f"done ({mode}): {n_early:,} wallets bought in the range; {report.coverage_text(cov) or 'exits from the result'}; cached",
                "done", 1, 1, 1.5 * u))
    return out


def play(job, result, t_from, t_to, page_size=250, budget_s=12.0, sleep=time.sleep):
    """Програти на живому Job: рядки в журнал, фази в прогрес, паузи між ними."""
    for line, phase, done, total, pause in replay_lines(result, t_from, t_to, page_size=page_size, budget_s=budget_s):
        if line:
            job.log.append(line)
        job.set_progress(phase, done, total)
        sleep(pause)
    return result
