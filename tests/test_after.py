"""«Що було після алерту»: перші покупки з 30 днів гаманця і що токен зробив далі. Без мережі."""
import unittest

from tracced.web import after

NOW = 1_790_000_000_000
H, M, D = after.HOUR, after.MIN, after.DAY


def card(*tokens):
    return {"recent": [{"mint": m, "symbol": s, "trades": tr} for m, s, tr in tokens]}


def candles(t0, highs, lows=None, closes=None, step=after.STEP):
    """Свічки по 5 хвилин, перша — та, в якій сталася покупка (її пік до покупки не рахується)."""
    start = t0 - t0 % step
    return [{"time": start + i * step, "high": h, "low": (lows or highs)[i], "close": (closes or highs)[i]} for i, h in enumerate(highs)]


class TestMoments(unittest.TestCase):
    def test_the_first_buy_of_each_token_in_the_window(self):
        c = card(("A", "AAA", [[NOW - 3 * D, "b", 50.0, 100, 0.5], [NOW - 2 * D, "b", 20.0, 40, 0.5], [NOW - D, "s", 90.0, 140, 0.64]]),
                 ("B", "BBB", [[NOW - 20 * D, "b", 10.0, 10, 1.0], [NOW - D, "b", 30.0, 15, 2.0]]),     # bought before: «more»
                 ("C", "CCC", [[NOW - 9 * D, "b", 10.0, 10, 1.0]]),                                      # older than 7 days
                 ("Z", "ZZZ", [[NOW - D, "s", 10.0, 10, 1.0]]))                                          # only a sale
        ms = {m["mint"]: m for m in after.moments(c, "W", NOW)}
        self.assertEqual(sorted(ms), ["A", "B"])
        self.assertEqual((ms["A"]["t"], ms["A"]["price"], ms["A"]["usd"], ms["A"]["new"]), (NOW - 3 * D, 0.5, 50.0, True))
        self.assertFalse(ms["B"]["new"])
        self.assertEqual(ms["B"]["wallet"], "W")


class TestOutcome(unittest.TestCase):
    def test_peak_dip_now_and_its_exit_from_its_buy_price(self):
        t0 = (NOW - 30 * H) // after.STEP * after.STEP          # a candle starts at t0; the buy is two minutes into it
        m = {"t": t0 + 2 * M, "price": 1.0}
        # the buy's own candle had a high of 9 before the buy: it does not count
        cs = candles(t0, [9.0, 1.2, 3.0, 2.5] + [1.5] * 300, lows=[0.5, 0.7, 2.0, 2.0] + [1.4] * 300)
        trades = [[t0 + 2 * M, "b", 100.0, 100, 1.0], [t0 + 40 * M, "s", 200.0, 50, 4.0], [t0 + 60 * M, "s", 100.0, 50, 2.0]]
        o = after.outcome(m, cs, trades, NOW)
        self.assertEqual(o["peak_x"], 3.0)
        self.assertEqual(o["peak_min"], round((10 * M + after.STEP / 2 - 2 * M) / M))   # the middle of the peak's candle
        self.assertEqual(o["dip_x"], 0.7)                         # the lowest before the peak
        self.assertEqual(o["now_x"], 1.5)
        self.assertTrue(o["at_end"])                              # 24 h passed: «now» is the price at 24 h
        self.assertEqual((o["exit_x"], o["exit_min"], o["sold_pct"]), (3.0, 38, 100))   # (50×4 + 50×2) / 100

    def test_never_below_and_still_holding(self):
        t0 = NOW - 2 * H
        o = after.outcome({"t": t0, "price": 1.0}, candles(t0, [1.0, 1.1, 1.3], lows=[1.0, 1.05, 1.2]), [[t0, "b", 10.0, 10, 1.0]], NOW)
        self.assertIsNone(o["dip_x"])
        self.assertFalse(o["at_end"])
        self.assertEqual((o["exit_x"], o["sold_pct"]), (None, None))
        self.assertEqual(after.outcome({"t": t0, "price": 1.0}, [], [], NOW)["peak_x"], None)   # no candles: no numbers

    def test_summary(self):
        rows = [{"peak_x": 3.0, "exit_x": 1.5, "now_x": 1.0}, {"peak_x": 1.2, "exit_x": None, "now_x": 0.5}, {"peak_x": None}]
        s = after.summary(rows)
        self.assertEqual((s["n"], s["peak"], s["doubled"], s["priced"], s["exit"], s["exits"], s["now"]), (3, 2.1, 1, 2, 1.5, 1, 0.75))


if __name__ == "__main__":
    unittest.main()
