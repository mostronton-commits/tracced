import tempfile
import unittest

from tracced.early import pipeline, report, settings

T0 = 1_000_000_000_000
MIN = 60_000
H = 3_600_000
SUPPLY = 1_000_000
MINT = "FAKEMINT"


def tr(minute, typ, wallet, qty, price):
    return {"wallet": wallet, "type": typ, "time": T0 + minute * MIN, "qty": qty,
            "usd": qty * price, "price": price, "tx": f"tx-{wallet}-{minute}-{typ}", "program": "x"}


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

    def trades_page(self, mint, cursor):
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


if __name__ == "__main__":
    unittest.main()
