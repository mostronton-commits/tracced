"""Мітки InsightX для спонсорів: назви, кеш, квота, і що з ними робить збагачення. Без мережі."""
import unittest
import urllib.error
from types import SimpleNamespace

from tracced.early import labels
from tracced.early.wallet_age import MonthBudget


class Cache(dict):
    def get(self, k): return dict.get(self, k)
    def put(self, k, v): self[k] = v
    def flush(self): pass


class FakeIX:
    def __init__(self, known, fail=None):
        self.known, self.fail, self.urls = known, fail, []

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise self.fail
        return [{"address": a, "label": self.known[a][0], "tags": [self.known[a][1]], "smart_contract": False}
                for a in url.rsplit("/", 1)[1].split(",") if a in self.known]


class TestNames(unittest.TestCase):
    def test_short_names(self):
        for label, name in [("Binance: Hot Wallet", "Binance"), ("Coinbase Hot Wallet 3", "Coinbase"), ("Moonpay: Hot Wallet", "MoonPay"),
                            ("MoonPay Hot Wallet", "MoonPay"), ("Kucoin", "KuCoin"), ("Gate.io: Hot Wallet", "Gate.io"),
                            ("Unibot SOL Fee Address (New)", "Unibot"), ("Stake.com", "Stake.com"), ("Relay: Solver", "Relay")]:
            self.assertEqual(labels.short_name(label), name, label)
        self.assertIsNone(labels.entry_of({"address": "A", "label": None}))
        self.assertEqual(labels.entry_of({"address": "A", "label": "Stake.com", "tags": ["Gambling"]}),
                         {"name": "Stake.com", "label": "Stake.com", "kind": "gambling"})
        self.assertEqual(labels.kind_text("gambling"), "a gambling site")
        self.assertEqual(labels.kind_text("whale"), "a known service")


class TestLookup(unittest.TestCase):
    def make(self, known, **kw):
        post = FakeIX(known, kw.pop("fail", None))
        ix = labels.InsightX("key", cache=Cache(), budget=MonthBudget(None, limit=kw.pop("limit", 1000), reserve_pct=10),
                             pace_s=0, post=post, sleep=lambda s: None, **kw)
        return ix, post

    def test_batches_of_a_hundred_and_a_cap_per_run(self):
        addrs = [f"F{i:03d}" for i in range(250)]
        ix, post = self.make({"F001": ("Binance: Hot Wallet", "exchange"), "F200": ("Stake.com", "gambling")})
        got = ix.lookup(addrs, max_calls=2)
        self.assertEqual(len(post.urls), 2)                                     # 2 of the 3 batches this time
        self.assertEqual(len(post.urls[0].rsplit("/", 1)[1].split(",")), 100)
        self.assertEqual(got, {"F001": {"name": "Binance", "label": "Binance: Hot Wallet", "kind": "exchange"}})
        got = ix.lookup(addrs, max_calls=2)                                     # the asked ones come from the cache
        self.assertEqual(len(post.urls), 3)
        self.assertEqual(sorted(got), ["F001", "F200"])
        self.assertEqual((ix.requests, ix.budget.spent), (3, 3))
        self.assertEqual(ix.cached("F002"), (True, None))                       # asked, no label: remembered too

    def test_no_label_is_asked_again_after_a_week_a_label_after_a_month(self):
        now = [1_000_000.0]
        ix, post = self.make({"A": ("OKX Hot Wallet", "exchange")}, now=lambda: now[0])
        ix.lookup(["A", "B"])
        now[0] += 8 * 86_400
        self.assertEqual((ix.cached("A")[0], ix.cached("B")[0]), (True, False))
        now[0] += 30 * 86_400
        self.assertEqual(ix.cached("A")[0], False)

    def test_the_quota_and_a_refusal_stop_the_asking(self):
        ix, post = self.make({}, limit=10)
        ix.budget.spend(9)                                                      # 9 of 10 with a 10% reserve: paused
        self.assertEqual(ix.lookup(["A"]), {})
        self.assertEqual(post.urls, [])
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        ix, post = self.make({}, fail=err)
        self.assertEqual(ix.lookup([f"A{i}" for i in range(300)], max_calls=3), {})
        self.assertEqual(len(post.urls), 1)                                     # 429: the rest waits for the next run


class TestEnrichment(unittest.TestCase):
    def test_labels_name_funders_and_unmake_an_exchange_bundle(self):
        from tracced.web import app as app_mod
        ix = labels.InsightX("key", cache=Cache(), pace_s=0, sleep=lambda s: None,
                             post=FakeIX({"CB": ("Coinbase Hot Wallet 2", "exchange"), "ST": ("Stake.com", "gambling")}))
        r = {"funders": {"W1": "CB", "W2": "CB", "W3": "CB", "W4": "ST", "W5": "OP", "W6": "OP", "W7": "OP"}}
        job = SimpleNamespace(log=[])
        app_mod._label_funders(r, ix, {"insightx_calls_per_run": 3}, job)
        self.assertEqual(r["labels"], {"CB": ["Coinbase", "Coinbase Hot Wallet 2", "exchange"], "ST": ["Stake.com", "Stake.com", "gambling"]})
        self.assertTrue(r["labels_at"])
        self.assertIn("InsightX named 2 funders (1 exchanges) in 1 request", job.log[-1])
        app_mod._check_services(r, None)
        self.assertEqual(set(r["services"]), {"CB", "ST"})                     # funds strangers: no bundle from it
        rows = [{"wallet": w, "tag_list": []} for w in r["funders"]]
        app_mod._bundles(r, rows)
        self.assertEqual(sorted(r["bundle"]), ["W5", "W6", "W7"])               # one operator's three wallets stay a bundle
        exch, flab = app_mod._labels_for_page(r)
        self.assertEqual(exch["CB"], ["Coinbase", "Coinbase Hot Wallet 2 · label: InsightX"])
        self.assertEqual(flab["ST"], ["Stake.com", "Stake.com · label: InsightX", "a gambling site"])
        app_mod._label_funders(r, None, {}, job)                                # no key: nothing changes, nothing breaks


if __name__ == "__main__":
    unittest.main()
