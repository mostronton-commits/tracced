import unittest
import urllib.error

from tracced.early import tags
from tracced.early.wallet_age import DEFAULT_URL, MonthBudget, WalletAge, funder_from_tx

H = 3_600_000


def sigs(n, oldest_s=1_000_000):
    return [{"signature": str(i), "blockTime": oldest_s + (n - i)} for i in range(n)]   # newest first


class FakePost:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, payload, url=None):
        self.calls.append(payload)
        self.urls = getattr(self, "urls", []) + [url]
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return {"jsonrpc": "2.0", "result": a}


class TestWalletAge(unittest.TestCase):
    def test_exact_age_when_under_limit(self):
        post = FakePost([sigs(5), []])          # порожня сторінка = кінець історії, як у справжньої ноди
        wa = WalletAge(post=post, sleep=lambda s: None, pace_s=0)
        a = wa.oldest_tx("W1")
        self.assertEqual(a, {"oldest_ms": 1_000_001_000, "exact": True, "n": 5, "oldest_sig": "4"})
        self.assertEqual(post.calls[0]["method"], "getSignaturesForAddress")
        self.assertEqual(post.calls[0]["params"][1]["limit"], 1000)

    def test_bound_only_when_pages_run_out(self):
        wa = WalletAge(post=FakePost([sigs(1000)] * 6), sleep=lambda s: None, pace_s=0)
        a = wa.oldest_tx("W2")
        self.assertFalse(a["exact"])                       # шість повних сторінок і кінця не видно
        self.assertEqual(a["n"], 6000)

    def test_a_short_page_is_not_the_end_of_the_history(self):
        """Нода Solana Tracker віддає першою сторінкою сім підписів, а далі ще тисячі.

        Поки ми зупинялись на короткій сторінці, старий активний гаманець виглядав створеним сьогодні,
        тобто тег `fresh` брехав саме на тих гаманцях, які нас цікавлять найбільше."""
        pages = [sigs(7, oldest_s=2_000_000), sigs(1000, oldest_s=1_500_000), sigs(300, oldest_s=1_000_000), []]
        wa = WalletAge(post=FakePost(pages), sleep=lambda s: None, pace_s=0)
        a = wa.oldest_tx("W2b")
        self.assertTrue(a["exact"])
        self.assertEqual(a["n"], 1307)
        self.assertEqual(a["oldest_ms"], 1_000_001_000)    # час з ОСТАННЬОЇ сторінки, не з першої

    def test_each_page_asks_for_the_one_before_it(self):
        post = FakePost([sigs(1000), sigs(4), []])
        wa = WalletAge(post=post, sleep=lambda s: None, pace_s=0)
        wa.oldest_tx("W2c")
        self.assertNotIn("before", post.calls[0]["params"][1])
        self.assertEqual(post.calls[1]["params"][1]["before"], "999")   # останній підпис першої сторінки

    def test_empty_wallet(self):
        wa = WalletAge(post=FakePost([[]]), sleep=lambda s: None, pace_s=0)
        self.assertEqual(wa.oldest_tx("W3"), {"oldest_ms": None, "exact": True, "n": 0, "oldest_sig": None})

    def test_retries_on_429_then_gives_up_on_400(self):
        slept = []
        err = lambda code: urllib.error.HTTPError("u", code, "x", {}, None)  # noqa: E731
        wa = WalletAge(post=FakePost([err(429), err(503), sigs(2), []]), sleep=slept.append, pace_s=0)
        self.assertEqual(wa.oldest_tx("W4")["n"], 2)
        self.assertEqual(slept, [2, 4])                                   # наростаюча пауза
        wa2 = WalletAge(post=FakePost([err(400)]), sleep=lambda s: None, pace_s=0)
        with self.assertRaises(urllib.error.HTTPError):
            wa2.oldest_tx("W5")

    def test_pacing_and_cache(self):
        class Cache(dict):
            def get(self, k): return dict.get(self, k)
            def put(self, k, v): self[k] = v
            def flush(self): pass
        slept = []
        post = FakePost([sigs(1), [], sigs(1), []])
        wa = WalletAge(post=post, cache=Cache(), sleep=slept.append, pace_s=0.5)
        wa.oldest_tx("A"); wa.oldest_tx("B"); wa.oldest_tx("A")
        self.assertEqual(len(post.calls), 4)                              # два гаманці по дві сторінки; третій виклик — з кешу
        self.assertTrue(slept and 0 < slept[0] <= 0.5)                    # pause before the second call

    def test_each_node_keeps_its_own_pace(self):
        """Транзакції йдуть у публічну ноду зі своїм темпом і не чекають на паузу платної ноди підписів."""
        slept = []
        post = FakePost([sigs(1), [], {"meta": {}}, {"meta": {}}])
        wa = WalletAge(url="https://rpc.example/?k", tx_url=DEFAULT_URL, post=post, sleep=slept.append,
                       pace_s=0.5, tx_pace_s=0.3)
        wa.oldest_tx("W1")                                                # дві сторінки: друга чекає 0.5 с
        wa.funder("W1", "0")                                              # перша транзакція: нода тиха, без паузи
        wa.funder("W2", "0")                                              # друга: темп транзакцій, не підписів
        self.assertEqual(len(slept), 2)
        self.assertTrue(0.45 < slept[0] <= 0.5)
        self.assertTrue(0.25 < slept[1] <= 0.3)
        self.assertEqual(post.urls, [None, None, DEFAULT_URL, DEFAULT_URL])

    def test_a_slow_node_does_not_hold_up_the_other(self):
        import threading
        entered, release = threading.Event(), threading.Event()

        def post(payload, url=None):
            if url is None:                                               # платна нода підписів «зависла»
                entered.set()
                release.wait(5)
                return {"result": []}
            return {"result": {"meta": {}}}
        wa = WalletAge(url="https://rpc.example/?k", tx_url=DEFAULT_URL, post=post, sleep=lambda s: None, pace_s=0)
        t = threading.Thread(target=wa.oldest_tx, args=("W1",))
        t.start()
        try:
            self.assertTrue(entered.wait(5))
            done = []
            probe = threading.Thread(target=lambda: done.append(wa.funder("W2", "0")))
            probe.start()
            probe.join(2)
            self.assertEqual(done, [None])                                # відповіла, не чекаючи на першу ноду
        finally:
            release.set()
            t.join(5)

    def test_429_waits_as_long_as_the_node_asks_within_a_cap(self):
        from tracced.early.wallet_age import RETRY_AFTER_MAX
        err = lambda after: urllib.error.HTTPError("u", 429, "x", {"Retry-After": after}, None)  # noqa: E731
        for after, want in (("7", 7.0), ("600", RETRY_AFTER_MAX), ("soon", 2)):
            with self.subTest(after=after):
                slept = []
                wa = WalletAge(post=FakePost([err(after), sigs(1), []]), sleep=slept.append, pace_s=0)
                self.assertEqual(wa.oldest_tx("W")["n"], 1)
                self.assertEqual(slept, [want])                           # незрозумілий заголовок — звичайна пауза

    def test_deep_read_continues_where_the_normal_one_stopped(self):
        from tracced.early.wallet_age import MAX_PAGES
        full = lambda k: [{"signature": f"s{k}-{i}", "blockTime": 1_790_000_000 - k * 100_000 - i} for i in range(1000)]  # noqa: E731
        pages = [full(k) for k in range(MAX_PAGES)] + [full(MAX_PAGES), sigs(40), []]
        class Cache(dict):
            def get(self, k): return dict.get(self, k)
            def put(self, k, v): self[k] = v
            def flush(self): pass
        post = FakePost(pages)
        wa = WalletAge(post=post, cache=Cache(), sleep=lambda s: None, pace_s=0)
        shallow = wa.oldest_tx("BUSY")
        self.assertEqual((shallow["exact"], shallow["n"]), (False, MAX_PAGES * 1000))   # звичайний підрахунок не дійшов до першої
        deep = wa.oldest_tx_deep("BUSY")
        self.assertEqual((deep["exact"], deep["n"], deep["deep"]), (True, MAX_PAGES * 1000 + 1040, True))
        self.assertEqual(deep["oldest_sig"], "39")                                  # найстаріший — останній з останньої сторінки
        calls = len(post.calls)
        self.assertEqual(wa.oldest_tx_deep("BUSY"), deep)                           # з кешу, без нових викликів
        self.assertEqual(len(post.calls), calls)

    def test_helius_finds_the_first_transaction_without_paging(self):
        from tracced.early.wallet_age import MonthBudget, LIMIT
        H = "https://mainnet.helius-rpc.com/?api-key=x"
        # звичайний гаманець: неповна перша сторінка — уся історія, 1 кредит
        budget = MonthBudget(None, limit=10_000)
        post = FakePost([sigs(40)])
        wa = WalletAge(url=H, post=post, sleep=lambda s: None, pace_s=0, budget=budget)
        age = wa.oldest_tx("A")
        self.assertEqual((age["exact"], age["n"]), (True, 40))
        self.assertEqual((len(post.calls), budget.spent), (1, 1))
        # зайнятий: повна сторінка, тоді один виклик «від найстарішої» — 1 + 10 кредитів, без гортання
        budget = MonthBudget(None, limit=10_000)
        post = FakePost([sigs(LIMIT), {"data": [{"signature": "first", "blockTime": 1_761_516_360}], "paginationToken": "t"}])
        wa = WalletAge(url=H, post=post, sleep=lambda s: None, pace_s=0, budget=budget)
        age = wa.oldest_tx("BUSY")
        self.assertEqual((age["exact"], age["oldest_sig"], age["oldest_ms"]), (True, "first", 1_761_516_360_000))
        self.assertEqual(post.calls[1]["method"], "getTransactionsForAddress")
        self.assertEqual(post.calls[1]["params"][1]["sortOrder"], "asc")
        self.assertEqual(budget.spent, 11)
        self.assertEqual(wa.tx_url, H)                                         # транзакцію теж віддає Helius

    def test_an_app_wallets_funder_comes_from_its_first_hundred_transactions(self):
        H = "https://mainnet.helius-rpc.com/?api-key=x"
        def tx(wallet_gain, sender="SENDER"):
            keys = [{"pubkey": "PAYER", "signer": True}, {"pubkey": sender, "signer": True}, {"pubkey": "APP", "signer": False}]
            return {"meta": {"err": None, "preBalances": [5_000_000, 9_000_000_000, 0],
                             "postBalances": [4_995_000, 9_000_000_000 - wallet_gain, wallet_gain]},
                    "transaction": {"message": {"accountKeys": keys}}}
        # перша транзакція — токени, SOL гаманця не змінився; вхідний SOL — третій серед перших ста
        post = FakePost([tx(0), {"data": [tx(0), tx(0), tx(2_000_000, "REALFUNDER")], "paginationToken": None}])
        wa = WalletAge(url=H, post=post, sleep=lambda s: None, pace_s=0)
        self.assertEqual(wa.funder("APP", "sig1"), "REALFUNDER")
        self.assertEqual(post.calls[1]["params"][1]["transactionDetails"], "full")
        # інша нода не знає «від найстарішої»: лишається перша транзакція, як було
        post = FakePost([tx(0)])
        self.assertIsNone(WalletAge(url="https://rpc.example", post=post, sleep=lambda s: None, pace_s=0).funder("APP", "sig1"))
        self.assertEqual(len(post.calls), 1)

    def test_helius_reads_the_history_before_the_first_buy(self):
        from tracced.early.wallet_age import LIMIT

        class Cache(dict):
            def get(self, k): return dict.get(self, k)
            def put(self, k, v): self[k] = v
            def flush(self): pass
        HX = "https://mainnet.helius-rpc.com/?api-key=x"
        # уся передісторія гаманця — одна неповна сторінка до покупки: точний вік за 1 кредит, і в дешевій перевірці
        b, post = MonthBudget(None, limit=10_000), FakePost([sigs(12)])
        wa = WalletAge(url=HX, post=post, sleep=lambda s: None, pace_s=0, budget=b, cache=Cache())
        age = wa.oldest_tx("A", full=False, before="BUY")
        self.assertEqual((age["exact"], age["n"], b.spent), (True, 12, 1))
        self.assertEqual(post.calls[0]["params"][1]["before"], "BUY")
        # тисяча транзакцій до покупки: дешева перевірка зупиняється на «старший за найстарішу прочитану»
        b, post = MonthBudget(None, limit=10_000), FakePost([sigs(LIMIT), {"data": [{"signature": "first", "blockTime": 900_000}]}])
        wa = WalletAge(url=HX, post=post, sleep=lambda s: None, pace_s=0, budget=b, cache=Cache())
        age = wa.oldest_tx("BUSY", full=False, before="BUY")
        self.assertEqual((age["exact"], age["n"], len(post.calls), b.spent), (False, LIMIT, 1, 1))
        self.assertIs(wa.oldest_tx("BUSY", full=False), age)                    # вдруге дешевій перевірці — з кешу
        # повна перевірка (перші за PnL, картка) дочитує з кешу одним викликом «від найстарішої», без першої сторінки
        age = wa.oldest_tx("BUSY")
        self.assertEqual((age["exact"], age["oldest_sig"]), (True, "first"))
        self.assertEqual((post.calls[-1]["method"], len(post.calls), b.spent), ("getTransactionsForAddress", 2, 11))
        self.assertEqual(wa.oldest_tx_deep("BUSY"), age)                        # картка: уже точний, нічого не коштує
        self.assertEqual(len(post.calls), 2)
        # до покупки порожньо: застосунок заплатив за гаманець, і покупка — його перша транзакція. Читаємо від найновішої
        post = FakePost([[], sigs(3)])
        age = WalletAge(url=HX, post=post, sleep=lambda s: None, pace_s=0).oldest_tx("APP", full=False, before="BUY")
        self.assertEqual((age["exact"], age["n"], len(post.calls)), (True, 3, 2))
        self.assertNotIn("before", post.calls[1]["params"][1])
        # нода не знає підпису покупки: так само
        calls = []

        def unknown_sig(payload, url=None):
            calls.append(payload)
            if "before" in payload["params"][1]:
                return {"jsonrpc": "2.0", "error": {"code": -32602, "message": "Invalid param: not a signature"}}
            return {"jsonrpc": "2.0", "result": sigs(3)}
        age = WalletAge(url=HX, post=unknown_sig, sleep=lambda s: None, pace_s=0).oldest_tx("APP", full=False, before="??")
        self.assertEqual((age["exact"], age["n"], len(calls)), (True, 3, 2))

    def test_the_cheap_funder_check_leaves_the_search_for_later(self):
        class Cache(dict):
            def get(self, k): return dict.get(self, k)
            def put(self, k, v): self[k] = v
            def flush(self): pass
        HX = "https://mainnet.helius-rpc.com/?api-key=x"

        def tx(gain, sender="SENDER"):
            keys = [{"pubkey": "PAYER", "signer": True}, {"pubkey": sender, "signer": True}, {"pubkey": "APP", "signer": False}]
            return {"meta": {"err": None, "preBalances": [5_000_000, 9_000_000_000, 0],
                             "postBalances": [4_995_000, 9_000_000_000 - gain, gain]},
                    "transaction": {"message": {"accountKeys": keys}}}
        b, post = MonthBudget(None, limit=10_000), FakePost([tx(0), {"data": [tx(0), tx(2_000_000, "REALFUNDER")]}])
        wa = WalletAge(url=HX, post=post, sleep=lambda s: None, pace_s=0, budget=b, cache=Cache())
        self.assertIsNone(wa.funder("APP", "sig1", scan=False))                  # лише перша транзакція: 1 кредит
        self.assertEqual((len(post.calls), b.spent, wa.funder_pending("APP")), (1, 1, True))
        self.assertIsNone(wa.funder("APP", "sig1", scan=False))                  # дешевій перевірці вдруге — з кешу
        self.assertEqual(wa.funder("APP", "sig1"), "REALFUNDER")                 # картка: лише пошук, 10 кредитів
        self.assertEqual((post.calls[-1]["method"], len(post.calls), b.spent), ("getTransactionsForAddress", 2, 11))
        self.assertFalse(wa.funder_pending("APP"))
        old = Cache()
        old["funder:OLD"] = {"funder": None}                                     # записаний до цієї позначки: дочитаний
        wa = WalletAge(url=HX, post=FakePost([]), sleep=lambda s: None, pace_s=0, cache=old)
        self.assertEqual((wa.funder("OLD", "s"), wa.funder_pending("OLD")), (None, False))

    def test_could_be_fresh(self):
        buy = 100 * H
        self.assertTrue(tags.could_be_fresh(buy, {"oldest_ms": buy - 2 * H, "exact": True}))
        self.assertFalse(tags.could_be_fresh(buy, {"oldest_ms": buy - 30 * H, "exact": True}))
        # неточний: найстаріша прочитана транзакція — за 30 годин до покупки, отже перша ще старша: точно не fresh
        self.assertFalse(tags.could_be_fresh(buy, {"oldest_ms": buy - 30 * H, "exact": False}))
        self.assertTrue(tags.could_be_fresh(buy, {"oldest_ms": buy - 2 * H, "exact": False}))   # може: дочитати
        self.assertTrue(tags.could_be_fresh(buy, {"oldest_ms": buy + 5 * H, "exact": False}))   # прочитане — після покупки
        self.assertFalse(tags.could_be_fresh(None, {"oldest_ms": 1, "exact": False}))

    def test_funder_from_tx(self):
        keys = [{"pubkey": "FUNDER", "signer": True}, {"pubkey": "NEWWALLET", "signer": False}, {"pubkey": "11111111111111111111111111111111", "signer": False}]
        tx = {"transaction": {"message": {"accountKeys": keys}},
              "meta": {"preBalances": [5_000_000_000, 0, 1], "postBalances": [4_899_995_000, 100_000_000, 1]}}
        self.assertEqual(funder_from_tx(tx, "NEWWALLET"), "FUNDER")
        self.assertIsNone(funder_from_tx(tx, "FUNDER"))                                 # its own balance fell
        self.assertIsNone(funder_from_tx({"transaction": {"message": {"accountKeys": keys}}, "meta": {"preBalances": [1], "postBalances": [1]}}, "NEWWALLET"))
        self.assertIsNone(funder_from_tx(None, "NEWWALLET"))
        post = FakePost([sigs(3), [], {"transaction": {"message": {"accountKeys": keys}}, "meta": {"preBalances": [5, 0, 1], "postBalances": [3, 2, 1]}}])
        wa = WalletAge(post=post, sleep=lambda s: None, pace_s=0)
        age = wa.oldest_tx("NEWWALLET")
        self.assertEqual(age["oldest_sig"], "2")                                         # найстаріший = останній у списку
        self.assertEqual(wa.funder("NEWWALLET", age["oldest_sig"]), "FUNDER")
        self.assertEqual(post.calls[-1]["method"], "getTransaction")
        self.assertEqual(post.urls[-1], wa.tx_url)          # транзакція йде в ноду, яка це вміє

    def test_is_fresh(self):
        buy = 10 * H
        self.assertTrue(tags.is_fresh(buy, {"oldest_ms": buy - 2 * H, "exact": True}))
        self.assertFalse(tags.is_fresh(buy, {"oldest_ms": buy - 30 * H, "exact": True}))
        self.assertFalse(tags.is_fresh(buy, {"oldest_ms": buy - 2 * H, "exact": False}))   # only a bound
        self.assertFalse(tags.is_fresh(None, {"oldest_ms": 1, "exact": True}))
        self.assertEqual(tags.with_tag(["re-bought"], "fresh"), ["fresh", "re-bought"])



class TestRpcBudget(unittest.TestCase):
    """RPC — окремий гаманець кредитів: межа стоїть на кредитах місяця, а не на кількості гаманців."""

    def test_spend_pauses_at_the_reserve_and_a_new_month_starts_clean(self):
        import tempfile, os
        t = [1_790_000_000]                                   # вересень 2026
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rpc.json")
            b = MonthBudget(path, limit=100, reserve_pct=10, now=lambda: t[0])
            b.spend(80)
            self.assertFalse(b.exhausted())
            b.spend(10)
            self.assertTrue(b.exhausted())                    # 90 з 100: лишився лише резерв
            b.flush()
            again = MonthBudget(path, limit=100, reserve_pct=10, now=lambda: t[0])
            self.assertEqual(again.spent, 90)                 # переживає перезапуск
            t[0] += 40 * 86400                                # наступний місяць
            self.assertFalse(again.exhausted())
            self.assertEqual(again.state()["spent"], 0)

    def test_only_the_paid_node_is_counted(self):
        b = MonthBudget(None, limit=1000)
        free = WalletAge(url=DEFAULT_URL, tx_url=DEFAULT_URL, post=FakePost([sigs(3), []]), sleep=lambda s: None, pace_s=0, budget=b)
        free.oldest_tx("W1")
        self.assertEqual(b.spent, 0)                          # публічна нода нічого не коштує
        paid = WalletAge(url="https://rpc.example/?k", tx_url=DEFAULT_URL, post=FakePost([sigs(3), [], {"meta": {}}]),
                         sleep=lambda s: None, pace_s=0, budget=b)
        age = paid.oldest_tx("W2")
        self.assertEqual(b.spent, 20)                         # дві сторінки підписів по 10 кредитів
        paid.funder("W2", age["oldest_sig"])
        self.assertEqual(b.spent, 20)                         # транзакцію читає публічна нода

    def test_enrichment_pauses_on_the_budget_and_keeps_cached_wallets_free(self):
        from types import SimpleNamespace
        from tracced.web.app import make_enricher

        class Cache(dict):
            def put(self, k, v): self[k] = v
            def flush(self): pass
        b = MonthBudget(None, limit=44, reserve_pct=10)       # пауза з 39.6 кредита: два гаманці по 20 = 40
        cache = Cache()
        cache["W9"] = {"oldest_ms": 1000, "exact": True, "n": 3, "oldest_sig": "s"}
        answers = [sigs(3), []] * 2
        wa = WalletAge(url="https://rpc.example/?k", post=FakePost(answers), sleep=lambda s: None, pace_s=0,
                       cache=cache, budget=b)
        rows = [{"wallet": w, "first_buy_ms": 2000, "tag_list": []} for w in ("W1", "W2", "W3", "W9")]
        job = SimpleNamespace(result={"rows": rows}, log=[])
        saved = []
        make_enricher(wa, {"age_lookups_max": 10})(job, saved.append)
        e = job.result["enrich"]
        self.assertEqual(e["done"], 2)                        # W1 і W2 перевірені, на W3 бюджет скінчився
        self.assertEqual(e["paused"], "rpc-budget")
        self.assertEqual(b.spent, 40)
        self.assertTrue(any("paused" in m for m in job.log))
        self.assertTrue(saved)


    def test_the_top_gets_the_full_check_and_the_rest_the_cheap_one(self):
        """Перший за PnL: точний вік зайнятого гаманця і пошук спонсора застосунку. Решта: сторінка до покупки й перша
        транзакція; вік дочитується лише тому, хто ще може виявитись `fresh`, — тег лишається точним."""
        from types import SimpleNamespace
        from tracced.web.app import make_enricher
        from tracced.early.wallet_age import LIMIT

        class Cache(dict):
            def get(self, k): return dict.get(self, k)
            def put(self, k, v): self[k] = v
            def flush(self): pass
        HX = "https://mainnet.helius-rpc.com/?api-key=x"
        buy_s = 1_790_000_000

        def tx(wallet, gain, sender):
            keys = [{"pubkey": "PAYER", "signer": True}, {"pubkey": sender, "signer": True}, {"pubkey": wallet, "signer": False}]
            return {"meta": {"err": None, "preBalances": [5_000_000, 9_000_000_000, 0],
                             "postBalances": [4_995_000, 9_000_000_000 - gain, gain]},
                    "transaction": {"message": {"accountKeys": keys}}}
        post = FakePost([
            # вік: TOP — повна сторінка, тоді «від найстарішої»
            sigs(LIMIT, oldest_s=buy_s - 90 * 86400), {"data": [{"signature": "t1", "blockTime": buy_s - 400 * 86400}]},
            # OLD — тисяча транзакцій, найстаріша прочитана за 30 годин до покупки: точно не fresh, далі не читаємо
            sigs(LIMIT, oldest_s=buy_s - 30 * 3600),
            # BOT — тисяча транзакцій за останню годину до покупки: може бути свіжим, дочитуємо (вийшло: 2 години)
            sigs(LIMIT, oldest_s=buy_s - 3600), {"data": [{"signature": "b1", "blockTime": buy_s - 2 * 3600}]},
            # NEW — уся історія на одній сторінці
            sigs(5, oldest_s=buy_s - 3 * 86400),
            # спонсори: TOP — перша транзакція без SOL, пошук серед перших ста; BOT — перша транзакція; NEW — лише перша
            tx("TOP", 0, "X"), {"data": [tx("TOP", 3_000_000, "EXCHANGE")]},
            tx("BOT", 2_000_000, "BUNDLER"),
            tx("NEW", 0, "X"),
        ])
        b = MonthBudget(None, limit=100_000)
        wa = WalletAge(url=HX, post=post, sleep=lambda s: None, pace_s=0, budget=b, cache=Cache())
        rows = [{"wallet": w, "first_buy_ms": buy_s * 1000, "tag_list": [], "entry_tx": "buy-" + w}
                for w in ("TOP", "OLD", "BOT", "NEW")]
        job = SimpleNamespace(result={"rows": rows}, log=[])
        make_enricher(wa, {"age_lookups_max": 10, "age_full_top": 1})(job, lambda j: True)
        r = job.result
        self.assertFalse(post.answers)                                        # рівно ці виклики, не більше
        self.assertEqual([c["params"][1].get("before") for c in post.calls[:1]], ["buy-TOP"])
        self.assertEqual((r["ages"]["TOP"]["exact"], r["ages"]["OLD"]["exact"], r["ages"]["BOT"]["exact"]), (True, False, True))
        self.assertEqual(r["fresh_wallets"], ["BOT"])
        self.assertEqual(r["funders"], {"TOP": "EXCHANGE", "BOT": "BUNDLER"})
        self.assertTrue(wa.funder_pending("NEW"))                             # пошук для NEW — з картки, якщо відкриють
        self.assertEqual(b.spent, (1 + 10 + 1 + 10) + 1 + (1 + 10 + 1) + (1 + 1))
        self.assertEqual((r["enrich"]["done"], r["enrich"]["funders_done"], r["enrich"]["total"]), (4, 4, 4))

    def test_enrichment_stops_when_the_analysis_is_deleted(self):
        from types import SimpleNamespace
        from tracced.web.app import make_enricher
        answers = [sigs(3), []] * 60
        post = FakePost(answers)
        wa = WalletAge(post=post, sleep=lambda s: None, pace_s=0)
        rows = [{"wallet": f"W{i}", "first_buy_ms": 2000, "tag_list": []} for i in range(60)]
        job = SimpleNamespace(result={"rows": rows}, log=[])
        make_enricher(wa, {"age_lookups_max": 100})(job, lambda j: False)   # save() каже: аналізу вже нема
        self.assertEqual(job.result["enrich"]["done"], 25)                    # зупинилось на першому збереженні
        self.assertEqual(len(post.calls), 50)


if __name__ == "__main__":
    unittest.main()
