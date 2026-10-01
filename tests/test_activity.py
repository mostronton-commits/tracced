"""Лічильники угод гаманців, за якими стежить потік: з якого моменту, ковзні 7 діб, забування, файл, зіпсований файл."""
import json
import os
import tempfile
import unittest

from tracced.web.activity import Activity, HOUR_MS

NOW = 1_790_800_000_000          # 2026-09-30
DAY = 24 * HOUR_MS


class TestActivity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "usage", "activity.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_only_while_watched_over_a_rolling_week(self):
        a = Activity(self.path)
        a.bump("W", "buy", NOW)                              # not watched yet: nothing counted
        self.assertEqual(a.of(["W"], NOW), {})
        a.watch({"W", "Q"}, NOW - 8 * DAY)
        a.bump("W", "buy", NOW - 1000)
        a.bump("W", "sell", NOW - 500)
        a.bump("W", "buy", NOW - 6 * DAY)                    # inside the week
        a.bump("W", "buy", NOW - 7 * DAY - 2 * HOUR_MS)      # just outside it
        a.bump("W", "swap", NOW)                             # not a trade side
        self.assertEqual(a.of(["W"], NOW)["W"], {"buys": 2, "sells": 1, "last": NOW - 500, "since": NOW - 8 * DAY})
        self.assertEqual(a.of(["Q"], NOW)["Q"]["buys"], 0)   # watched, quiet
        a.watch({"Q"}, NOW)                                  # W is no longer watched: forgotten
        self.assertNotIn("W", a.of(["W", "Q"], NOW))
        a.watch({"W", "Q"}, NOW)                             # back: counting starts again
        self.assertEqual(a.of(["W"], NOW)["W"], {"buys": 0, "sells": 0, "last": 0, "since": NOW})

    def test_save_keeps_eight_days_and_the_bookmark(self):
        a = Activity(self.path)
        a.watch({"W"}, NOW - 9 * DAY)
        a.bump("W", "buy", NOW - 9 * DAY)
        a.bump("W", "sell", NOW)
        a.seen("W", "SIG")
        self.assertTrue(a.write(a.snapshot(NOW)))
        self.assertIsNone(a.snapshot(NOW))                   # nothing new: nothing to write
        b = Activity(self.path)
        self.assertEqual(len(b.data["W"]["h"]), 1)           # the 9-day-old hour is gone
        self.assertEqual((b.of(["W"], NOW)["W"]["sells"], b.last_sig("W")), (1, "SIG"))

    def test_a_damaged_file_does_not_break_the_page(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"W": {"h": {"2026-09-30T10": [1, "x"], "bad": [1, 1]}, "since": NOW}, "V": "bad",
                       "U": {"h": {"2026-09-30T10": [2, 1]}, "last": NOW, "since": NOW, "sig": 5}, "Z": {"h": {}}}, f)
        a = Activity(self.path)
        self.assertEqual(set(a.data), {"W", "U"})
        self.assertEqual(a.data["W"]["h"], {})
        self.assertEqual((a.data["U"]["h"], a.last_sig("U")), ({"2026-09-30T10": [2, 1]}, ""))


if __name__ == "__main__":
    unittest.main()
