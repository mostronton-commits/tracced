import unittest

from tracced.early import ledger

T0 = 1_000_000_000_000
MIN = 60_000
SUPPLY = 1_000_000


def tr(minute, typ, wallet, qty, price):
    return {"wallet": wallet, "type": typ, "time": T0 + minute * MIN, "qty": qty,
            "usd": qty * price, "price": price, "tx": f"tx-{wallet}-{minute}-{typ}", "program": "x"}


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.t_from, self.t_to, self.t_exit = T0, T0 + 20 * MIN, T0 + 60 * MIN

    def run_one(self, trades):
        L, stats = ledger.build(trades, self.t_from, self.t_to, self.t_exit)
        return L, stats

    def test_buy_then_partial_sell(self):
        L, _ = self.run_one([tr(1, "buy", "A", 100, 1.0), tr(10, "sell", "A", 50, 3.0)])
        f = ledger.facts(L["A"], SUPPLY, price_at_exit=2.0)
        self.assertAlmostEqual(f["invested_usd"], 100)
        self.assertAlmostEqual(f["proceeds_usd"], 150)
        self.assertAlmostEqual(f["realized_usd"], 100)          # 50×3 − 50×1
        self.assertAlmostEqual(f["unrealized_usd"], 50)         # 50 лишилось × $2 − собівартість 50
        self.assertAlmostEqual(f["entry_mcap_first"], 1.0 * SUPPLY)
        self.assertAlmostEqual(f["entry_mcap_avg"], 1.0 * SUPPLY)
        self.assertAlmostEqual(f["exit_mcap_avg"], 3.0 * SUPPLY)
        self.assertAlmostEqual(f["multiple"], 3.0)
        self.assertAlmostEqual(f["sold_share_pct"], 50)
        self.assertAlmostEqual(f["holding_share_pct"], 50)
        self.assertAlmostEqual(f["hold_minutes"], 9)
        self.assertFalse(f["partial_history"])
        self.assertFalse(f["bought_after_range"])

    def test_entry_mcap_first_is_first_price(self):
        L, _ = self.run_one([tr(1, "buy", "A", 100, 1.0), tr(2, "buy", "A", 100, 3.0)])
        f = ledger.facts(L["A"], SUPPLY, 0)
        self.assertAlmostEqual(f["entry_mcap_first"], 1.0 * SUPPLY)
        self.assertAlmostEqual(f["entry_mcap_avg"], 2.0 * SUPPLY)   # VWAP (100+300)/200
        self.assertIsNone(f["exit_mcap_avg"])
        self.assertIsNone(f["multiple"])
        self.assertIsNone(f["hold_minutes"])

    def test_sell_without_buy_means_pre_window(self):
        L, _ = self.run_one([tr(2, "sell", "B", 10, 1.0)])
        early, counts = ledger.classify(L, self.t_to, 20)
        self.assertEqual(early, [])
        self.assertEqual(counts["pre_range_only"], 1)

    def test_late_and_dust(self):
        L, _ = self.run_one([tr(30, "buy", "C", 100, 1.0),      # після «до» → пізній
                             tr(2, "buy", "E", 10, 1.0)])         # $10 < $20 → пил
        early, counts = ledger.classify(L, self.t_to, 20)
        self.assertEqual(early, [])
        self.assertEqual(counts["late"], 1)
        self.assertEqual(counts["dust"], 1)

    def test_bought_after_window_flag(self):
        L, _ = self.run_one([tr(5, "buy", "F", 100, 1.0), tr(25, "buy", "F", 100, 2.0)])
        early, _ = ledger.classify(L, self.t_to, 20)
        self.assertEqual([l.wallet for l in early], ["F"])
        f = ledger.facts(L["F"], SUPPLY, 0)
        self.assertTrue(f["bought_after_range"])
        self.assertEqual(f["buys_in_range"], 1)
        self.assertAlmostEqual(f["invested_in_range_usd"], 100)   # лише покупка до «до»
        self.assertAlmostEqual(f["invested_usd"], 300)             # усього до горизонту
        self.assertEqual(f["buys"], 2)

    def test_oversold_marks_partial_history(self):
        L, _ = self.run_one([tr(1, "buy", "G", 100, 1.0), tr(5, "sell", "G", 150, 2.0)])
        f = ledger.facts(L["G"], SUPPLY, 0)
        self.assertTrue(f["partial_history"])
        self.assertAlmostEqual(f["realized_usd"], 100)          # рахуємо лише наявні 100
        self.assertAlmostEqual(f["proceeds_usd"], 200)          # 300 × (100/150)

    def test_pre_window_sell_not_counted_as_exit(self):
        # продав до покупки (позиція з-перед «від»), потім купив і продав уже нашу покупку
        L, _ = self.run_one([tr(2, "sell", "H", 10, 1.0), tr(5, "buy", "H", 100, 1.0),
                             tr(10, "sell", "H", 100, 2.0)])
        f = ledger.facts(L["H"], SUPPLY, 0)
        self.assertEqual(L["H"].sold_without_buy, 1)
        self.assertEqual(f["sells"], 1)
        self.assertEqual(f["first_sell_ms"], T0 + 10 * MIN)     # не 2-га хвилина
        self.assertAlmostEqual(f["hold_minutes"], 5)
        self.assertAlmostEqual(f["realized_usd"], 100)
        self.assertTrue(f["partial_history"])

    def test_facts_from_stats(self):
        L, _ = self.run_one([tr(1, "buy", "A", 100, 1.0)])
        st = {"invested": 140.0, "proceeds": 150.0, "bought": 110.0, "sold": 50.0, "buys": 2, "sells": 1,
              "first_buy": T0 + MIN, "first_sell": T0 + 10 * MIN, "last_sell": T0 + 10 * MIN,
              "realized": 100.0, "unrealized": 60.0}
        f = ledger.facts_from_stats(L["A"], st, SUPPLY)
        self.assertEqual(f["source"], "wallet-stats")
        self.assertAlmostEqual(f["entry_mcap_avg"], 1.0 * SUPPLY)          # from our window ledger
        self.assertAlmostEqual(f["exit_mcap_avg"], 3.0 * SUPPLY)           # 150 / 50 × supply
        self.assertAlmostEqual(f["sold_share_pct"], 50 / 110 * 100)
        self.assertAlmostEqual(f["hold_minutes"], 9)
        self.assertTrue(f["bought_after_range"])                           # 2 buys lifetime vs 1 in window
        self.assertFalse(f["partial_history"])
        st["first_buy"] = T0 - 5 * MIN                                       # traded before our window
        self.assertTrue(ledger.facts_from_stats(L["A"], st, SUPPLY)["partial_history"])
        e = ledger.facts_entry_only(L["A"], SUPPLY)
        self.assertEqual(e["source"], "entry-only")
        self.assertIsNone(e["realized_usd"])
        self.assertAlmostEqual(e["invested_in_range_usd"], 100)

    def test_outside_range_ignored(self):
        L, stats = self.run_one([tr(-5, "buy", "A", 100, 1.0), tr(61, "sell", "A", 100, 5.0),
                                 tr(3, "buy", "A", 10, 1.0)])
        self.assertEqual(stats["n_trades"], 1)
        self.assertEqual(L["A"].buys, 1)
        self.assertEqual(L["A"].sells, 0)

    def test_normalize_st_record(self):
        n = ledger.normalize({"wallet": "W", "type": "buy", "time": 1783382957000, "amount": 5.5,
                              "priceUsd": 2.0, "volume": 11.0, "tx": "t", "program": "pump"})
        self.assertEqual(n["time"], 1783382957000)
        self.assertEqual(n["qty"], 5.5)
        self.assertEqual(n["usd"], 11.0)
        self.assertEqual(ledger.normalize({"time": 1783382957})["time"], 1783382957000)


if __name__ == "__main__":
    unittest.main()
