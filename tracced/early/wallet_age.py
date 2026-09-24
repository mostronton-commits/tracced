"""Вік гаманця з блокчейну: час його найстарішої транзакції (для тега-факту `fresh`).

Джерело — Solana RPC `getSignaturesForAddress(limit=1000)`: підписи йдуть від нових до старих, тож
останній у списку — найстаріший. Гортаємо сторінки, доки відповідь не порожня або доки не впремось у
MAX_PAGES; у другому випадку вік невідомий (`exact=False`, тегу `fresh` не буде). Зупинятись на короткій
сторінці НЕ можна: нода ST віддає [7, 1000, 1000, …], і тоді старий гаманець виглядав би свіжим.

Нода за замовчуванням — офіційна api.mainnet-beta.solana.com: вона віддає повну історію підписів
(проба 17.09.2026: гаманець з лютого → oldest = лютий, 0.3 с). publicnode НЕ підходить: тримає лише
~2 доби історії, тому кожен гаманець виглядав «свіжим» (100 % fresh на PAID — хибно).
Публічні ноди ріжуть серії запитів, тому між запитами пауза: `pace_s` для підписів, `tx_pace_s` для
транзакцій, і в кожної ноди свій замок і свій час останнього запиту, щоб одна нода не чекала на іншу.
На 429/5xx — повтор з наростаючою паузою, а на 429 із заголовком Retry-After — стільки, скільки просить нода
(не довше RETRY_AFTER_MAX). Один запит на гаманець, кеш 7 днів. Адресу ноди можна замінити через
SOLANA_RPC_URL (платна нода → без пауз), але вона мусить зберігати повну історію підписів.
"""
import email.utils
import json
import os
import threading
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://api.mainnet-beta.solana.com"
HEAVY = {"getSignaturesForAddress", "getTransaction"}   # платна нода Solana Tracker бере за них по 10 кредитів
# Helius: повна історія, по 1 кредиту за виклик, і свій метод «від найстарішої» (getTransactionsForAddress, 10 кредитів),
# що знаходить першу транзакцію зайнятого гаманця одним викликом замість гортання (перевірено 24.09.2026: у гаманця
# з 36 039 транзакціями — жовтень 2025, як в Axiom)
HELIUS_HOST = "helius-rpc.com"
LIMIT = 1000
MAX_PAGES = 6            # 6 000 підписів: далі гаманець точно не «свіжий», а ходити глибше дорого
DEEP_PAGES = 30          # картка, яку відкрили: до 30 000 підписів, щоб у зайнятого гаманця знайти справжній вік і спонсора
RETRY_SLEEP = (2, 4, 8)
RETRY_AFTER_MAX = 10     # Retry-After слухаємо, але картку, що чекає на відповідь, довше не тримаємо


def _retry_after(err, default):
    """Пауза після 429: заголовок Retry-After (секунди або дата HTTP), не довше RETRY_AFTER_MAX; нема — default."""
    v = (getattr(err, "headers", None) or {}).get("Retry-After")
    if v is None:
        return default
    try:
        wait = float(v)
    except (TypeError, ValueError):
        try:
            wait = email.utils.parsedate_to_datetime(v).timestamp() - time.time()
        except (TypeError, ValueError, IndexError, OverflowError):
            return default
    return min(max(wait, 0.0), RETRY_AFTER_MAX)


class MonthBudget:
    """Кредити платної RPC-ноди за календарний місяць (UTC), з файлом: переживає перезапуск і деплой.

    RPC — окремий продукт зі своїм лічильником, і в Data API його не видно. Лічильник запитів гаманців погано
    захищав цей гаманець кредитів: 30 прогонів на день по 600 гаманців з'їли б безкоштовний пул за день з
    лишком. Тому межа — кредити, а не кількість гаманців. `limit` 0 — без межі."""

    def __init__(self, path=None, limit=0, reserve_pct=10, now=time.time):
        self.path, self.limit, self.reserve_pct = path, int(limit or 0), float(reserve_pct or 0)
        self._now, self._lock, self._dirty = now, threading.Lock(), 0
        self.month, self.spent = self._month(), 0
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("month") == self.month:
                    self.spent = int(d.get("spent") or 0)
            except Exception:  # noqa: BLE001 — битий файл = чистий місяць
                pass

    def _month(self):
        return time.strftime("%Y-%m", time.gmtime(self._now()))

    def _roll(self):
        m = self._month()
        if m != self.month:
            self.month, self.spent, self._dirty = m, 0, 1

    def spend(self, n):
        with self._lock:
            self._roll()
            self.spent += int(n)
            self._dirty += 1
            if self._dirty >= 20:
                self._flush()

    def exhausted(self):
        """True, коли до межі лишився лише резерв: збагачення стає на паузу до нового місяця."""
        if not self.limit:
            return False
        with self._lock:
            self._roll()
            return self.spent >= self.limit * (1 - self.reserve_pct / 100)

    def state(self):
        with self._lock:
            self._roll()
            return {"month": self.month, "spent": self.spent, "limit": self.limit}

    def _flush(self):
        self._dirty = 0
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"month": self.month, "spent": self.spent}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def flush(self):
        with self._lock:
            if self._dirty:
                self._flush()


class WalletAge:
    def __init__(self, url=None, cache=None, pace_s=0.5, post=None, sleep=time.sleep, tx_url=None, budget=None,
                 tx_pace_s=0.3):
        self.url = url or os.getenv("SOLANA_RPC_URL") or DEFAULT_URL
        self.helius = HELIUS_HOST in self.url
        # getTransaction і getSignaturesForAddress не конче живуть на одній ноді. Нода Solana Tracker віддає
        # повну історію підписів і не ріже серії, але на getTransaction відповідає Internal error (перевірено
        # 24.09.2026, усі варіанти параметрів). Тому одну транзакцію питаємо там, де вона працює.
        self.tx_url = tx_url or os.getenv("SOLANA_RPC_TX_URL") or (
            self.url if self.helius else (DEFAULT_URL if self.url != DEFAULT_URL else self.url))   # Helius віддає й транзакції
        self.cache = cache
        self.pace_s = pace_s
        self.tx_pace_s = tx_pace_s
        self.requests = 0
        self.cache_hits = 0
        self._post = post or self._http
        self._sleep = sleep
        # замок і час останнього запиту — окремі для кожної ноди: транзакції на публічній ноді не чекають на
        # підписи з платної. Публічна api.mainnet-beta тримає ~40 викликів за 10 с на метод: спонсори ловили 429,
        # поки йшли в темпі платної ноди, тому в транзакцій свій темп
        self._slots = {u: {"lock": threading.Lock(), "last": 0.0} for u in (self.url, self.tx_url)}
        self._count_lock = threading.Lock()              # лічильник спільний, а ноди йдуть паралельно
        self.budget = budget            # MonthBudget: кредити платної ноди (публічна нода безкоштовна і не рахується)

    # ── транспорт ──
    def _http(self, payload, url=None):
        req = urllib.request.Request(url or self.url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "early-wallets/1.0"},   # без UA деякі ноди дають 403
                                     method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    def _call(self, method, params, url=None, pace_s=None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_err = None
        node = url or self.url
        paid = self.budget is not None and node != DEFAULT_URL
        pace = self.pace_s if pace_s is None else pace_s
        slot = self._slots.setdefault(node, {"lock": threading.Lock(), "last": 0.0})
        for attempt in range(len(RETRY_SLEEP) + 1):
            pause = RETRY_SLEEP[min(attempt, len(RETRY_SLEEP) - 1)]
            with slot["lock"]:
                wait = pace - (time.monotonic() - slot["last"])
                if wait > 0:
                    self._sleep(wait)
                try:
                    with self._count_lock:
                        self.requests += 1
                    if paid:
                        self.budget.spend(self._credits(method, node))   # невдала спроба теж оплачена
                    d = self._post(payload, url) if url else self._post(payload)
                    slot["last"] = time.monotonic()
                except urllib.error.HTTPError as e:
                    slot["last"] = time.monotonic()
                    last_err = e
                    if e.code not in (429, 500, 502, 503, 504) or attempt == len(RETRY_SLEEP):
                        raise
                    if e.code == 429:
                        pause = _retry_after(e, pause)
                except urllib.error.URLError as e:
                    slot["last"] = time.monotonic()
                    last_err = e
                    if attempt == len(RETRY_SLEEP):
                        raise
                else:
                    if d.get("error"):
                        raise RuntimeError(f"RPC error: {d['error']}")
                    return d.get("result")
            self._sleep(pause)
        raise last_err  # pragma: no cover — цикл завжди або повертає, або кидає

    @staticmethod
    def _credits(method, node):
        """Ціна виклику на цій ноді: Helius бере по 1 кредиту (метод «від найстарішої» — 10), Solana Tracker — 10 за
        історію підписів і транзакцію, 1 за решту."""
        if HELIUS_HOST in node:
            return 10 if method == "getTransactionsForAddress" else 1
        return 10 if method in HEAVY else 1

    def paused(self):
        """Бюджет платної ноди на цей місяць вичерпано (до резерву): нові гаманці чекають наступного місяця."""
        return bool(self.budget and self.budget.exhausted())

    def cached(self, wallet):
        """Вік з кешу без запиту; None — треба питати ноду."""
        return self.cache.get(wallet) if self.cache is not None else None

    # ── факт ──
    def oldest_tx(self, wallet, refresh=False, full=True, before=None):
        """{"oldest_ms": ms|None, "exact": bool, "n": кількість підписів, "oldest_sig"} (кешовано).

        `before` — підпис першої покупки гаманця в аналізі. Helius читає сторінку історії ДО неї, і в більшості
        гаманців уся їхня передісторія влазить в одну сторінку: це точний вік за 1 кредит. `full=False` на цьому й
        зупиняється: гаманець з тисячею транзакцій до покупки лишається «старший за найстарішу прочитану» (для
        тега `fresh` цього майже завжди досить, див. tags.could_be_fresh). `full=True` дочитує такий гаманець одним
        викликом «від найстарішої» (10 кредитів), зокрема той, що в кеші лишила дешева перевірка."""
        cached = None
        if self.cache is not None and not refresh:
            cached = self.cache.get(wallet)
            if cached is not None and (cached.get("exact") or cached.get("deep") or not full or not self.helius):
                self.cache_hits += 1
                return cached
        if cached is not None:                            # неточний вік з дешевої перевірки: лишився один виклик
            out = self._oldest_first(wallet, cached)
        elif self.helius:
            out = self._oldest_helius(wallet, full, before)
        else:
            out = self._oldest_paged(wallet)
        if self.cache is not None:
            self.cache.put(wallet, out)
        return out

    @staticmethod
    def _age(sig, exact, n):
        bt = (sig or {}).get("blockTime")
        return {"oldest_ms": int(bt) * 1000 if bt else None, "exact": bool(exact), "n": n, "oldest_sig": (sig or {}).get("signature")}

    def _oldest_paged(self, wallet):
        # Коротка сторінка НЕ означає кінець історії: нода Solana Tracker віддає першою сторінкою 7 підписів,
        # а далі ще двадцять дев'ять по тисячі. Тому гортаємо, доки відповідь не порожня, і лише вичерпавши
        # сторінки, зізнаємось, що точної дати не знаємо (exact=False, тег fresh не ставиться).
        before, last, n, pages = None, None, 0, 0
        while pages < MAX_PAGES:
            params = [wallet, {"limit": LIMIT}]
            if before:
                params[1]["before"] = before
            sigs = self._call("getSignaturesForAddress", params) or []
            if not sigs:
                break
            n += len(sigs)
            last, before = sigs[-1], sigs[-1].get("signature")
            pages += 1
        return self._age(last, pages < MAX_PAGES, n)

    def _oldest_helius(self, wallet, full=True, before=None):
        """Helius віддає повні сторінки до самого кінця історії, тож неповна сторінка — це вся історія (1 кредит).
        З `before` сторінка — лише те, що було до першої покупки: у зайнятого сьогодні гаманця там часто кілька
        десятків транзакцій. Порожня сторінка до покупки (застосунок заплатив за гаманець, і покупка — його перша
        транзакція) і підпис, якого нода не знає, — читаємо від найновішої, як без `before`.
        Зайнятий гаманець не гортаємо: найстаріший підпис дає один виклик «від найстарішої» (10 кредитів)."""
        sigs = None
        if before:
            try:
                sigs = self._call("getSignaturesForAddress", [wallet, {"limit": LIMIT, "before": before}]) or []
            except RuntimeError:
                sigs = None
        if not sigs:
            sigs = self._call("getSignaturesForAddress", [wallet, {"limit": LIMIT}]) or []
        if len(sigs) < LIMIT:
            return self._age(sigs[-1] if sigs else None, True, len(sigs))
        inexact = self._age(sigs[-1], False, len(sigs))  # «старший за цю»: дешева перевірка на цьому зупиняється
        return self._oldest_first(wallet, inexact) if full else inexact

    def _oldest_first(self, wallet, fallback):
        """Перша транзакція зайнятого гаманця одним викликом «від найстарішої» (10 кредитів). План без цього методу —
        гортаємо, як на будь-якій ноді; порожня відповідь — лишається `fallback`."""
        try:
            res = self._call("getTransactionsForAddress",
                             [wallet, {"sortOrder": "asc", "limit": 1, "transactionDetails": "signatures"}]) or {}
        except RuntimeError:
            return self._oldest_paged(wallet)
        first = ((res.get("data") if isinstance(res, dict) else res) or [None])[0]
        if not first:
            return fallback
        return self._age(first, True, None)               # скільки всього транзакцій — не рахуємо: це й було б гортання

    def oldest_tx_deep(self, wallet):
        """Той самий вік, але для зайнятого гаманця: гортаємо далі, з того підпису, де зупинився звичайний підрахунок,
        до DEEP_PAGES сторінок. Лише коли людина відкрила картку: для сотень гаманців аналізу це задовго і задорого.
        Результат з `deep: True` лягає в кеш, тож друга спроба вже нічого не коштує, навіть якщо початку не видно."""
        base = self.oldest_tx(wallet)
        if base.get("exact") or base.get("deep") or not base.get("oldest_sig"):
            return base
        before, last, n = base["oldest_sig"], None, int(base.get("n") or 0)
        pages, reached = -(-n // LIMIT), False
        while pages < DEEP_PAGES:
            sigs = self._call("getSignaturesForAddress", [wallet, {"limit": LIMIT, "before": before}]) or []
            if not sigs:
                reached = True
                break
            n += len(sigs)
            last, before = sigs[-1], sigs[-1].get("signature")
            pages += 1
        bt = last.get("blockTime") if last else None
        out = {"oldest_ms": int(bt) * 1000 if bt else base.get("oldest_ms"), "exact": reached, "n": n,
               "oldest_sig": (last or {}).get("signature") or base.get("oldest_sig"), "deep": True}
        if self.cache is not None:
            self.cache.put(wallet, out)
        return out

    def funder(self, wallet, oldest_sig, scan=True):
        """Хто дав гаманцю перший SOL: підписант найстарішої транзакції, чий баланс зменшився, коли баланс
        гаманця зріс. None, якщо перша транзакція не була вхідним переказом (кешовано).

        `scan=False` — дешева перевірка: лише перша транзакція (1 кредит), без пошуку серед перших 100 (10 кредитів).
        Такий порожній результат кеш пам'ятає як `scanned: False`, і наступний виклик зі `scan=True` (картка,
        перша двісті) робить лише пошук. Записи, старші за цю позначку, вважаються дочитаними."""
        key = f"funder:{wallet}"
        can_scan = HELIUS_HOST in self.tx_url
        cached = self.cache.get(key) if self.cache is not None else None
        if cached is not None and (cached.get("funder") or not scan or cached.get("scanned", True) or not can_scan):
            self.cache_hits += 1
            return cached.get("funder")
        if cached is not None:                            # перша транзакція вже прочитана і спонсора не дала
            found, via = self._first_sol_in(wallet), "scan"
        else:
            tx = self._call("getTransaction", [oldest_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                            url=self.tx_url, pace_s=self.tx_pace_s)
            found, via = funder_from_tx(tx, wallet), "first"
            if found is None and can_scan and scan:
                found, via = self._first_sol_in(wallet), "scan"
        out = {"funder": found, "scanned": bool(found) or scan or not can_scan}
        if found:
            out["via"] = via                              # звідки: скільки спонсорів дає лише пошук за 10 кредитів
        if self.cache is not None:
            self.cache.put(key, out)
        return found

    def funder_pending(self, wallet):
        """Дешева перевірка прочитала лише першу транзакцію, і спонсора там не було: пошук серед перших 100 ще не
        робився. Картка, яку відкрили, його доробляє."""
        c = self.cache.get(f"funder:{wallet}") if self.cache is not None else None
        return bool(c) and not c.get("funder") and c.get("scanned") is False and HELIUS_HOST in self.tx_url

    def _first_sol_in(self, wallet):
        """Гаманець застосунку (комісії за нього платить застосунок) починає не з SOL, а з токенів. Перший вхідний SOL
        шукаємо серед його перших 100 транзакцій, одним викликом «від найстарішої» (10 кредитів). Далі — невідомо:
        у гаманця Fomo з 36 тисяч транзакцій його не було і серед перших 1 500."""
        try:
            res = self._call("getTransactionsForAddress",
                             [wallet, {"sortOrder": "asc", "limit": 100, "transactionDetails": "full",
                                       "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                             url=self.tx_url, pace_s=self.tx_pace_s) or {}
        except RuntimeError:
            return None
        for t in (res.get("data") if isinstance(res, dict) else res) or []:
            if (t.get("meta") or {}).get("err"):
                continue
            found = funder_from_tx(t, wallet)
            if found:
                return found
        return None

    def flush(self):
        if self.cache is not None:
            self.cache.flush()
        if self.budget is not None:
            self.budget.flush()


def funder_from_tx(tx, wallet):
    """Чиста розбірка транзакції (jsonParsed): спонсор = підписант з найбільшим відпливом лампортів,
    якщо баланс `wallet` у цій транзакції зріс. Інакше None."""
    if not tx:
        return None
    meta, msg = tx.get("meta") or {}, (tx.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    if len(keys) != len(pre) or len(pre) != len(post):
        return None
    idx = next((i for i, k in enumerate(keys) if (k.get("pubkey") if isinstance(k, dict) else k) == wallet), None)
    if idx is None or post[idx] - pre[idx] <= 0:
        return None
    best, best_delta = None, 0
    for i, k in enumerate(keys):
        pk = k.get("pubkey") if isinstance(k, dict) else k
        signer = k.get("signer") if isinstance(k, dict) else (i == 0)
        delta = pre[i] - post[i]
        if signer and pk != wallet and delta > best_delta:
            best, best_delta = pk, delta
    return best
