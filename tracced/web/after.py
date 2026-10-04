"""«Що було після алерту» (власник, 04.10: «реалізуй, як бачиш, я потім поправлю»).

Для гаманців з дзвіночком: кожна їхня перша покупка токена за останні DAYS днів і що токен зробив далі, від ціни
цієї покупки:
- пік — найвища ціна за HOURS годин після неї (і через скільки);
- просідання — найнижча ціна до того піку: чи витримав би її той, хто купив слідом;
- зараз — остання ціна (для старших покупок — на HOURS-й годині);
- його вихід — середня ціна його продажів після покупки і яку частку купленого він продав.

Угоди беремо з 30 днів гаманця (картка, кеш на добу), ціни — зі свічок токена (5 хв). Покупки рахуються з угод, а не з
надісланих повідомлень: на чорновику бот не працює, а на сайті так видно й те, що було, поки дзвіночок мовчав
(менше мінімуму в $, ліміт за добу). Усе тут чисте: без мережі, тестується на фікстурах.
"""
import statistics

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
DAYS = 7
HOURS = 24
STEP = 5 * MIN                      # свічки по 5 хвилин: доба — 288 свічок, один запит
DOUBLED = 2.0


def moments(card, wallet, now_ms, days=DAYS):
    """Перші покупки токенів за останні `days` днів: [{wallet, mint, symbol, t, price, usd, new}]. `new` — до цього в
    30 днях гаманця покупок цього токена не було (повідомлення сказало б 🆕, а не «bought more»)."""
    out, since = [], now_ms - days * DAY
    for tok in (card or {}).get("recent") or []:
        buys = [x for x in tok.get("trades") or [] if len(x) >= 5 and x[1] == "b" and x[4]]
        first = next((x for x in buys if x[0] >= since), None)
        if not first:
            continue
        out.append({"wallet": wallet, "mint": tok.get("mint"), "symbol": tok.get("symbol"), "t": int(first[0]),
                    "price": float(first[4]), "usd": float(first[2] or 0), "new": not any(x[0] < first[0] for x in buys)})
    return out


def outcome(m, candles, trades, now_ms, hours=HOURS):
    """Що було після покупки `m`. candles — [{time, high, low, close}] у тих самих одиницях, що й ціна покупки ($ за
    токен); свічка, в якій сталася покупка, не береться: її максимум міг бути до неї. trades — угоди гаманця на цьому
    токені [час, b|s, $, кількість, ціна]."""
    t0, p0 = m["t"], m["price"]
    end = min(now_ms, t0 + hours * HOUR)
    cs = [c for c in candles or [] if t0 < c.get("time", 0) <= end and c.get("high") and c.get("low")]
    out = {"peak_x": None, "peak_min": None, "dip_x": None, "now_x": None, "at_end": end < now_ms,
           "exit_x": None, "exit_min": None, "sold_pct": None}
    if p0 and cs:
        top = max(cs, key=lambda c: float(c["high"]))
        out["peak_x"] = round(float(top["high"]) / p0, 2)
        out["peak_min"] = max(0, round((top["time"] + STEP / 2 - t0) / MIN))
        low = min(float(c["low"]) for c in cs if c["time"] <= top["time"])
        out["dip_x"] = round(low / p0, 2) if low < p0 else None
        last = cs[-1]
        out["now_x"] = round(float(last.get("close") or last["high"]) / p0, 2)
    bought = sum(float(x[3] or 0) for x in trades or [] if x[1] == "b" and x[0] >= t0)
    sells = [x for x in trades or [] if x[1] == "s" and x[0] > t0 and x[3] and x[4]]
    if p0 and sells:
        qty = sum(float(x[3]) for x in sells)
        out["exit_x"] = round(sum(float(x[3]) * float(x[4]) for x in sells) / qty / p0, 2)
        out["exit_min"] = round((sells[0][0] - t0) / MIN)
        out["sold_pct"] = min(100, round(100 * qty / bought)) if bought else None
    return out


def summary(rows):
    """Підсумок над таблицею: скільки покупок, медіана піку, скільки подвоїлись, медіана його виходу і «зараз»."""
    med = lambda v: round(statistics.median(v), 2) if v else None
    peaks = [r["peak_x"] for r in rows if r.get("peak_x")]
    exits = [r["exit_x"] for r in rows if r.get("exit_x")]
    nows = [r["now_x"] for r in rows if r.get("now_x")]
    return {"n": len(rows), "peak": med(peaks), "doubled": sum(1 for p in peaks if p >= DOUBLED), "priced": len(peaks),
            "exit": med(exits), "exits": len(exits), "now": med(nows)}
