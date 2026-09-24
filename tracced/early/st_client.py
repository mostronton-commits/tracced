"""Клієнт Solana Tracker для early: сирі сторінки угод (з кількістю) і свічки з відрізком.

Наслідує темп, ретраї 429/5xx і token_info з providers/solana_tracker.py. Безпечний для кількох потоків:
кеші під `_cache_lock`, темп і лічильник запитів під замком у `_get`.
stats_cache тепер тримає угоди гаманця по токену (ключ trades:<mint>:<wallet>).
Поля перевірені живцем 16.09.2026 (docs/early_spike.md).
"""
import threading
import urllib.parse

from ..providers.solana_tracker import PAGE, SolanaTracker
from ..util import to_ms
from .ledger import normalize


class EarlyST(SolanaTracker):
    def __init__(self, api_key, chart_cache=None, stats_cache=None, **kw):
        super().__init__(api_key, **kw)
        self.chart_cache = chart_cache
        self.stats_cache = stats_cache
        self.chart_cache_hits = 0
        self.stats_cache_hits = 0
        # кеш свічок читають/пишуть кілька потоків (сторінка + робочий потік): без замка два
        # одночасні flush() ламались об os.replace того самого тимчасового файлу
        self._cache_lock = threading.Lock()

    def trades_page(self, mint, cursor_ms):
        """Одна сторінка угод від cursor_ms (ASC). Повертає нормалізовані угоди + курсор далі."""
        d = self._get(f"/trades/{mint}?sortDirection=ASC&limit={PAGE}&cursor={int(cursor_ms)}")
        return {
            "trades": [normalize(tr) for tr in (d.get("trades") or [])],
            "hasNextPage": bool(d.get("hasNextPage")),
            "nextCursor": d.get("nextCursor"),
        }

    @staticmethod
    def _chart_key(mint, interval, t_from_ms, t_to_ms):
        return f"{mint}:{interval}:{int(t_from_ms // 1000)}:{int(t_to_ms // 1000)}"

    def chart_cached(self, mint, interval, t_from_ms, t_to_ms):
        """Чи лежить цей шматок у кеші (тоді він нічого не коштує)."""
        if self.chart_cache is None:
            return False
        with self._cache_lock:
            return self.chart_cache.get(self._chart_key(mint, interval, t_from_ms, t_to_ms)) is not None

    def chart(self, mint, interval, t_from_ms, t_to_ms):
        """Свічки [{"time": ms, open, high, low, close, volume}] за відрізок (кешовано)."""
        a, b = int(t_from_ms // 1000), int(t_to_ms // 1000)
        key = self._chart_key(mint, interval, t_from_ms, t_to_ms)
        if self.chart_cache is not None:
            with self._cache_lock:
                cached = self.chart_cache.get(key)
            if cached is not None:
                self.chart_cache_hits += 1
                return cached
        q = urllib.parse.urlencode({"type": interval, "time_from": a, "time_to": b})
        d = self._get(f"/chart/{mint}?{q}")
        out = []
        for c in (d.get("oclhv") or d.get("data") or []):
            t = to_ms(c.get("time"))
            if t is None:
                continue
            out.append({"time": t, "open": c.get("open"), "high": c.get("high"),
                        "low": c.get("low"), "close": c.get("close"), "volume": c.get("volume")})
        out.sort(key=lambda c: c["time"])
        if self.chart_cache is not None:
            with self._cache_lock:
                self.chart_cache.put(key, out)
        return out

    def wallet_token_trades(self, wallet, mint, max_pages=4):
        """All trades of one wallet on one token (ST `/trades/{mint}/by-wallet/{owner}`, ASC, cursor
        pages of 500; 1 request per page, cached). Same raw swaps as the token feed, filtered by
        wallet on their side. Cursor is exclusive (time > cursor), so pages restart one ms before the last
        time and duplicates are dropped by tx — otherwise trades sharing the boundary second are lost."""
        key = f"trades:{mint}:{wallet}"
        if self.stats_cache is not None:
            with self._cache_lock:
                cached = self.stats_cache.get(key)
            if cached is not None:
                self.stats_cache_hits += 1
                return cached
        out, seen, cursor = [], set(), None
        for _ in range(max_pages):
            q = f"/trades/{mint}/by-wallet/{wallet}?sortDirection=ASC&limit={PAGE}" + (f"&cursor={int(cursor)}" if cursor else "")
            d = self._get(q)
            page = [normalize(tr) for tr in (d.get("trades") or [])]
            fresh = [tr for tr in page if tr["tx"] not in seen]
            seen.update(tr["tx"] for tr in fresh)
            out.extend(fresh)
            times = [tr["time"] for tr in page if tr["time"] is not None]
            if not d.get("hasNextPage") or not times:
                break
            nxt = max(times) - 1                            # курсор виключний: перечитати межову секунду
            if cursor is not None and nxt <= cursor:        # ціла сторінка в одній секунді — йдемо далі
                nxt = max(times)
            cursor = nxt
        out.sort(key=lambda tr: tr["time"] or 0)
        if self.stats_cache is not None:
            with self._cache_lock:
                self.stats_cache.put(key, out)
        return out

    def flush(self):
        with self._cache_lock:
            super().flush()
            for c in (self.chart_cache, self.stats_cache):
                if c is not None:
                    c.flush()
