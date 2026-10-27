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

    def test_advanced_and_pro_differ_only_in_the_month(self):
        adv, pro = settings.load({"early": {"plan": "advanced"}}), settings.load({"early": {"plan": "pro"}})
        self.assertEqual((adv["credits_month"], pro["credits_month"]), (200_000, 1_000_000))
        self.assertEqual((adv["credits_reserve_pct"], adv["st_concurrency"]), (5, 8))
        self.assertEqual({k: v for k, v in adv.items() if k not in ("plan", "credits_month")},
                         {k: v for k, v in pro.items() if k not in ("plan", "credits_month")})

    def test_the_repo_config_fits_the_plan(self):
        from pathlib import Path
        from tracced import config
        s = settings.load(config.load_config(str(Path(__file__).resolve().parent.parent / "config.yaml")))
        self.assertEqual((s["plan"], s["credits_month"]), ("advanced", 200_000))
        self.assertLessEqual(s["run_requests_per_day"] * 30, s["credits_month"])                  # runs alone fit the month
        self.assertLessEqual(s["run_cap_requests"], s["run_requests_per_day"] // 2)                # two runs fit a day

    def test_explicit_override_beats_plan(self):
        s = settings.load({"early": {"plan": "advanced", "max_wallet_lookups": 10, "max_window_pages": 50}})
        self.assertEqual((s["max_wallet_lookups"], s["max_window_pages"], s["max_trade_pages"]), (10, 50, 2000))

    def test_unknown_plan(self):
        with self.assertRaises(ValueError):
            settings.load({"early": {"plan": "gold"}})


if __name__ == "__main__":
    unittest.main()
