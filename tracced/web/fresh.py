"""Свіжі пампи для головної: токени, створені за останню добу, які виросли (власник, 30.09): капа ≥ $1M, ліквідність
≥ $80K, пік капи ≥ $2M. Джерело — Solana Tracker: `/search` з фільтрами на його боці (1 запит на сторінку) і
`/tokens/{mint}/ath` (пік, 1 запит на токен, година з пам'яті). Публічні джерела не підійшли (30.09): у «трендах» Jupiter
за добу лише 1 такий токен з 22 свіжих, GeckoTerminal віддає нові пули по 20 — це хвилини, не доба.

Накрутку капи відсікає обіг: у клонів з капою $200M–3.4B і ~3000 холдерів обіг за добу 0.00–0.08 капи, у справжніх
пампів — 0.2–11. «Вічно зростаючі» токени — нуль комісій трейдерів і мало продажів. Тут лише чиста логіка і запити
через переданий клієнт; коли оновлювати — вирішує app.py."""
import time
import urllib.parse

HOUR_MS = 3_600_000


def search_path(now_ms, s, cursor=None):
    """Запит `/search`: свіжі за `fresh_hours`, пороги капи й ліквідності, холдери з угодами — і комісії трейдерів на боці
    Solana Tracker (`minFeesTotal`). Без останнього верх відсортованого за капою списку займають накручені клони
    (232 з 265 токенів мали менше 1 SOL комісій), і справжні пампи випадали за межі двох сторінок по 50 (дослідження 30.09).
    Одна сторінка на 500 — один запит."""
    q = {"minCreatedAt": int(now_ms - float(s.get("fresh_hours", 24)) * HOUR_MS),
         "minMarketCap": int(s.get("fresh_min_mcap", 1_000_000)), "minLiquidity": int(s.get("fresh_min_liquidity", 80_000)),
         "minHolders": int(s.get("fresh_min_holders", 500)), "minTotalTransactions": int(s.get("fresh_min_trades", 1000)),
         "minFeesTotal": float(s.get("fresh_min_fees_sol", 5)),
         "sortBy": "marketCapUsd", "sortOrder": "desc", "limit": int(s.get("fresh_page", 500))}
    if cursor:
        q["cursor"] = cursor
    return "/search?" + urllib.parse.urlencode(q)


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def candidates(rows, s):
    """Рядки `/search` → кандидати. Пороги `/search` перевіряємо ще раз (відповідь чужа) і відсіюємо сміття, якого сервер
    не бачить (дослідження 30.09, 265 токенів за 48 год):
    - обіг за добу не менший за `fresh_min_turnover` капи — накручена капа без торгівлі;
    - комісії трейдерів: не менше `fresh_min_fees_sol` загалом і `fresh_fees_per_musd` SOL на кожен $1M обороту — «мийка»
      обсягу (у мийки максимум 6.8, у справжніх від 17.8);
    - продажів не менше `fresh_min_sell_ratio` від купівель — «вічно зростаючий» графік;
    - капа ÷ ліквідність у межах `fresh_cap_liq` — фальшива капа (180–650) чи пул, у який поклали майже все (1);
    - обіг за останню годину не менший за `fresh_min_vol_1h` — мертвий пул."""
    out, seen = [], set()
    lo, hi = (list(s.get("fresh_cap_liq") or [2, 150]) + [2, 150])[:2]
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("mint") or r["mint"] in seen:
            continue
        cap, liq, vol = _num(r.get("marketCapUsd")), _num(r.get("liquidityUsd")), _num(r.get("volume_24h"))
        if cap < float(s.get("fresh_min_mcap", 1_000_000)) or liq < float(s.get("fresh_min_liquidity", 80_000)):
            continue
        if vol < float(s.get("fresh_min_turnover", 0.2)) * cap:
            continue
        fees = _num((r.get("fees") or {}).get("total")) if isinstance(r.get("fees"), dict) else _num(r.get("fees"))
        buys, sells = _num(r.get("buys")), _num(r.get("sells"))
        if fees < float(s.get("fresh_min_fees_sol", 5)) or (buys and sells < float(s.get("fresh_min_sell_ratio", 0.3)) * buys):
            continue
        if vol and fees < float(s.get("fresh_fees_per_musd", 10)) * vol / 1e6:
            continue
        if liq and not (lo <= cap / liq <= hi):
            continue
        if r.get("volume_1h") is not None and _num(r.get("volume_1h")) < float(s.get("fresh_min_vol_1h", 10_000)):
            continue
        seen.add(r["mint"])
        img = r.get("image") or ""
        out.append({"mint": r["mint"], "symbol": str(r.get("symbol") or "")[:16], "name": str(r.get("name") or "")[:40],
                    "cap": cap, "liq": liq, "vol": vol, "created_ms": int(_num(r.get("createdAt"))),
                    "image": img if img.startswith("https://image.solanatracker.io/") else ""})   # чужі хости (IPFS) бачили б відвідувача
    return out


def pick(cands, peaks, now_ms, s):
    """Кандидати + піки → що показати: пік ≥ `fresh_min_ath`, одна назва — один токен (клон з меншим піком іде), найбільші
    піки першими, до `fresh_show`. Пік не менший за нинішню капу; без відомого піку — лише коли капа сама ≥ порога."""
    need, best = float(s.get("fresh_min_ath", 2_000_000)), {}
    for c in cands:
        peak = max(_num(peaks.get(c["mint"])), c["cap"])
        if peak < need:
            continue
        row = dict(c, peak=peak, age_h=max(0.0, (now_ms - c["created_ms"]) / HOUR_MS) if c["created_ms"] else None,
                   drop=round(100 * (1 - c["cap"] / peak)) if peak else 0)
        k = (c["symbol"] or c["mint"]).lower()
        if k not in best or row["peak"] > best[k]["peak"]:
            best[k] = row
    return sorted(best.values(), key=lambda c: -c["peak"])[: int(s.get("fresh_show", 8))]


def refresh(st, s, peaks, now_ms=None):
    """Один прохід: `/search` (сторінка на 500, друга лише якщо є ще) → кандидати → піки тих, кого ще не питали.
    `peaks` — {mint: (пік, коли дізнались, коли токен створено)}, спільна пам'ять між проходами. Пік лише росте, тож
    питаємо його раз на токен, а далі береться більше з пам'яті й нинішньої капи; невдалий запит пробуємо знову за
    `fresh_ath_retry_min`. Забуваємо токен, коли він старший за вікно плюс добу. Викликати в потоці, під лічильником."""
    now_ms = now_ms or int(time.time() * 1000)
    rows, cursor = [], None
    for _ in range(2):
        d = st._get(search_path(now_ms, s, cursor)) or {}
        rows += d.get("data") or []
        cursor = d.get("nextCursor")
        if not d.get("hasMore") or not cursor:
            break
    cands = candidates(rows, s)[: int(s.get("fresh_max_candidates", 30))]
    retry = float(s.get("fresh_ath_retry_min", 30)) * 60_000
    for c in cands:
        hit = peaks.get(c["mint"])
        if hit and (hit[0] > 0 or now_ms - hit[1] < retry):
            continue
        try:
            a = st._get(f"/tokens/{c['mint']}/ath") or {}
            peaks[c["mint"]] = (_num(a.get("highest_market_cap")), now_ms, c["created_ms"])
        except Exception:  # noqa: BLE001 — без піку токен лишається, якщо капа сама вища за поріг; спроба знову пізніше
            peaks[c["mint"]] = (0.0, now_ms, c["created_ms"])
    horizon = (float(s.get("fresh_hours", 24)) + 24) * HOUR_MS
    for m in [m for m, v in peaks.items() if now_ms - (v[2] if len(v) > 2 and v[2] else v[1]) > horizon]:
        del peaks[m]
    return pick(cands, {m: v[0] for m, v in peaks.items()}, now_ms, s)
