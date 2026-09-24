import unittest

from tracced.early import ledger

T0 = 1_000_000_000_000
MIN = 60_000
SUPPLY = 1_000_000


def tr(minute, typ, wallet, qty, price):
    return {"wallet": wallet, "type": typ, "time": T0 + minute * MIN, "qty": qty,
            "usd": qty * price, "price": price, "tx": f"tx-{wallet}-{minute}-{typ}", "program": "x"}


class TestUnbackedTokens(unittest.TestCase):
    """Продано більше, ніж куплено: токени прийшли переказом, а не з біржі. Дрібна різниця — похибка."""

    def facts_of(self, trades, wallet="W"):
        L, _ = ledger.build(trades, T0, T0 + 20 * MIN, T0 + 60 * MIN)
        return ledger.facts(L[wallet], SUPPLY, 1.0)

    def test_selling_much_more_than_bought_is_flagged(self):
        f = self.facts_of([tr(1, "buy", "W", 100, 1.0), tr(5, "sell", "W", 400, 2.0)])
        self.assertTrue(f["partial_history"])

    def test_rounding_on_a_full_exit_is_not(self):
        # сотні угод накопичують похибку: продаж «усього» виходить на мікрон більшим за куплене
        trades = [tr(i, "buy", "W", 0.1, 1.0) for i in range(1, 60)]
        bought = sum(t["qty"] for t in trades)
        trades.append(tr(61, "sell", "W", bought * (1 + 1e-12), 2.0))
        f = self.facts_of(trades)
        self.assertFalse(f["partial_history"])

    def test_selling_without_ever_buying_is_flagged(self):
        f = self.facts_of([tr(1, "sell", "W", 500, 2.0), tr(2, "buy", "W", 10, 1.0)])
        self.assertTrue(f["partial_history"])


class TestSolAmounts(unittest.TestCase):
    """Кожна угода несе і долари, і SOL. Сайт показує те, що записав своп, а не сьогоднішній курс."""

    def test_the_raw_swap_carries_the_sol_leg(self):
        raw = {"wallet": "A", "type": "buy", "time": 1, "amount": 10, "volume": 20.0,
               "volumeSol": 0.1, "priceUsd": 2.0, "tx": "t", "program": "p"}
        self.assertEqual(ledger.normalize(raw)["sol"], 0.1)
        self.assertIsNone(ledger.normalize({k: v for k, v in raw.items() if k != "volumeSol"})["sol"])

    def facts_of(self, trades):
        L, _ = ledger.build(trades, T0, T0 + 20 * MIN, T0 + 60 * MIN)
        return ledger.facts(L["A"], SUPPLY, price_at_exit=2.0)

    def with_sol(self, t, sol):
        t["sol"] = sol
        return t

    def test_sums_follow_the_trades(self):
        f = self.facts_of([self.with_sol(tr(1, "buy", "A", 100, 1.0), 0.5),
                           self.with_sol(tr(30, "buy", "A", 100, 1.0), 0.4),    # за межами діапазону
                           self.with_sol(tr(40, "sell", "A", 100, 3.0), 1.2)])
        self.assertAlmostEqual(f["invested_sol"], 0.9)
        self.assertAlmostEqual(f["invested_in_range_sol"], 0.5)
        self.assertAlmostEqual(f["proceeds_sol"], 1.2)

    def test_a_trade_feed_without_sol_says_so_instead_of_showing_zero(self):
        f = self.facts_of([tr(1, "buy", "A", 100, 1.0), tr(10, "sell", "A", 50, 3.0)])
        self.assertIsNone(f["invested_sol"])
        self.assertIsNone(f["proceeds_sol"])
        self.assertIsNone(f["invested_in_range_sol"])

    def test_profit_in_sol_is_counted_the_same_way_as_in_dollars(self):
        # докупив ПІСЛЯ продажу: частка проданого падає, але собівартість проданого не змінюється.
        # Якщо рахувати SOL через частку, та сама угода дає дві різні відповіді — тут вони мають збігтись.
        rate = 200.0
        f = self.facts_of([self.with_sol(tr(1, "buy", "A", 100, 1.0), 100 / rate),
                           self.with_sol(tr(10, "sell", "A", 50, 3.0), 150 / rate),
                           self.with_sol(tr(50, "buy", "A", 10, 4.0), 40 / rate)])
        self.assertAlmostEqual(f["realized_usd"], 100)
        self.assertAlmostEqual(f["realized_sol"], 100 / rate)

    def test_a_wallet_with_sol_on_only_some_trades_keeps_dollars(self):
        f = self.facts_of([self.with_sol(tr(1, "buy", "A", 100, 1.0), 0.5),
                           tr(10, "sell", "A", 50, 3.0)])            # у цієї угоди SOL нема
        self.assertIsNone(f["realized_sol"])
        self.assertIsNone(f["invested_sol"])
        self.assertAlmostEqual(f["realized_usd"], 100)


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

    def test_facts_entry_only(self):
        L, _ = self.run_one([tr(1, "buy", "A", 100, 1.0)])
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


class TestRepairQuantities(unittest.TestCase):
    """Джерело інколи віддає кількість токенів іншого порядку; долари при цьому правильні."""

    def market(self, n=40, price=0.01, t0=1_000_000_000_000):
        return [{"wallet": f"W{i}", "type": "buy", "time": t0 + i * 1000, "qty": 100.0,
                 "usd": 100.0 * price, "price": price} for i in range(n)]

    def test_broken_amount_is_repriced_from_the_market(self):
        tr = self.market()
        broken = {"wallet": "B", "type": "sell", "time": tr[20]["time"], "qty": 5.8e-11,
                  "usd": 1821.71, "price": 3.1e13}
        tr.append(broken)
        n = ledger.repair_quantities(tr)
        self.assertEqual(n, 1)
        self.assertTrue(broken["repaired"])
        self.assertAlmostEqual(broken["price"], 0.01)
        self.assertAlmostEqual(broken["qty"], 182171.0, places=0)     # долари / ринкова ціна
        self.assertEqual(broken["usd"], 1821.71)                      # суму не чіпаємо
        self.assertNotIn("repaired", tr[0])                           # здорові угоди не торкаємось

    def test_real_moves_are_left_alone(self):
        tr = self.market()
        moved = {"wallet": "M", "type": "buy", "time": tr[20]["time"], "qty": 10.0, "usd": 1.0, "price": 0.1}
        tr.append(moved)                                              # 10x дорожче за ринок — це рух, не дефект
        self.assertEqual(ledger.repair_quantities(tr), 0)
        self.assertNotIn("repaired", moved)

    def test_no_reference_and_empty_input(self):
        self.assertEqual(ledger.repair_quantities([]), 0)
        self.assertEqual(ledger.repair_quantities([{"wallet": "A", "type": "buy", "time": 1, "qty": 0, "usd": 0, "price": 0}]), 0)
