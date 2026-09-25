"""Журнал подій і підрахунки дашборда власника: без сервера і без мережі."""
import datetime
import json
import os
import tempfile
import unittest

from tracced.web import usage
from tracced.web.accounts import EventLog

SEP_2026 = 1_789_000_000_000          # 2026-09-10 UTC
AUG_2026 = SEP_2026 - 31 * 86_400_000


class TestEventLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.legacy = os.path.join(self.tmp.name, "_events.jsonl")
        self.log = EventLog(os.path.join(self.tmp.name, "usage"), legacy=self.legacy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_line_lands_in_the_file_of_its_month(self):
        self.log.add("P", "signin", ts_ms=AUG_2026, wallet="Phantom", n=None)
        self.log.add_many([{"ts_ms": SEP_2026, "pubkey": "P", "event": "view", "page": "job"}])
        files = sorted(os.listdir(os.path.join(self.tmp.name, "usage")))
        self.assertEqual(files, ["2026-08.jsonl", "2026-09.jsonl"])
        with open(os.path.join(self.tmp.name, "usage", "2026-08.jsonl")) as f:
            rec = json.loads(f.readline())
        self.assertEqual(rec, {"ts_ms": AUG_2026, "pubkey": "P", "event": "signin", "wallet": "Phantom"})   # None не пишеться

    def test_read_merges_the_old_file_and_keeps_time_order(self):
        with open(self.legacy, "w") as f:
            f.write(json.dumps({"ts_ms": AUG_2026 - 5, "pubkey": "P", "event": "signin"}) + "\nnot json\n")
        self.log.add("P", "view", ts_ms=SEP_2026 + 2)
        self.log.add("P", "analyze", ts_ms=SEP_2026 + 1)                  # пачка кліків могла прийти пізніше за подію
        self.assertEqual([e["event"] for e in self.log.read()], ["signin", "analyze", "view"])
        self.assertEqual([e["event"] for e in self.log.read(since_ms=SEP_2026)], ["analyze", "view"])
        self.assertEqual([e["event"] for e in self.log.read(until_ms=AUG_2026)], ["signin"])

    def test_tail_holds_only_actions_newest_first_across_months(self):
        with open(self.legacy, "w") as f:
            f.write(json.dumps({"ts_ms": 1, "pubkey": "guest", "event": "waitlist"}) + "\n")
        self.log.add("P", "save_wallets", ts_ms=AUG_2026, n=1)
        self.log.add("P", "view", ts_ms=SEP_2026, page="job")
        self.log.add("P", "spend", ts_ms=SEP_2026 + 1, st=3)
        self.log.add("P", "analyze", ts_ms=SEP_2026 + 2)
        self.assertEqual([e["event"] for e in self.log.tail()], ["analyze", "save_wallets", "waitlist"])
        self.assertEqual([e["event"] for e in self.log.tail(2, kinds=None)], ["analyze", "spend"])

    def test_prune_keeps_the_last_months(self):
        d = os.path.join(self.tmp.name, "usage")
        for m in ("2025-08", "2025-09", "2026-08", "2026-09"):
            open(os.path.join(d, m + ".jsonl"), "w").close()
        self.assertEqual(self.log.prune(13, now_ms=SEP_2026), 1)         # вересень 2025 — тринадцятий місяць, лишається
        self.assertEqual(sorted(os.listdir(d)), ["2025-09.jsonl", "2026-08.jsonl", "2026-09.jsonl"])


class TestBeaconBatch(unittest.TestCase):
    NOW = 1_790_000_000_000

    def test_only_named_clicks_with_short_values_pass(self):
        addr = "9ALkCa" + "x" * 38
        body = {"e": [["sort", {"key": "real", "dir": "desc", "via": "head", "extra": "no"}, 5_000],
                      ["copy", {"what": addr}, 5_000],                            # адреса не проходить
                      ["filter", {"k": "hello world, I typed this"}, 5_000],    # набраний текст — теж
                      ["select", {"count": float("nan")}, 5_000],
                      ["leave", {"secs": 1e12}, 5_000],
                      ["pin", {"on": True}, 5_000],
                      ["rm -rf", {}, 5_000], "junk", ["card-open", "not a dict", 1]]}
        out = usage.clean_batch(body, self.NOW)
        self.assertEqual([(e["name"], e["p"]) for e in out],
                         [("sort", {"key": "real", "dir": "desc", "via": "head"}), ("copy", {}), ("filter", {}),
                          ("select", {}), ("leave", {"secs": 1_000_000_000}), ("pin", {"on": True})])

    def test_the_browser_clock_only_orders_a_batch(self):
        out = usage.clean_batch({"e": [["tf", {"tf": "1m"}, 1_000], ["tf", {"tf": "5m"}, 61_000], ["tf", {"tf": "1h"}, 10**15]]}, self.NOW)
        self.assertEqual([e["ts"] for e in out], [self.NOW - usage.LAG_MAX_MS, self.NOW - usage.LAG_MAX_MS, self.NOW])
        out = usage.clean_batch({"e": [["tf", {}, 1_000], ["tf", {}, 61_000]]}, self.NOW)
        self.assertEqual([e["ts"] for e in out], [self.NOW - 60_000, self.NOW])

    def test_at_most_thirty_and_junk_bodies(self):
        self.assertEqual(len(usage.clean_batch({"e": [["tf", {}, 1]] * 100}, self.NOW)), 30)
        for body in (None, [], {"e": "x"}, {"e": {}}, {}):
            self.assertEqual(usage.clean_batch(body, self.NOW), [])

    def test_the_page_comes_from_the_referer_of_this_site(self):
        h = "tracced.xyz"
        mint = "8" * 44
        cases = {"https://tracced.xyz/": ("home", None), f"https://tracced.xyz/token?mint={mint}&from=x": ("token", mint),
                 "https://tracced.xyz/job/98kfF7_20260915-1930_1950": ("job", "98kfF7_20260915-1930_1950"),
                 "https://tracced.xyz/me": ("me", None), "https://tracced.xyz/docs": ("docs", "index"),
                 "https://tracced.xyz/docs/limits": ("docs", "limits"), "https://tracced.xyz/token?mint=<script>": ("token", None),
                 "https://tracced.xyz/connect": ("other", None)}
        for ref, want in cases.items():
            self.assertEqual(usage.page_of(ref, h), want, ref)
        for ref in ("https://tracced.xyz/admin", "https://tracced.xyz/admin/w/x", "https://evil.example/job/x", "", "not a url"):
            self.assertIsNone(usage.page_of(ref, h), ref)


class TestZone(unittest.TestCase):
    def test_warsaw_resolves_in_the_image(self):
        tz = usage.zone("Europe/Warsaw")                                 # pip tzdata: у slim-образі системної бази нема
        self.assertEqual(datetime.datetime(2026, 9, 25, 22, 30, tzinfo=datetime.timezone.utc).astimezone(tz).day, 26)

    def test_an_unknown_zone_is_utc(self):
        self.assertIs(usage.zone("Mars/Olympus"), datetime.timezone.utc)
        noon = datetime.datetime(2026, 9, 25, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(noon.astimezone(usage.zone("")).hour, 12)      # не задано — UTC


if __name__ == "__main__":
    unittest.main()
