import unittest

from tracced.early import settings


class TestSettings(unittest.TestCase):
    def test_free_plan_caps(self):
        s = settings.load()
        self.assertEqual((s["plan"], s["max_trade_pages"], s["max_wallet_lookups"], s["budget_guard_pct"]), ("free", 300, 500, 25))

    def test_advanced_plan_caps(self):
        s = settings.load({"early": {"plan": "advanced"}})
        self.assertEqual((s["max_trade_pages"], s["max_wallet_lookups"], s["max_window_pages"], s["budget_guard_pct"]), (2000, 3000, 400, 0))
        self.assertLess(s["pause_s"], 0.1)

    def test_explicit_override_beats_plan(self):
        s = settings.load({"early": {"plan": "advanced", "max_wallet_lookups": 10, "max_window_pages": 50}})
        self.assertEqual((s["max_wallet_lookups"], s["max_window_pages"], s["max_trade_pages"]), (10, 50, 2000))

    def test_unknown_plan(self):
        with self.assertRaises(ValueError):
            settings.load({"early": {"plan": "gold"}})


if __name__ == "__main__":
    unittest.main()
