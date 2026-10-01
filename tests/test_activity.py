"""Лічильники угод гаманців зі списків: дні, межа 7 днів, забування, файл, зіпсований файл."""
import json
import os
import tempfile
import unittest

from tracced.web.activity import Activity, DAY_MS

NOW = 1_790_800_000_000          # 2026-09-30


class TestActivity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "usage", "activity.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_by_day_and_the_last_trade(self):
        a = Activity(self.path)
        a.bump("PK", "W", "buy", NOW - 1000)
        a.bump("PK", "W", "buy", NOW - 2 * DAY_MS)
        a.bump("PK", "W", "sell", NOW - 500)
        a.bump("PK", "W", "buy", NOW - 9 * DAY_MS)           # older than a week: not in the 7 days
        a.bump("PK", "W", "swap", NOW)                       # not a trade side: ignored
        a.bump("OTHER", "W", "sell", NOW)                    # each watcher has their own counts
        self.assertEqual(a.of("PK", NOW)["W"], {"buys": 2, "sells": 1, "last": NOW - 500, "side": "sell"})
        self.assertEqual(a.of("OTHER", NOW)["W"]["sells"], 1)
        self.assertEqual(a.of("NOBODY", NOW), {})

    def test_save_keeps_30_days_and_survives_a_restart(self):
        a = Activity(self.path)
        a.bump("PK", "OLD", "buy", NOW - 40 * DAY_MS)
        a.bump("PK", "W", "sell", NOW)
        self.assertTrue(a.save(NOW))
        self.assertFalse(a.save(NOW))                        # nothing new: no write
        b = Activity(self.path)
        self.assertNotIn("OLD", b.of("PK", NOW))             # no trades in 30 days: forgotten
        self.assertEqual(b.of("PK", NOW)["W"]["sells"], 1)
        b.forget("PK", "W")
        b.save(NOW)
        self.assertEqual(Activity(self.path).of("PK", NOW), {})

    def test_a_damaged_file_does_not_break_the_page(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            json.dump({"PK": {"W": {"d": {"2026-09-30": [1, "x"]}}, "V": "bad", "U": {"d": {"2026-09-30": [2, 1]}, "last": NOW}}, "Q": 5}, f)
        a = Activity(self.path)
        self.assertEqual(a.of("PK", NOW), {"U": {"buys": 2, "sells": 1, "last": NOW, "side": None}})


if __name__ == "__main__":
    unittest.main()
