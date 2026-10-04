import unittest

from tracced.early import tags

T0 = 1_000_000_000_000
S = 1000
MIN = 60_000
H = 3_600_000


def facts(**kw):
    base = {"first_buy_ms": T0 + 5 * MIN, "buys": 1, "sells": 1, "hold_minutes": 30.0,
            "partial_history": False, "bought_after_range": False, "source": "trades"}
    base.update(kw)
    return base


class TestTags(unittest.TestCase):
    def test_sniper(self):
        self.assertIn("sniper", tags.compute(facts(first_buy_ms=T0 + 45 * S), created_ms=T0))
        self.assertNotIn("sniper", tags.compute(facts(first_buy_ms=T0 + 61 * S), created_ms=T0))
        self.assertNotIn("sniper", tags.compute(facts(), created_ms=None))

    def test_fresh(self):
        fb = T0 + 5 * MIN
        self.assertIn("fresh", tags.compute(facts(first_buy_ms=fb), wallet_first_tx_ms=fb - 3 * H))
        self.assertNotIn("fresh", tags.compute(facts(first_buy_ms=fb), wallet_first_tx_ms=fb - 30 * H))
        self.assertNotIn("fresh", tags.compute(facts(first_buy_ms=fb), wallet_first_tx_ms=None))

    def test_bot_like_by_trades_and_hold(self):
        f = facts(buys=20, sells=15, hold_minutes=0.5)
        self.assertIn("bot-like", tags.compute(f))
        self.assertNotIn("bot-like", tags.compute(facts(buys=20, sells=15, hold_minutes=10.0)))
        self.assertNotIn("bot-like", tags.compute(facts(buys=5, sells=5, hold_minutes=0.5)))

    def test_bot_like_by_quick_pairs(self):
        buys = [T0 + i * 10 * S for i in range(6)]
        sells = [b + 2 * S for b in buys]                     # продаж через 2 с після кожної покупки
        self.assertIn("bot-like", tags.compute(facts(buys=6, sells=6, hold_minutes=10.0), buy_times=buys, sell_times=sells))
        sells_slow = [b + 3 * MIN for b in buys]
        self.assertNotIn("bot-like", tags.compute(facts(buys=6, sells=6, hold_minutes=10.0), buy_times=buys, sell_times=sells_slow))

    def test_median_hold_from_times(self):
        buys = [T0, T0 + 10 * MIN]
        sells = [T0 + 1 * MIN, T0 + 30 * MIN]                 # 1 хв і 20 хв → медіана 10.5
        self.assertAlmostEqual(tags.median_hold_minutes(buys, sells), 10.5)
        self.assertIsNone(tags.median_hold_minutes([], sells))

    def test_history_tags(self):
        t = tags.compute(facts(bought_before_range=True, bought_after_range=True, source="entry-only"))
        self.assertEqual(t, ["pre-range", "re-bought"])                     # no-exits is gone (owner, 04.10)
        self.assertTrue(all(k in tags.DEFS for k in t))
        self.assertNotIn("no-exits", tags.DEFS)

    def test_never_sold_only_when_its_sells_were_read(self):
        # owner, 04.10: «never sold» instead of no-exits — but only where we read the sells and found none
        self.assertIn("never-sold", tags.compute(facts(sells=0)))
        self.assertNotIn("never-sold", tags.compute(facts(sells=2)))
        self.assertNotIn("never-sold", tags.compute(facts(sells=None, source="entry-only")))   # beyond the cap: unknown
        self.assertNotIn("never-sold", tags.compute(facts(buys=0, sells=0)))                   # nothing bought here

    def test_dormant_counts_whole_days_from_a_week(self):
        buy = T0 + 30 * 24 * H
        self.assertEqual(tags.dormant_days(buy, buy - 7 * 24 * H), 7)
        self.assertEqual(tags.dormant_days(buy, buy - 23 * 24 * H - 5 * H), 23)
        self.assertIsNone(tags.dormant_days(buy, buy - 6 * 24 * H))             # less than a week: awake
        self.assertIsNone(tags.dormant_days(buy, None))                          # the buy was its first transaction
        self.assertEqual(tags.with_tag(["sniper", "bundle"], "dormant"), ["sniper", "dormant", "bundle"])

    def test_tokens_that_arrived_without_a_buy_are_not_called_a_purchase(self):
        # продав більше, ніж купував: це переказ, а не покупка до діапазону — два різні факти, два різні теги
        t = tags.compute(facts(partial_history=True))
        self.assertEqual(t, ["transfer-in"])
        self.assertNotIn("pre-range", t)
        t = tags.compute(facts(bought_before_range=True))
        self.assertEqual(t, ["pre-range"])
        self.assertNotIn("transfer-in", t)
        t = tags.compute(facts(bought_before_range=True, partial_history=True))
        self.assertEqual(t, ["pre-range", "transfer-in"])                 # обидва можуть бути разом
        self.assertTrue(all(k in tags.DEFS for k in t))


if __name__ == "__main__":
    unittest.main()
