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


if __name__ == "__main__":
    unittest.main()
