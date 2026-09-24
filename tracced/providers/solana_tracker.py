"""Реализация источника на Solana Tracker Data API. Эндпоинты проверены живьём."""
import threading
import time
import urllib.error

from .base import PumpDataSource
from ..util import http_get_json, to_ms

BASE = "https://data.solanatracker.io"


PAGE = 500          # стеля сторінки /trades; за замовчуванням вони дають 250, тобто вдвічі більше запитів


def _usd(v):
    """Поля ST вида {usd, quote} → берём usd; если уже число — как есть."""
    if isinstance(v, dict):
        return v.get("usd")
    return v


def _launch_pool(pools):
    """Пул, з якого токен почався: у нього є крива. Токен, запущений одразу на біржі, кривої не має."""
    with_curve = [x for x in pools if x.get("curve") or x.get("curvePercentage") is not None]
    return min(with_curve, key=lambda x: x.get("createdAt") or 0) if with_curve else {}


def _migration(pools):
    """Коли торгівля переїхала з лаунчпада на біржу: створення першого пулу після того, як крива добігла.

    Пізніші пули створюють сторонні люди (у нашого демо-токена їх шість), тож бере саме перший. Крива не
    завершена або токен запущено одразу на біржі — міграції не було, і малювати на графіку нічого."""
    launch = _launch_pool(pools)
    if not launch or (launch.get("curvePercentage") or 0) < 100:
        return None
    born = launch.get("createdAt") or 0
    later = [x for x in pools if x is not launch and (x.get("createdAt") or 0) > born]
    if not later:
        return None
    first = min(later, key=lambda x: x["createdAt"])
    return {"ms": first["createdAt"], "market": first.get("market"), "from": launch.get("market")}


class SolanaTracker(PumpDataSource):
    def __init__(self, api_key, pause=0.35, retries=3, cache=None):
        self.h = {"x-api-key": api_key}
        self.pause = pause          # ~3 req/s — лимит free-тарифа
        self.retries = retries
        self.requests = 0
        self.cache_hits = 0
        self.cache = cache
        self._last = 0.0
        self._lock = threading.Lock()   # темп і лічильник спільні для всіх потоків; сам HTTP-виклик іде поза замком

    def flush(self):
        if self.cache:
            self.cache.flush()

    def credits(self):
        """Остаток кредитов ST на ключе. None при ошибке."""
        try:
            return self._get("/credits").get("credits")
        except Exception:
            return None

    def _get(self, path):
        with self._lock:
            if self.pause > 0:                                   # free: темп ≤3 req/s на всі потоки разом
                wait = self.pause - (time.monotonic() - self._last)
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
        pools = [x for x in (d.get("pools") or []) if x] or [{}]
        p = pools[0] or {}
        creation = tok.get("creation") or {}
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
            "creator": creation.get("creator") or _launch_pool(pools).get("deployer"),   # творець токена: тег `dev`
            "deployer": p.get("deployer"),              # хто створив пул pools[0] — не обовʼязково творець токена
            "migration": _migration(pools),             # коли крива добігла і торгівля переїхала на біржу
            "launchpad": tok.get("createdOn"),          # де запущено (pump.fun тощо)
            "market": p.get("market"),                  # на якій біржі пул
            "twitter": tok.get("twitter"),
            "website": tok.get("website"),
            "holders": d.get("holders"),
            "txns": d.get("txns"),
            "buys": d.get("buys"),
            "sells": d.get("sells"),
        }
