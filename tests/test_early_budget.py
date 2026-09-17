import unittest

from tracced.early.budget import Caps, budget_message, choose_mode, estimate_gap_pages

MIN = 60_000


class TestChooseMode(unittest.TestCase):
    def test_paiddoge_free_plan_prefers_full_range(self):
        # 1 544 ранніх, повний діапазон ≈243 сторінки, стеля 300 сторінок / 300 гаманців → повний
        c = choose_mode(243, 1544, Caps(pages_left=266, lookups=300))
        self.assertEqual((c.mode, c.cost, c.covered, c.total), ("trades", 243, 1544, 1544))
        self.assertIn("covers everyone", c.reason)

    def test_old_caps_left_most_wallets_uncovered(self):
        c = choose_mode(243, 1544, Caps(pages_left=166, lookups=250))
        self.assertEqual((c.mode, c.covered, c.cost_full), ("wallet-trades", 250, 243))
        self.assertIn("over the cap", c.reason)

    def test_few_wallets_cheaper_per_wallet(self):
        c = choose_mode(50, 9, Caps(266, 300))
        self.assertEqual((c.mode, c.cost, c.covered), ("wallet-trades", 9, 9))

    def test_full_cheaper_than_wallets(self):
        self.assertEqual(choose_mode(5, 9, Caps(266, 300)).mode, "trades")
        self.assertEqual(choose_mode(9, 9, Caps(266, 300)).mode, "trades")      # нічия → повний

    def test_all_cached(self):
        c = choose_mode(0, 9, Caps(266, 300))
        self.assertEqual((c.mode, c.cost), ("trades", 0))

    def test_completeness_beats_cost(self):
        self.assertEqual(choose_mode(450, 400, Caps(1966, 300)).mode, "trades")

    def test_neither_complete(self):
        c = choose_mode(2500, 400, Caps(1966, 300))
        self.assertEqual((c.mode, c.covered, c.total), ("wallet-trades", 300, 400))

    def test_no_early_wallets(self):
        c = choose_mode(40, 0, Caps(266, 300))
        self.assertEqual((c.cost, c.covered), (0, 0))

    def test_window_already_over_run_cap(self):
        self.assertEqual(choose_mode(3, 1, Caps(-2, 10)).mode, "wallet-trades")


class TestEstimateAndGuard(unittest.TestCase):
    def test_estimate_gap_pages(self):
        self.assertEqual(estimate_gap_pages(8456, 37 * MIN, 246 * MIN), 225)
        self.assertEqual(estimate_gap_pages(8456, 37 * MIN, 246 * MIN, margin=1.15), 259)
        self.assertEqual(estimate_gap_pages(3, 20 * MIN, 30 * MIN), 1)
        self.assertEqual(estimate_gap_pages(0, 20 * MIN, 30 * MIN), 1)
        self.assertEqual(estimate_gap_pages(100, 20 * MIN, 0), 0)

    def test_budget_message(self):
        m = budget_message(400, 1369, 25)
        self.assertIn("about 400 requests", m); self.assertIn("1,369 left", m)
        self.assertIsNone(budget_message(277, 1369, 0))          # охоронець вимкнено (advanced)
        self.assertIsNone(budget_message(10, None, 25))           # /credits не відповів → не блокуємо
        self.assertIsNone(budget_message(300, 1369, 25))          # 342 дозволено
        self.assertIsNone(budget_message(0, 1369, 25))


if __name__ == "__main__":
    unittest.main()
