import unittest

from tracced.config import DEFAULTS
from tracced.early import settings, window

T0 = 1_000_000_000_000
MIN = 60_000
H = 3_600_000


def candles(closes):
    return [{"time": T0 + i * MIN, "open": c, "high": c, "low": c, "close": c, "volume": 1}
            for i, c in enumerate(closes)]


class TestWindow(unittest.TestCase):
    def test_validate(self):
        ok = window.validate(T0, T0 + H, created_ms=T0 - H, now_ms=T0 + 3 * H)
        self.assertEqual(ok, [])
        self.assertTrue(window.validate(T0 + H, T0))                          # від ≥ до
        self.assertTrue(window.validate(T0, T0 + H, created_ms=T0 + 5 * H))
        self.assertTrue(window.validate(T0, T0 + H, now_ms=T0 + 30 * MIN))
        self.assertTrue(window.validate(None, T0))
        self.assertTrue(window.validate(T0, T0 + 30 * H, max_window_ms=24 * H))   # діапазон > 24 год
        self.assertEqual(window.validate(T0, T0 + H, max_window_ms=24 * H), [])

    def test_mcap_at(self):
        s = [(0, 1.0), (10, 2.0), (20, 3.0)]
        self.assertEqual(window.mcap_at(s, 15), 2.0)
        self.assertEqual(window.mcap_at(s, -5), 1.0)
        self.assertEqual(window.mcap_at(s, 100), 3.0)
        self.assertIsNone(window.mcap_at([], 5))

    def test_suggest_on_synthetic_pump(self):
        closes = [0.1] * 40 + [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6] + [0.6] * 20
        supply = 10_000_000                       # база 1M → пік 6M (≥ min_peak 1M)
        hints = window.suggest(candles(closes), supply, {"detect": dict(DEFAULTS["detect"])})
        self.assertEqual(len(hints), 1)
        h = hints[0]
        self.assertEqual(h["pump_start"], T0 + 40 * MIN)      # відрив: перша свічка ≥ база×1.3
        self.assertEqual(h["peak_time"], T0 + 49 * MIN)       # перша свічка з максимумом
        self.assertAlmostEqual(h["peak_mcap"], 6_000_000, delta=1)
        self.assertLess(h["acc_start"], h["pump_start"])

    def test_suggest_flat_is_empty(self):
        self.assertEqual(window.suggest(candles([0.1] * 60), 10_000_000,
                                        {"detect": dict(DEFAULTS["detect"])}), [])
        self.assertEqual(window.suggest([], 1, {"detect": dict(DEFAULTS["detect"])}), [])

    def test_chart_interval(self):
        s = settings.load()
        self.assertEqual(settings.chart_interval(3 * H, s), "1m")
        self.assertEqual(settings.chart_interval(24 * H, s), "5m")
        self.assertEqual(settings.chart_interval(7 * 24 * H, s), "15m")
        self.assertEqual(settings.chart_interval(30 * 24 * H, s), "1h")

    def test_settings_merge(self):
        s = settings.load({"early": {"min_invested_usd": 6, "chart_span_hours": {"1m": 2}}})
        self.assertEqual(s["min_invested_usd"], 6)
        self.assertEqual(s["chart_span_hours"]["1m"], 2)
        self.assertEqual(s["chart_span_hours"]["5m"], 48)        # решта дефолтів лишилась
        self.assertEqual(settings.DEFAULTS["min_invested_usd"], 20)   # дефолти не зіпсовано


if __name__ == "__main__":
    unittest.main()
