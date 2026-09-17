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
        t = tags.compute(facts(partial_history=True, bought_after_range=True, source="entry-only"))
        self.assertEqual(t, ["pre-range", "re-bought", "no-exits"])
        self.assertTrue(all(k in tags.DEFS for k in t))


if __name__ == "__main__":
    unittest.main()
