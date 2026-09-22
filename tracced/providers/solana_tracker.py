"""Реализация источника на Solana Tracker Data API. Эндпоинты проверены живьём."""
import time
import urllib.error
import urllib.parse

from .base import PumpDataSource
from ..util import http_get_json, to_ms

BASE = "https://data.solanatracker.io"


def _usd(v):
    """Поля ST вида {usd, quote} → берём usd; если уже число — как есть."""
    if isinstance(v, dict):
        return v.get("usd")
    return v


class SolanaTracker(PumpDataSource):
    def __init__(self, api_key, pause=0.35, retries=3, cache=None):
        self.h = {"x-api-key": api_key}
        self.pause = pause          # ~3 req/s — лимит free-тарифа
        self.retries = retries
        self.requests = 0
        self.cache_hits = 0
        self.cache = cache
        self._last = 0.0

    def flush(self):
        if self.cache:
            self.cache.flush()

    def credits(self):
        """Остаток кредитов ST (free-план ~10k/мес). None при ошибке."""
        try:
            return self._get("/credits").get("credits")
        except Exception:
            return None

    def _get(self, path):
        wait = self.pause - (time.monotonic() - self._last)  # держим темп ≤3 req/s
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        last = None
        for attempt in range(self.retries):
            try:
                return http_get_json(BASE + path, self.h)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:
                    time.sleep(1.5 * (attempt + 1))  # лимит — ждём подольше
                    continue
                if e.code in (500, 502, 503, 504):
                    time.sleep(0.4 * (attempt + 1))  # серверный сбой — короткий повтор
                    continue
                raise
            except urllib.error.URLError as e:
                last = e
                time.sleep(1.0 * (attempt + 1))       # сетевой сбой — повтор
        raise last

    def token_info(self, mint):
        d = self._get(f"/tokens/{mint}")
        tok = d.get("token", {}) or {}
        pools = d.get("pools") or [{}]
        p = pools[0] or {}
        # усе нижче приходить у тій самій відповіді, за яку ми вже заплатили — окремих запитів нема
        return {
            "mint": mint,
            "symbol": tok.get("symbol"),
            "name": tok.get("name"),
            "created_time": to_ms((tok.get("creation") or {}).get("created_time")),
            "supply": (p.get("tokenSupply") or 0) or None,
            "price_usd": (p.get("price") or {}).get("usd"),
            "mcap": _usd(p.get("marketCap")),
            "liquidity_usd": (p.get("liquidity") or {}).get("usd"),
            "deployer": p.get("deployer"),              # гаманець, який створив пул: тег `dev`, якщо він купував
            "launchpad": tok.get("createdOn"),          # де запущено (pump.fun тощо)
            "market": p.get("market"),                  # на якій біржі пул
            "twitter": tok.get("twitter"),
            "website": tok.get("website"),
            "holders": d.get("holders"),
            "txns": d.get("txns"),
            "buys": d.get("buys"),
            "sells": d.get("sells"),
        }

    def trades_iter(self, mint, max_pages=40):
        cursor = None
        pages = 0
        while pages < max_pages:
            path = f"/trades/{mint}?sortDirection=ASC"
            if cursor:
                path += f"&cursor={cursor}"
            d = self._get(path)
            pages += 1
            for tr in d.get("trades", []) or []:
                yield {
                    "wallet": tr.get("wallet"),
                    "type": tr.get("type"),
                    "time": to_ms(tr.get("time")),
                    "volume_usd": tr.get("volume"),
                    "price_usd": tr.get("priceUsd"),
                    "program": tr.get("program"),
                }
            if not d.get("hasNextPage"):
                break
            cursor = d.get("nextCursor")

    def trades_window(self, mint, t_from, t_to, max_pages=40):
        """Сделки в окне [t_from..t_to] (мс): курсор стартует с t_from, идём ASC до t_to.
        Дёшево для токенов, где окно далеко от момента создания."""
        cursor = int(t_from)
        pages = 0
        while pages < max_pages:
            path = f"/trades/{mint}?sortDirection=ASC&cursor={cursor}"
            d = self._get(path)
            pages += 1
            for tr in d.get("trades", []) or []:
                t = to_ms(tr.get("time"))
                if t is not None and t > t_to:
                    return
                yield {
                    "wallet": tr.get("wallet"),
                    "type": tr.get("type"),
                    "time": t,
                    "volume_usd": tr.get("volume"),
                    "price_usd": tr.get("priceUsd"),
                    "program": tr.get("program"),
                }
            if not d.get("hasNextPage"):
                break
            cursor = d.get("nextCursor")

    def price_series(self, mint, interval="5m", t_from=None, t_to=None):
        """Свечи графика → [(time_ms, close, volume)] по возрастанию времени."""
        params = {"type": interval}
        if t_from:
            params["time_from"] = int(t_from)
        if t_to:
            params["time_to"] = int(t_to)
        d = self._get(f"/chart/{mint}?" + urllib.parse.urlencode(params))
        out = []
        for c in (d.get("oclhv") or d.get("data") or []):
            t = to_ms(c.get("time"))
            close = c.get("close")
            if t and close:
                out.append((t, close, c.get("volume")))
        out.sort()
        return out

    def wallet_stats(self, wallet):
        if self.cache is not None:
            cached = self.cache.get(wallet)
            if cached is not None:
                self.cache_hits += 1          # запрос сэкономлен
                return cached
        d = self._get(f"/pnl/{wallet}")
        s = d.get("summary", {}) or {}
        toks = d.get("tokens")
        ntok = len(toks) if isinstance(toks, (dict, list)) else None
        stats = {
            "winrate": (s.get("winPercentage") or 0) / 100.0,
            "total_pnl_usd": s.get("total"),
            "total_invested_usd": s.get("totalInvested"),   # «депозит» — развёрнутый капитал
            "positions": (s.get("totalWins") or 0) + (s.get("totalLosses") or 0),
            "distinct_tokens": ntok,
        }
        if self.cache is not None:
            self.cache.put(wallet, stats)
        return stats

    def discover_tokens(self, scan_cfg):
        """Свежие токены с mcap≥порога через /search (фильтры по дате и капитализации)."""
        now_ms = int(time.time() * 1000)
        min_created = now_ms - scan_cfg["max_age_hours"] * 3_600_000
        params = {
            "minCreatedAt": min_created,
            "minMarketCap": scan_cfg["min_mcap"],
            "sortBy": "createdAt",
            "sortOrder": "desc",
            "limit": 100,
        }
        if scan_cfg.get("max_mcap"):
            params["maxMarketCap"] = scan_cfg["max_mcap"]
        d = self._get("/search?" + urllib.parse.urlencode(params))
        out = []
        for it in (d.get("data") or []):
            mc = it.get("marketCapUsd")
            ct = it.get("createdAt")
            mint = it.get("mint")
            if not mc or not ct or not mint:
                continue
            out.append({
                "mint": mint,
                "symbol": it.get("symbol"),
                "mcap": round(mc),
                "age_hours": round((now_ms - ct) / 3_600_000, 1),
                "link": f"https://www.solanatracker.io/tokens/{mint}",
            })
        out.sort(key=lambda r: r["age_hours"])
        return out
