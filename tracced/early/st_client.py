"""Клієнт Solana Tracker для early: сирі сторінки угод (з кількістю) і свічки з відрізком.

Наслідує темп, ретраї 429/5xx і token_info з providers/solana_tracker.py. Безпечний для кількох потоків:
кеші під `_cache_lock`, темп і лічильник запитів під замком у `_get`.
stats_cache тепер тримає угоди гаманця по токену (ключ trades:<mint>:<wallet>).
Поля перевірені живцем 16.09.2026 (docs/early_spike.md).
"""
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from ..providers.solana_tracker import PAGE, SolanaTracker
from ..util import to_ms
from .ledger import normalize
from .profile import compact_identity


class EarlyST(SolanaTracker):
    def __init__(self, api_key, chart_cache=None, stats_cache=None, identity_cache=None, **kw):
        super().__init__(api_key, **kw)
        self.chart_cache = chart_cache
        self.stats_cache = stats_cache
        # хто стоїть за гаманцем (KOL, Twitter, платформа): пакетом по 100 гаманців з /v2/pnl/wallets/batch.
        # Не з enrich=identity на сторінках угод: перевірено 24.09 на dev, сторінка з ним відповідає 11 с замість 0.2 с
        self.identity_cache = identity_cache
        self.chart_cache_hits = 0
        self.stats_cache_hits = 0
        # кеш свічок читають/пишуть кілька потоків (сторінка + робочий потік): без замка два
        # одночасні flush() ламались об os.replace того самого тимчасового файлу
        self._cache_lock = threading.Lock()

    def identity(self, wallet):
        """Ідентичність гаманця з кешу; None — невідомий гаманець або ще не питали."""
        if self.identity_cache is None:
            return None
        with self._cache_lock:
            return self.identity_cache.get(wallet) or None

    def identities(self, wallets, workers=8):
        """Хто стоїть за гаманцями: `POST /v2/pnl/wallets/batch`, 100 гаманців на запит, запити одночасно.

        Беремо лише `identity`; їхні PnL і теги в продукт не йдуть. Відповідь кешується, зокрема «невідомий»
        (порожній запис), тож той самий гаманець у наступному аналізі не коштує нічого. Повертає {гаманець: ідентичність}
        лише для відомих. Збій одного пакета не валить решту: ці гаманці просто лишаються без імені."""
        if self.identity_cache is None:
            return {}
        with self._cache_lock:
            todo = [w for w in dict.fromkeys(wallets) if w and self.identity_cache.get(w) is None]
        chunks = [todo[i:i + 100] for i in range(0, len(todo), 100)]

        def one(chunk):
            try:
                d = self._get("/v2/pnl/wallets/batch", body={"wallets": chunk}) or {}
            except Exception:  # noqa: BLE001
                return None
            return {x.get("wallet"): compact_identity(x.get("identity")) or {} for x in (d.get("wallets") or []) if x.get("wallet")}
        got = {}
        if chunks:
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks))), thread_name_prefix="early-ident") as pool:
                for chunk, res in zip(chunks, pool.map(one, chunks)):
                    if res is None:
                        continue
                    got.update(res)
                    got.update({w: {} for w in chunk if w not in res})     # notFound = невідомий, теж кешуємо
        with self._cache_lock:
            for w, idn in got.items():
                self.identity_cache.put(w, idn)
        return {w: self.identity(w) for w in wallets if self.identity(w)}

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
        # v3: свічки до міграції з пулу кривої. Старі записи кешу — лише пул після міграції, тому не читаються
        return f"v3:{mint}:{interval}:{int(t_from_ms // 1000)}:{int(t_to_ms // 1000)}"

    def chart_cached(self, mint, interval, t_from_ms, t_to_ms):
        """Чи лежить цей шматок у кеші (тоді він нічого не коштує)."""
        if self.chart_cache is None:
            return False
        with self._cache_lock:
            return self.chart_cache.get(self._chart_key(mint, interval, t_from_ms, t_to_ms)) is not None

    def _candles(self, path, interval, a, b):
        q = urllib.parse.urlencode({"type": interval, "time_from": a, "time_to": b, "dynamicPools": "true"})
        d = self._get(f"{path}?{q}")
        out = []
        for c in (d.get("oclhv") or d.get("data") or []):
            t = to_ms(c.get("time"))
            if t is None:
                continue
            out.append({"time": t, "open": c.get("open"), "high": c.get("high"),
                        "low": c.get("low"), "close": c.get("close"), "volume": c.get("volume")})
        return out

    def chart(self, mint, interval, t_from_ms, t_to_ms, launch_pool=None, migrated_ms=None):
        """Свічки [{"time": ms, open, high, low, close, volume}] за відрізок (кешовано).

        Джерело будує графік токена з пулу, що головний зараз. У токена, який переїхав з pump.fun на біржу, це пул
        біржі, і торгівля на кривій, де стається більшість пампів, приходила кількома свічками (SI 24.09: 13 з 90
        хвилин діапазону). Тому все, що до міграції, береться з пулу кривої (`/chart/{mint}/{pool}`), решта — як
        було, а на межі дві відповіді зшиваються: до моменту міграції свічки кривої, після нього — біржі."""
        a, b = int(t_from_ms // 1000), int(t_to_ms // 1000)
        key = self._chart_key(mint, interval, t_from_ms, t_to_ms)
        if self.chart_cache is not None:
            with self._cache_lock:
                cached = self.chart_cache.get(key)
            if cached is not None:
                self.chart_cache_hits += 1
                return cached
        mig = int(migrated_ms // 1000) if (launch_pool and migrated_ms) else None
        if mig and a < mig:
            out = [c for c in self._candles(f"/chart/{mint}/{launch_pool}", interval, a, min(b, mig)) if c["time"] < mig * 1000]
            if b > mig:
                out += [c for c in self._candles(f"/chart/{mint}", interval, mig, b) if c["time"] >= mig * 1000]
        else:
            out = self._candles(f"/chart/{mint}", interval, a, b)
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
            d = self._get(f"/trades/{mint}/by-wallet/{wallet}?sortDirection=ASC&limit={PAGE}"
                          + (f"&cursor={int(cursor)}" if cursor else ""))
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

    def wallet_swaps(self, owner, since_ms, max_pages=5):
        """Обміни гаманця по всіх токенах (`/wallet/{owner}/trades`, від нових до старих, до 1000 на сторінку),
        доки не дійдемо до since_ms або до max_pages сторінок. 1 запит на сторінку, без кешу: підсумок кешує той,
        хто кличе. Повертає (сирі обміни, partial): partial — сторінки скінчились раніше, ніж потрібна дата.

        Курсор — час, і межова секунда може прийти на обох сторінках: дублікати відкидаємо за транзакцією і ногами."""
        out, seen, cursor, partial = [], set(), None, False
        for page in range(max_pages):
            d = self._get(f"/wallet/{owner}/trades" + (f"?cursor={urllib.parse.quote(str(cursor))}" if cursor is not None else ""))
            trs = d.get("trades") or []
            for tr in trs:
                key = (tr.get("tx"), (tr.get("from") or {}).get("address"), (tr.get("to") or {}).get("address"),
                       (tr.get("from") or {}).get("amount"))
                if tr.get("tx") and key in seen:
                    continue
                seen.add(key)
                out.append(tr)
            times = [t for t in (to_ms(tr.get("time")) for tr in trs) if t is not None]
            if not trs or not d.get("hasNextPage") or d.get("nextCursor") is None or (times and min(times) < since_ms):
                break
            cursor = d.get("nextCursor")
            if page == max_pages - 1:
                partial = True                          # сторінки скінчились, а до потрібної дати ще не дійшли
        return out, partial

    def flush(self):
        with self._cache_lock:
            super().flush()
            for c in (self.chart_cache, self.stats_cache, self.identity_cache):
                if c is not None:
                    c.flush()
