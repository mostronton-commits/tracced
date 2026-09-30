"""Свіжі пампи для головної: токени, створені за останню добу, які виросли (власник, 30.09): капа ≥ $1M, ліквідність
≥ $80K, пік капи ≥ $2M. Джерело — Solana Tracker: `/search` з фільтрами на його боці (1 запит на сторінку) і
`/tokens/{mint}/ath` (пік, 1 запит на токен, година з пам'яті). Публічні джерела не підійшли (30.09): у «трендах» Jupiter
за добу лише 1 такий токен з 22 свіжих, GeckoTerminal віддає нові пули по 20 — це хвилини, не доба.

Накрутку капи відсікає обіг: у клонів з капою $200M–3.4B і ~3000 холдерів обіг за добу 0.00–0.08 капи, у справжніх
пампів — 0.2–11. Тут лише чиста логіка і запити через переданий клієнт; коли оновлювати — вирішує app.py."""
import time
import urllib.parse

HOUR_MS = 3_600_000


def search_path(now_ms, s, cursor=None):
    """Запит `/search`: свіжі за `fresh_hours`, пороги капи й ліквідності, і холдери з угодами — без них верх списку
    займають «токени» з одним холдером і нулем угод (перевірено 28.09)."""
    q = {"minCreatedAt": int(now_ms - float(s.get("fresh_hours", 24)) * HOUR_MS),
         "minMarketCap": int(s.get("fresh_min_mcap", 1_000_000)), "minLiquidity": int(s.get("fresh_min_liquidity", 80_000)),
         "minHolders": int(s.get("fresh_min_holders", 500)), "minTotalTransactions": int(s.get("fresh_min_trades", 1000)),
         "sortBy": "marketCapUsd", "sortOrder": "desc", "limit": 50}
    if cursor:
        q["cursor"] = cursor
    return "/search?" + urllib.parse.urlencode(q)


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def candidates(rows, s):
    """Рядки `/search` → кандидати: обіг за добу не менший за `fresh_min_turnover` капи, без дублів адрес. Пороги
    `/search` перевіряємо ще раз: відповідь чужа."""
    out, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("mint") or r["mint"] in seen:
            continue
        cap, liq, vol = _num(r.get("marketCapUsd")), _num(r.get("liquidityUsd")), _num(r.get("volume_24h"))
        if cap < float(s.get("fresh_min_mcap", 1_000_000)) or liq < float(s.get("fresh_min_liquidity", 80_000)):
            continue
        if vol < float(s.get("fresh_min_turnover", 0.2)) * cap:
            continue
        seen.add(r["mint"])
        img = r.get("image") or ""
        out.append({"mint": r["mint"], "symbol": str(r.get("symbol") or "")[:16], "name": str(r.get("name") or "")[:40],
                    "cap": cap, "liq": liq, "vol": vol, "created_ms": int(_num(r.get("createdAt"))),
                    "image": img if img.startswith("https://image.solanatracker.io/") else ""})   # чужі хости (IPFS) бачили б відвідувача
    return out


def pick(cands, peaks, now_ms, s):
    """Кандидати + піки → що показати: пік ≥ `fresh_min_ath`, найбільші піки першими, до `fresh_show`. Пік не менший за
    нинішню капу (пам'ять піків годинна, токен міг вирости за цей час); без відомого піку — лише коли капа сама ≥ порога."""
    need, out = float(s.get("fresh_min_ath", 2_000_000)), []
    for c in cands:
        peak = max(_num(peaks.get(c["mint"])), c["cap"])
        if peak < need:
            continue
        out.append(dict(c, peak=peak, age_h=max(0.0, (now_ms - c["created_ms"]) / HOUR_MS) if c["created_ms"] else None,
                        drop=round(100 * (1 - c["cap"] / peak)) if peak else 0))
    out.sort(key=lambda c: -c["peak"])
    return out[: int(s.get("fresh_show", 8))]


def refresh(st, s, peaks, now_ms=None):
    """Один прохід: `/search` (до 2 сторінок) → кандидати → піки тих, чий пік невідомий чи старший за `fresh_ath_ttl_min`.
    `peaks` — {mint: (пік, коли дізнались)}, спільна пам'ять між проходами; оновлюється на місці. Повертає список для
    сторінки. Викликати в потоці, під лічильником запитів."""
    now_ms = now_ms or int(time.time() * 1000)
    rows, cursor = [], None
    for _ in range(2):
        d = st._get(search_path(now_ms, s, cursor)) or {}
        rows += d.get("data") or []
        cursor = d.get("nextCursor")
        if not d.get("hasMore") or not cursor:
            break
    cands = candidates(rows, s)[: int(s.get("fresh_max_candidates", 20))]
    ttl = float(s.get("fresh_ath_ttl_min", 60)) * 60_000
    for c in cands:
        hit = peaks.get(c["mint"])
        if hit and now_ms - hit[1] < ttl:
            continue
        try:
            a = st._get(f"/tokens/{c['mint']}/ath") or {}
            peaks[c["mint"]] = (_num(a.get("highest_market_cap")), now_ms)
        except Exception:  # noqa: BLE001 — без піку токен лишається, якщо капа сама вища за поріг
            continue
    for m in [m for m, (_, at) in peaks.items() if now_ms - at > 48 * HOUR_MS]:
        del peaks[m]                                    # токени старші за добу сюди вже не потраплять
    return pick(cands, {m: p for m, (p, _) in peaks.items()}, now_ms, s)
