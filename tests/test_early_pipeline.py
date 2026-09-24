import tempfile
import unittest

from tracced.early import pipeline, report, settings

T0 = 1_000_000_000_000
MIN = 60_000
H = 3_600_000
SUPPLY = 1_000_000
MINT = "FAKEMINT"


SOL_USD = 200.0     # фіктивний курс лише для фікстур: ST дає обидві суми в одній угоді, перетворення в коді нема


def tr(minute, typ, wallet, qty, price):
    return {"wallet": wallet, "type": typ, "time": T0 + minute * MIN, "qty": qty,
            "usd": qty * price, "price": price, "sol": qty * price / SOL_USD,
            "tx": f"tx-{wallet}-{minute}-{typ}", "program": "x"}


class FakeST:
    def __init__(self, trades, page=3, credits=100):
        self.trades = sorted(trades, key=lambda t: t["time"])
        self.page = page
        self.requests = 0
        self.flushed = False
        self._credits = credits

    def token_info(self, mint):
        self.requests += 1
        return {"mint": mint, "symbol": "TST", "supply": SUPPLY, "created_time": T0 - H,
                "mcap": 2_000_000, "price_usd": 2.0}

    def trades_page(self, mint, cursor, identity=True):
        self.requests += 1
        chunk = [t for t in self.trades if t["time"] > cursor][:self.page]      # як у ST: курсор виключний
        has_next = bool(chunk) and chunk[-1]["time"] < self.trades[-1]["time"]
        return {"trades": chunk, "hasNextPage": has_next,
                "nextCursor": chunk[-1]["time"] if chunk else None}

    def credits(self):
        self.requests += 1                                # як у ST: /credits теж запит
        return self._credits

    def flush(self):
        self.flushed = True

    def wallet_token_trades(self, wallet, mint, max_pages=4):
        """The wallet's own trades on the token, as ST's by-wallet feed would return them."""
        self.requests += 1
        return [t for t in self.trades if t["wallet"] == wallet]

    def chart(self, mint, interval, t_from, t_to):
        self.requests += 1
        return []                                     # ціна на горизонті — з останньої угоди


TRADES = [
    tr(1, "buy", "A", 100, 1.0), tr(30, "sell", "A", 50, 3.0),   # ранній, частково вийшов
    tr(2, "buy", "C", 5, 1.0),                                    # пил ($5)
    tr(3, "sell", "D", 10, 1.0),                                  # купував до «від»
    tr(25, "buy", "B", 100, 2.0),                                 # пізній (після «до» = 20 хв)
    tr(50, "buy", "A", 10, 4.0),                                  # A докупив після вікна
]


class TestPipeline(unittest.TestCase):
    def test_end_to_end_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(TRADES)
            s = settings.load()
            logs = []
            res = pipeline.run(st, MINT, T0, T0 + 20 * MIN, s, log=logs.append,
                               store_dir=d, now_ms=T0 + 2 * H)
            self.assertEqual([r["wallet"] for r in res["rows"]], ["A"])
            self.assertEqual(res["counts"]["late"], 0)                   # counts come from the entry range now
            self.assertEqual(res["counts"]["pre_range_only"], 1)
            self.assertEqual(res["counts"]["dust"], 1)
            a = res["rows"][0]
            self.assertAlmostEqual(a["realized_usd"], 100)
            self.assertTrue(a["bought_after_range"])
            self.assertEqual(res["price_at_end"], 4.0)              # остання угода до «зараз»
            self.assertGreater(res["pages_fetched"], 0)
            self.assertTrue(st.flushed)
            self.assertTrue(any("page" in m for m in logs))

            st2 = FakeST(TRADES)
            res2 = pipeline.run(st2, MINT, T0, T0 + 20 * MIN, s, store_dir=d,
                                now_ms=T0 + 2 * H)
            self.assertLessEqual(res2["requests"], 2)               # token_info + свічка ціни «зараз» (кешується)
            self.assertEqual(res2["pages_fetched"], 0)
            self.assertEqual([r["wallet"] for r in res2["rows"]], ["A"])
            self.assertEqual(res["coverage"]["exits_known"], 1)     # повний шлях покрив усіх
            self.assertEqual(res["counts"]["lookups"], 0)
            self.assertIn("full trade history", report.coverage_text(res["coverage"]))

    def test_budget_stops_before_spending(self):
        # even the entry window is over its own cap → stop after the first page, nothing else spent
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(TRADES, page=2)
            s = settings.load({"early": {"max_window_pages": 1}})
            with self.assertRaises(pipeline.EarlyError) as cm:
                pipeline.run(st, MINT, T0, T0 + 20 * MIN, s,
                             store_dir=d, max_pages=1, now_ms=T0 + 2 * H)
            self.assertIn("range alone", str(cm.exception))
            self.assertLessEqual(st.requests, 2)                    # token_info + одна сторінка

    def test_hot_token_switches_to_wallet_trades(self):
        # full range (60 min) would need ≈60 pages at the first-page pace (1 min/page) > cap 1,
        # the window (20 min) fits into max_window_pages → exits come from each wallet's own trades
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(TRADES, page=2)
            s = settings.load({"early": {"max_window_pages": 50, "max_wallet_lookups": 10}})
            logs = []
            res = pipeline.run(st, MINT, T0, T0 + 20 * MIN, s, log=logs.append,
                               store_dir=d, max_pages=1, now_ms=T0 + 2 * H)
            self.assertEqual(res["mode"], "wallet-trades")
            self.assertTrue(any("per-wallet" in m for m in logs))
            self.assertEqual([r["wallet"] for r in res["rows"]], ["A"])
            a = res["rows"][0]
            self.assertEqual(a["source"], "wallet-trades")
            self.assertAlmostEqual(a["invested_in_range_usd"], 100)     # from our window ledger
            self.assertAlmostEqual(a["invested_usd"], 140)               # incl. the buy after the window
            self.assertAlmostEqual(a["proceeds_usd"], 150)
            self.assertAlmostEqual(a["realized_usd"], 100)
            self.assertAlmostEqual(a["exit_mcap_avg"], 3.0 * SUPPLY)     # 150 / 50 × supply
            self.assertEqual(a["first_sell_ms"], T0 + 30 * MIN)          # exact time, same as full mode
            self.assertTrue(a["bought_after_range"])
            self.assertEqual(res["counts"]["lookups"], 1)
            self.assertEqual(res["price_at_end"], 4.0)                   # last price seen
            self.assertEqual(res["coverage"]["exits_known"], 1)
            self.assertIn("each wallet's trades fetched", report.coverage_text(res["coverage"]))
            # the C wallet is dust; B is late → only A; nothing beyond the cap
            self.assertEqual(res["counts"]["entry_only"], 0)

    def test_wallet_lookup_cap_leaves_entry_only(self):
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(TRADES, page=2)
            s = settings.load({"early": {"max_window_pages": 50, "max_wallet_lookups": 0}})
            res = pipeline.run(st, MINT, T0, T0 + 20 * MIN, s, store_dir=d,
                               max_pages=1, now_ms=T0 + 2 * H)
            a = res["rows"][0]
            self.assertEqual(a["source"], "entry-only")
            self.assertIsNone(a["exit_mcap_avg"])
            self.assertIsNone(a["realized_usd"])
            self.assertAlmostEqual(a["invested_in_range_usd"], 100)
            self.assertEqual(res["counts"]["entry_only"], 1)
            self.assertIn("the rest tagged no-exits", report.coverage_text(res["coverage"]))

    def test_full_range_beats_many_lookups(self):
        # 6 ранніх гаманців, решта діапазону ≈1 сторінка → повний діапазон дешевший за 6 запитів
        trades = [tr(i + 1, "buy", f"W{i}", 100, 1.0) for i in range(6)] + [tr(30 + i, "sell", f"W{i}", 100, 2.0) for i in range(6)]
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(trades, page=6)
            logs = []
            res = pipeline.run(st, MINT, T0, T0 + 20 * MIN, settings.load(), log=logs.append,
                               store_dir=d, max_pages=20, now_ms=T0 + 2 * H)
            self.assertEqual(res["mode"], "trades")
            self.assertEqual(res["counts"]["lookups"], 0)
            self.assertEqual(res["coverage"]["exits_known"], 6)
            self.assertTrue(all(r["first_sell_ms"] for r in res["rows"]))
            self.assertTrue(any("cheapest complete path: whole token history" in m for m in logs))

    def test_budget_guard_refuses_before_spending(self):
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(TRADES, page=2, credits=4)             # 25 % від 4 = 1 запит дозволено
            with self.assertRaises(pipeline.EarlyError) as cm:
                pipeline.run(st, MINT, T0, T0 + 20 * MIN, settings.load(),
                             store_dir=d, now_ms=T0 + 2 * H)
            self.assertIn("left this month", str(cm.exception))
            self.assertLessEqual(st.requests, 3)                # token_info + перша сторінка + /credits

    def test_page_cap_falls_back_to_per_wallet(self):
        # оцінка з рідкого вікна обіцяє 1 сторінку, а дірка щільна → стеля → відкат на угоди гаманця
        trades = [tr(1, "buy", "A", 100, 1.0), tr(2, "buy", "B", 100, 1.0)] + \
                 [tr(21 + i, "sell" if i % 2 else "buy", "A" if i % 2 else "B", 10, 2.0) for i in range(20)]
        with tempfile.TemporaryDirectory() as d:
            st = FakeST(trades, page=2)
            logs = []
            res = pipeline.run(st, MINT, T0, T0 + 20 * MIN, settings.load(), log=logs.append,
                               store_dir=d, max_pages=4, now_ms=T0 + 2 * H)
            self.assertEqual(res["mode"], "wallet-trades")
            self.assertTrue(any("denser than estimated" in m for m in logs))
            self.assertEqual(res["coverage"]["exits_known"], 2)

    def test_bad_window(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(pipeline.EarlyError):
                pipeline.run(FakeST(TRADES), MINT, T0 + H, T0, settings.load(),
                             store_dir=d, now_ms=T0 + 2 * H)

    def test_no_supply(self):
        class NoSupply(FakeST):
            def token_info(self, mint):
                return {"mint": mint, "supply": None}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(pipeline.EarlyError):
                pipeline.run(NoSupply(TRADES), MINT, T0, T0 + MIN, settings.load(),
                             store_dir=d, now_ms=T0 + 2 * H)



class SlowST(FakeST):
    """Угоди гаманця приходять із затримкою; рахуємо, скільки викликів ідуть одночасно.

    Затримка тим довша, чим вище гаманець у рейтингу: потоки завершуються в зворотному порядку, і таблиця
    мусить однаково лишитись у порядку рейтингу. `cost` — скільки запитів коштує один гаманець."""

    def __init__(self, trades, page=2, cost=1, delay=0.05):
        super().__init__(trades, page=page)
        import threading
        self.lock = threading.Lock()
        self.in_flight = self.max_in_flight = 0
        self.cost, self.delay = cost, delay
        self.first_wallet_at = None

    def wallet_token_trades(self, wallet, mint, max_pages=4):
        import time as _t
        with self.lock:
            if self.first_wallet_at is None:
                self.first_wallet_at = self.requests
            self.requests += self.cost
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            rank = int(wallet[1:])                          # W0 вклав найбільше, отже він перший у рейтингу
            _t.sleep(self.delay * (1 + (12 - rank) / 12))
            return [t for t in self.trades if t["wallet"] == wallet]
        finally:
            with self.lock:
                self.in_flight -= 1


def many_wallets(n=12):
    """n гаманців купують у діапазоні різні суми (W0 найбільше) і продають після нього."""
    return [tr(1 + i, "buy", f"W{i}", 100 + 10 * (n - i), 1.0) for i in range(n)] + \
           [tr(30 + i, "sell", f"W{i}", 50, 2.0) for i in range(n)]


class TestParallelWallets(unittest.TestCase):
    """Pro не обмежує швидкість: угоди різних гаманців тягнемо кількома потоками одночасно."""

    def run_fake(self, st, d, **over):
        s = settings.load({"early": dict({"max_window_pages": 50, "max_wallet_lookups": 50, "st_concurrency": 4}, **over)})
        logs = []
        res = pipeline.run(st, MINT, T0, T0 + 20 * MIN, s, log=logs.append, store_dir=d,
                           max_pages=1, now_ms=T0 + 2 * H)      # max_pages=1: повна історія не влазить → по гаманцях
        return res, logs

    def test_wallets_are_fetched_in_parallel_and_kept_in_rank_order(self):
        with tempfile.TemporaryDirectory() as d:
            st = SlowST(many_wallets())
            res, _ = self.run_fake(st, d)
            self.assertEqual(res["mode"], "wallet-trades")
            self.assertGreaterEqual(st.max_in_flight, 2)
            self.assertLessEqual(st.max_in_flight, 4)
            self.assertEqual(res["coverage"]["exits_known"], 12)
            self.assertEqual(list(res["wallet_trades"]), [f"W{i}" for i in range(12)])   # рейтинг, не завершення
            self.assertTrue(all(v["source"] == "wallet-trades" for v in res["wallet_trades"].values()))

    def test_one_thread_is_the_old_sequential_path(self):
        with tempfile.TemporaryDirectory() as d:
            st = SlowST(many_wallets(), delay=0.005)
            res, _ = self.run_fake(st, d, st_concurrency=1)
            self.assertEqual(st.max_in_flight, 1)
            self.assertEqual(res["coverage"]["exits_known"], 12)

    def test_run_cap_never_overshoots_under_concurrency(self):
        # кожен гаманець коштує 4 запити; стеля — 16 запитів понад те, що пішло до гаманців
        with tempfile.TemporaryDirectory() as d:
            probe = SlowST(many_wallets(), cost=4, delay=0.001)
            self.run_fake(probe, d, max_wallet_trade_pages=4)
            base = probe.first_wallet_at
        with tempfile.TemporaryDirectory() as d:
            st = SlowST(many_wallets(), cost=4, delay=0.02)
            cap = base + 16
            res, logs = self.run_fake(st, d, max_wallet_trade_pages=4, run_cap_requests=cap)
            self.assertLessEqual(st.requests, cap)                # стеля не перевищена навіть на один запит
            self.assertEqual(res["coverage"]["exits_known"], 4)   # рівно 16 / 4 гаманці
            self.assertEqual(res["counts"]["entry_only"], 8)
            self.assertTrue(any("request cap" in m for m in logs))
            fetched = [w for w, v in res["wallet_trades"].items() if v["source"] == "wallet-trades"]
            self.assertEqual(fetched, ["W0", "W1", "W2", "W3"])          # стартують найвищі в рейтингу

    def test_a_failing_wallet_stays_entry_only_and_the_rest_go_on(self):
        class Flaky(SlowST):
            def wallet_token_trades(self, wallet, mint, max_pages=4):
                if wallet == "W3":
                    raise RuntimeError("boom")
                return super().wallet_token_trades(wallet, mint, max_pages)
        with tempfile.TemporaryDirectory() as d:
            st = Flaky(many_wallets(), delay=0.005)
            res, logs = self.run_fake(st, d)
            self.assertEqual(res["wallet_trades"]["W3"]["source"], "entry-only")
            self.assertEqual(res["coverage"]["exits_known"], 11)
            self.assertTrue(any("W3" in m and "unavailable" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
