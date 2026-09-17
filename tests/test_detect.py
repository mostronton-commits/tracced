import copy
import unittest

from tracced.config import DEFAULTS
from tracced.engine.detect import detect_pumps

SUPPLY = 1_000_000  # mcap = close * SUPPLY (close 0.1 → $100k)


def series():
    s = []
    t = 1_000_000_000_000
    step = 300_000  # 5m
    for k in range(30):            # плоская база: mcap $100k
        s.append((t + k * step, 0.1, 100))
    for k, c in enumerate([0.15, 0.3, 0.6, 1.0, 1.2]):   # разгон до $1.2M
        s.append((t + (30 + k) * step, c, 500))
    return s


class TestDetect(unittest.TestCase):
    def cfg(self):
        c = copy.deepcopy(DEFAULTS)
        c["detect"].update({"lookback": 24, "pump_multiple": 2.0,
                            "breakout_ratio": 1.3, "min_peak_mcap": 500_000,
                            "merge_gap_min": 60})
        return c

    def test_detects_one_pump(self):
        p = detect_pumps(series(), SUPPLY, self.cfg())
        self.assertEqual(len(p), 1)
        self.assertLess(p[0]["acc_start"], p[0]["pump_start"])   # накопление до старта
        self.assertGreaterEqual(p[0]["peak_mcap"], 500_000)

    def test_significance_filter_drops_small(self):
        c = self.cfg()
        c["detect"]["min_peak_mcap"] = 5_000_000   # выше пика ($1.2M) → отсеет
        self.assertEqual(len(detect_pumps(series(), SUPPLY, c)), 0)


if __name__ == "__main__":
    unittest.main()
