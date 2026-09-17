import unittest

from tracced.web import chart

T0 = 1_000_000_000_000          # 2001-09-09 01:46:40 UTC
H = 3_600_000


class TestFormatting(unittest.TestCase):
    def test_fmt_mcap(self):
        cases = {980: "980", 1500: "1.5K", 500_000: "500K", 1_234_567: "1.2M", 12_300_000: "12M",
                 1_000_000: "1M", 2_500_000_000: "2.5B", -127: "-127", None: "—", "x": "—",
                 999_982_232: "1B", 999_600: "1M"}
        for v, want in cases.items():
            self.assertEqual(chart.fmt_mcap(v), want, v)

    def test_fmt_dt(self):
        self.assertEqual(chart.fmt_dt(T0), "Sep 9, 01:46")
        self.assertEqual(chart.fmt_dt(T0, year=True, utc=True), "Sep 9, 2001 01:46 UTC")
        self.assertEqual(chart.fmt_dt(None), "—")

    def test_input_roundtrip(self):
        s = chart.to_input(T0)
        self.assertEqual(s, "2001-09-09T01:46")
        self.assertEqual(chart.from_input(s), T0 - 40_000)      # seconds dropped
        self.assertIsNone(chart.from_input(""))
        self.assertIsNone(chart.from_input("garbage"))


class TestCandles(unittest.TestCase):
    def test_auto_tf(self):
        self.assertEqual(chart.auto_tf(3 * H), "1m")
        self.assertEqual(chart.auto_tf(3 * 24 * H), "5m")
        self.assertEqual(chart.auto_tf(20 * 24 * H), "15m")
        self.assertEqual(chart.auto_tf(90 * 24 * H), "1h")

    def test_snap_range(self):
        a, b = chart.snap_range(1_000_100, 1_010_000, "1m")          # chunk 12h = 43200 s
        self.assertEqual(a % 43200, 0)
        self.assertEqual(b % 43200, 0)
        self.assertLessEqual(a, 1_000_100)
        self.assertGreaterEqual(b, 1_010_000)

    def test_candles_mcap(self):
        raw = [{"time": T0 + 60_000, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
               {"time": T0, "open": 0.9, "high": 1.0, "low": 0.8, "close": 1.0},
               {"time": T0, "open": 0.9, "high": 1.0, "low": 0.8, "close": 1.0},      # duplicate
               {"time": T0 + 120_000, "close": 0}]                                   # empty candle
        out = chart.candles_mcap(raw, 1_000_000)
        self.assertEqual([c["time"] for c in out], [T0 // 1000, T0 // 1000 + 60])
        self.assertAlmostEqual(out[1]["high"], 1_200_000)
        self.assertAlmostEqual(out[0]["close"], 1_000_000)


if __name__ == "__main__":
    unittest.main()
